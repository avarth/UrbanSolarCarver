# Design note — Simulated benefit weights

**Status:** implemented and shipped (`usc simulate-weights`, `simulated_weights_path`).
The engine's Annex C recurrence is regression-tested against the ETH
RC_BuildingSimulator source (MIT, Jayathissa et al.) to ~1 Wh/year on three
archetypes, plus steady-state closure against an independent network
reduction; the full suite has been validated on a CUDA workstation. One
verification step remains open: the equation block below was cross-checked
against RC_BuildingSimulator's transcription of the annex, and should
additionally be verified against the standard text (EN ISO 13790:2008 §12
and Annex C, or the national adaptation) before results are used in
publication-grade claims.

**Naming:** user-facing text calls the two benefit weightings **simple
weights** (the balance-point rule) and **simulated weights** (this
generator). The tier vocabulary below is retained only as internal design
framing; it appears nowhere in the CLI, configs, docs site, or tutorials.

## 1. Problem and approach

USC's benefit mode weights each sky patch by the radiation of *beneficial*
hours. The simple hour filter is a balance-point Heaviside (hours with
`T_air < balance_temperature − balance_offset` count fully, others not at
all): explainable and code-aligned, but blind to thermal lag, mass state,
and gain saturation.

The upgrade path keeps USC untouched at its natural boundary, the hourly
weighting, and swaps the *generator* of that weighting:

| Generator | Resolves | Cost | Status |
|-----------|----------|------|--------|
| Balance-point Heaviside ("simple") | nothing dynamic | zero | default |
| ISO 13790 monthly utilization factor η(γ, τ), *marginal* form | season + mass | closed form | deferred |
| **ISO 13790 Annex C hourly 5R1C + perturbation attribution ("simulated")** | **hour-resolved lag, diurnal mass state, saturation at operating point** | **seconds** | **shipped** |
| E+ shoebox perturbation | schedules, HVAC detail, multi-zone | heavy setup | not planned |

The monthly-η variant is deferred: the cooling-side loss-utilization sign
conventions (§12.2.1.1) must be transcribed from the standard text, not
memory, and its only role beside the hourly model is as a comparison
baseline. An EnergyPlus generator is not planned; the 5R1C model provides
a solid basis for a massing tool.

All generators emit the same artifact (§5); `simulated_weights_path` in benefit
mode consumes it (§6), so a future generator is a drop-in.

## 2. The 5R1C network (ISO 13790 Annex C)

Nodes: outdoor `θ_e`, supply `θ_sup` (= `θ_e`, no preheating), indoor air
`θ_air`, central surface/star `θ_s`, thermal mass `θ_m` (capacitance `C_m`).

Conductances [W/K]:

- `H_ve` — ventilation: `1200 · b_ek · V · (ACH_tot/3600)` with the heat-
  recovery adjustment `b_ek = 1 − (ACH_vent/ACH_tot) · η_hr` (ISO Annex E).
- `H_tr,is = h_is · A_tot`, `h_is = 3.45 W/m²K`, `A_tot = Λ_at · A_f`,
  `Λ_at = 4.5` — air ↔ surface coupling.
- `H_tr,w = Σ U_w · A_w` — glazing, massless, `θ_e ↔ θ_s`.
- `H_tr,ms = h_ms · A_m`, `h_ms = 9.1 W/m²K` — surface ↔ mass.
- `H_tr,em = 1 / (1/H_tr,op − 1/H_tr,ms)` — opaque envelope remainder,
  `θ_e ↔ θ_m` (standard §12.2.2). *Note: RC_BuildingSimulator simplifies
  this to `U_op·A_op` directly; oracle comparisons must feed identical H
  values so the recurrence is tested, not the parameter derivation.*

Mass class (ISO Table 12), per m² floor area `A_f`:

| Class | A_m | C_m [J/K] |
|-------|-----|-----------|
| very light | 2.5·A_f | 80 000·A_f |
| light | 2.5·A_f | 110 000·A_f |
| medium | 2.5·A_f | 165 000·A_f |
| heavy | 3.0·A_f | 260 000·A_f |
| very heavy | 3.5·A_f | 370 000·A_f |

Gain split (C.1–C.3), with `Φ_int` internal and `Φ_sol` transmitted solar:

```
Φ_ia = 0.5·Φ_int                                        → air node
Φ_m  = (A_m/A_tot) · (0.5·Φ_int + Φ_sol)                → mass node
Φ_st = (1 − A_m/A_tot − H_tr,w/(9.1·A_tot))
       · (0.5·Φ_int + Φ_sol)                            → surface node
```

Heating/cooling power `Φ_HC` enters the air node (standard base case;
emission-system node splits are a deliberate non-goal).

Auxiliary conductances (C.6–C.8):

