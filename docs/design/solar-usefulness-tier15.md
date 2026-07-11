# Design note — Physics-derived solar usefulness for benefit mode (Tier 1.5)

**Status:** draft for author sign-off. The equation block below was
cross-checked against the ETH RC_BuildingSimulator source (MIT, Jayathissa
et al.), which transcribes the same annex; it must additionally be verified
against the standard text (EN ISO 13790:2008 §12 and Annex C, or the
national adaptation) before the engine's results are trusted.

## 1. Problem and approach

USC's benefit mode weights each sky patch by the radiation of *beneficial*
hours. The default hour filter is a balance-point Heaviside (hours with
`T_air < balance_temperature − balance_offset` count fully, others not at
all): explainable and code-aligned, but blind to thermal lag, mass state,
and gain saturation.

The upgrade path keeps USC untouched at its natural boundary — the hourly
weighting — and swaps the *generator* of that weighting:

| Tier | Generator | Resolves | Cost |
|------|-----------|----------|------|
| 0 | Balance-point Heaviside (current default) | nothing dynamic | zero |
| 1 | ISO 13790 monthly utilization factor η(γ, τ), *marginal* form | season + mass | closed form |
| **1.5** | **ISO 13790 Annex C hourly 5R1C model + perturbation attribution** | **hour-resolved lag, diurnal mass state, saturation at operating point** | **seconds** |
| 2 | E+ shoebox perturbation (future) | schedules, HVAC detail, multi-zone | heavy setup |

All tiers emit the same artifact (§5); `usefulness_path` in benefit mode
consumes it (§6). Tier 2 is explicitly out of scope here.

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
defaults**): `A_f`, volume `V`, opaque `U·A` (or H_tr,op), window `U·A`,
per-orientation window area × g-value, ACH (vent + infiltration),
heat-recovery η_hr, mass class, set-points (default 20/26 °C), flat
internal gains [W/m²].

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

## 5. Artifact — `solar_usefulness.json`

```json
{
  "schema_version": 1,
  "meta": {
    "method": "iso13790-5r1c-perturbation",
    "epw": "<path/name as given>",
    "archetype": { "...all §3 inputs verbatim..." },
    "generated": "<iso timestamp>",
    "generator": "usc usefulness <version>"
  },
  "hourly": {
    "benefit": [8760 floats in [0,1]],
    "harm":    [8760 floats in [0,1]]
  }
}
```

8760 hourly values (TMY, non-leap), index = hour of year, timestep 1.

## 6. USC hook

New optional benefit-mode key `usefulness_path`. When set:

- the Heaviside filter is replaced: each hour's DNI/DHI in the Wea is
  scaled by `benefit[t]` before the cumulative SkyMatrix — the sky
  integration distributes usefulness onto exactly the patches each hour's
  sun and sky occupied (the current cold-hours filter is the binary special
  case of this mechanism);
- `include_harm: true` additionally subtracts the `harm[t]`-scaled matrix,
  clipped at zero — same semantics and same rationale (shading value never
  rewards mass) as the existing composite;
- balance_temperature / balance_offset are unused → warn if customized;
- the artifact path and its meta hash enter the patch-weight cache key and
  the preprocessing diagnostics.

## 7. Validation plan

Engine: energy-balance closure (steady state: demand = Σ H·ΔT − gains);
zero-mass and infinite-mass limits; regression against RC_BuildingSimulator
on three archetype scenarios driven by the **bundled Golden TMY3 EPW**
(dry bulb direct; transmitted solar from Ladybug's isotropic directional
irradiance on each scenario's glazing, g = 0.6). The exact hourly driving
arrays are stored verbatim inside `tests/data/oracle_5r1c_reference.json`
alongside the oracle's derived conductances (its `h_tr,em = U·A`
convention is fed to our engine as-is, so the recurrence is compared, not
the parameter derivation), annual demands, and sampled hourly node states.
Tests replay the stored arrays — deterministic, no weather generation, no
EPW parsing in the engine layer. Capture provenance:
`tests/data/capture_oracle_5r1c.py`.

Attribution: winter-night benefit ≈ high with zero harm; summer-afternoon
harm > 0 with benefit ≈ 0; heavier mass class ⇒ flatter diurnal usefulness;
monthly aggregation of 5R1C usefulness correlates with Tier 1 marginal-η.

End-to-end: Tier 0 vs Tier 1.5 weights on the bundled EPW → both run
through the same carve on the demo geometry (the paper's comparison
figure).

## 8. Declared limitations

Single zone, lumped mass: same-hour usefulness is facade-independent by
construction (time-of-day carries the direction signal; perimeter-zone
effects are out of scope for a massing tool). Ideal convective conditioning
at the air node; continuous operation, no setback. Fixed ACH — no night
flushing or operable shading, so cooling harm is overestimated
(conservative for the opt-in harm channel; a schedulable H_ve is the first
extension slot). Flat internal gains. TMY weather. Marginal linearization
at the archetype operating point. Usefulness derived unshaded while USC
creates shading context (first-order acceptable; one-iteration robustness
check possible). The correlation constants and coupling coefficients carry
the standard's residential-European calibration provenance.