```
H_tr,1 = 1/(1/H_ve + 1/H_tr,is)
H_tr,2 = H_tr,1 + H_tr,w
H_tr,3 = 1/(1/H_tr,2 + 1/H_tr,ms)
```

Mass-node recurrence (C.4–C.5), Crank–Nicolson over Δt = 1 h:

```
Φ_m,tot = Φ_m + H_tr,em·θ_e
        + H_tr,3·( Φ_st + H_tr,w·θ_e + H_tr,1·(Φ_ia + Φ_HC)/H_ve + H_tr,1·θ_sup ) / H_tr,2

θ_m,t   = [ θ_m,t−1·(C_m/3600 − 0.5·(H_tr,3 + H_tr,em)) + Φ_m,tot ]
        / [ C_m/3600 + 0.5·(H_tr,3 + H_tr,em) ]
```

then `θ_m = (θ_m,t + θ_m,t−1)/2` (C.9), surface and air back-substitution
(C.10–C.11):

```
θ_s   = [ H_tr,ms·θ_m + Φ_st + H_tr,w·θ_e + H_tr,1·(θ_sup + (Φ_ia + Φ_HC)/H_ve) ]
      / [ H_tr,ms + H_tr,w + H_tr,1 ]
θ_air = [ H_tr,is·θ_s + H_ve·θ_sup + Φ_ia + Φ_HC ] / [ H_tr,is + H_ve ]
```

Need calculation per hour (C.4.2, three steps): (1) free-float
(`Φ_HC = 0`); if `θ_air` within set-points → no demand. (2) apply test load
`Φ_HC,10 = 10 W/m² · A_f` and interpolate linearly to the violated
set-point: `Φ_HC,nd = Φ_HC,10 · (θ_set − θ_air,0)/(θ_air,10 − θ_air,0)`.
(3) clamp to system capacity (we default to unlimited). Heating demand
`Q_H` accumulates positive `Φ_HC,nd`; cooling demand `Q_C` accumulates the
magnitude of negative `Φ_HC,nd`.

## 3. Inputs

Archetype (user-supplied; one neutral example ships, **no national
defaults**), in either of two forms:

- **Shoebox shorthand** (preferred for non-experts): `width`, `length`,
  `height`, per-facade `wwr` (window-to-wall ratio keyed north/east/
  south/west), `g_value`, optional `orientation`. Floor area, volume,
  per-facade window areas, `area_window`, and `area_opaque` (opaque walls
  minus glazing, plus roof; slab-on-grade treated adiabatic) are derived
  by `expand_shoebox()`.
- **Explicit areas**: `A_f`, volume `V`, opaque `U·A` (or H_tr,op), window
  `U·A`, per-orientation window area × g-value (`windows` list).

Both forms additionally take ACH (vent + infiltration), heat-recovery
η_hr, mass class, set-points (default 20/26 °C), and flat internal gains
[W/m²] or a 24-value daily profile.

Shading (optional, declared coefficients — deliberately no device
geometry): `shading_permanent` (year-round transmission multiplier) and
`shading_hot` (additional multiplier active during the user-declared
`hot_months`). Each accepts a scalar or a per-facade mapping
(north/east/south/west; windows bin to their nearest cardinal). The
factors multiply `Φ_sol` per window, AND the attribution derivatives are
scaled by the effective hourly transmission `f_eff(t) = Φ_shaded/Φ_unshaded`
so the artifact keeps its exterior-joule semantics: a July joule arriving
behind a deployed awning earns proportionally less harm and benefit.
Declared values are recorded in the artifact provenance.

Climate: one EPW. Hourly transmitted solar
`Φ_sol(t) = Σ_orient A_w·g·I_orient(t)` with `I_orient` from the EPW via
Ladybug's directional-irradiance transposition. Only the *weighting* of
hours leaves the generator; USC's patch geometry never sees these areas.

## 4. Perturbation attribution

For each hour `t`, perturb `Φ_sol(t) → Φ_sol(t) ± ε` and difference the
annual sums (central differences; ε small, e.g. 1 W):

```
benefit[t] = −ΔQ_H/(2ε) ∈ [0, 1]   fraction of a marginal joule offsetting heating
harm[t]    = +ΔQ_C/(2ε) ∈ [0, 1]   fraction becoming cooling load
```

Two series, never pre-scalarized — they map onto benefit mode's default
(benefit only) and `include_harm` (declared composite) semantics.

Implementation: all 8760 perturbed trajectories march as one vectorized
batch (state per copy is 1 scalar `θ_m`; control branches via masks). A
perturbation's influence decays within ~5τ, but the full-year batch is
already O(seconds) — no windowing needed.

Known behaviors, accepted: values are marginal at the archetype's operating
point (WWR/g set the saturation level — provenance metadata records them);
hours near a control-regime switch yield subgradients (central differences
smooth this); strict [0,1] bounds hold up to switching noise and are
clamped with a tolerance check rather than asserted exactly.

## 5. Artifact — `simulated_weights.json`

```json
{
  "schema_version": 1,
  "meta": {
    "method": "iso13790-5r1c-perturbation",
    "epw": "<path/name as given>",
    "archetype": { "...all §3 inputs, expanded form..." },
    "generated": "<iso timestamp>",
    "generator": "usc simulate-weights (iso13790-5r1c)"
  },
  "hourly": {
    "benefit": [8760 floats in [0,1]],
    "harm":    [8760 floats in [0,1]]
  }
}
```

8760 hourly values (TMY, non-leap), index = hour of year, timestep 1.
The generator (`generate_simulated_weights`) also writes a `.png` companion next to the
artifact: benefit and harm as day × hour heatmaps, so the schedule can be
inspected without writing code.

## 6. USC hook

Optional benefit-mode key `simulated_weights_path`. When set:

- the Heaviside filter is replaced: each hour's DNI/DHI in the Wea is
  scaled by `benefit[t]` before the cumulative SkyMatrix — the sky
  integration distributes the weights onto exactly the patches each hour's
  sun and sky occupied (the simple cold-hours filter is the binary special
  case of this mechanism);
- `include_harm: true` additionally subtracts the `harm[t]`-scaled matrix,
  clipped at zero — same semantics and same rationale (shading value never
  rewards mass) as the existing composite;
- balance_temperature / balance_offset are unused → warn if customized;
- the artifact content hash enters the patch-weight cache key, and the
  artifact provenance enters the preprocessing diagnostics;
- with `diagnostic_plots: true`, the run's diagnostics additionally record
  a **comparison dome**: the difference between the consumed weights and
  the simple-rule counterfactual for the same config
  (`sky_patch_comparison_image` + redistribution stats in
  `diagnostic.json`). This keeps run-to-run comparison out of the public
  API: the diagnostics of a single run carry it.

## 7. Validation status

Engine (all passing in `tests/test_simulated_weights.py`): steady-state closure
(demand = Σ H·ΔT − gains, air held at set-point, verified against an
independent series/parallel network reduction); heavier `C_m` flattens
hour-to-hour `θ_m` variance; regression against RC_BuildingSimulator on
three archetype scenarios driven by the bundled Golden TMY3 EPW (annual
demands to ~1 Wh, sampled hourly node states; dry bulb direct; transmitted
solar from Ladybug's isotropic directional irradiance on each scenario's
glazing, g = 0.6). The exact hourly driving arrays are stored verbatim
inside `tests/data/oracle_5r1c_reference.json` alongside the oracle's
derived conductances (its `h_tr,em = U·A` convention is fed to our engine
as-is, so the recurrence is compared, not the parameter derivation).
Tests replay the stored arrays — deterministic, no weather generation, no
EPW parsing in the engine layer. Capture provenance:
`tests/data/capture_oracle_5r1c.py` (note: its oracle/repo paths are
machine-specific and need adjusting before re-capture).

Attribution (passing): winter benefit high with zero harm; summer-afternoon
harm high with benefit ≈ 0; winter-noon benefit stays high (lag credit);
heavier mass class ⇒ flatter diurnal weights. The monthly-η correlation
check is deferred together with the monthly generator itself.

Hook (passing, `tests/test_modes.py` / `test_pipeline.py`): an all-ones
schedule reproduces plain irradiance weights; a binary balance-filter
schedule reproduces the simple-rule weights exactly (the special-case
claim, tested); `include_harm` composite equals clip(benefit−harm, 0);
zero-in-period warns and returns zero weights; end-to-end artifact
consumption with provenance in diagnostics.

End-to-end evaluation on real hardware (CUDA workstation, RTX 3060):
simple vs simulated weights redistribute ~9% of sky-weight mass on the
demo site (east-morning share down, south-west-afternoon share up, the
thermal-lag signature); with `include_harm` the redistribution reaches
~20–30% and concentrates into the low southern band. Tutorial 5
(`examples/5_benefit_5r1c.ipynb`) reproduces the comparison.

## 8. Declared limitations

Single zone, lumped mass: same-hour weighting is facade-independent by
construction (time-of-day carries the direction signal; perimeter-zone
effects are out of scope for a massing tool). Ideal convective conditioning
at the air node; continuous operation, no setback. Fixed ACH — no night
flushing (a schedulable H_ve remains the first extension slot). Shading is
declared, not adaptive: the fixed-calendar `shading_hot` coefficient stands
in for occupant-operated devices; without it, cooling harm is overestimated
(conservative for the opt-in harm channel), and even with it there is no
response to same-day conditions. Flat internal gains. TMY weather. Marginal
linearization at the archetype operating point. Weights derived without the
carve's own shading context (first-order acceptable; one-iteration
robustness check possible). The correlation constants and coupling
coefficients carry the standard's residential-European calibration
provenance.
