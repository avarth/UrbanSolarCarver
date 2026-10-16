# Scientific Audit Fixes: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix all issues identified in the scientific audit of the UrbanSolarCarver codebase: stale references, schema hardening, documentation gaps, GH component errors, and a latent daylight-mode bug.

**Architecture:** Pure cleanup pass: no new features, no behavioral changes to the carving/scoring/thresholding pipeline. Changes touch: Pydantic schema (1 line), YAML configs (9 files), Python docstrings (4 files), docs (1 file), GH components (3 files), preprocessing period logic (1 file), and tests.

**Tech Stack:** Python, Pydantic v2, YAML, Markdown, pytest

---

## File Map

| Action | File | Responsibility |
|--------|------|---------------|
| Modify | `src/urbansolarcarver/pydantic_schemas.py` | Add `extra='forbid'` to reject unknown YAML keys |
| Modify | `src/urbansolarcarver/api_core/preprocessing.py` | Fix daylight period handling; fix stale docstring |
| Modify | `src/urbansolarcarver/carving.py` | Remove "Otsu" from docstring |
| Modify | `src/urbansolarcarver/carver_cli.py` | Remove "evaluation" from module docstring |
| Modify | `src/urbansolarcarver/sky_patches.py` | Fix false "sum=1" docstring claim |
| Modify | `configs/user_config.yaml` | Remove `score_scale`, fix stale comments |
| Modify | `configs/REFERENCE_all_options.yaml` | Remove `score_scale`, fix stale comments |
| Modify | `configs/config_benefit.yaml` | Add commented defaults block |
| Modify | `configs/config_irradiance.yaml` | Add commented defaults block |
| Modify | `configs/config_daylight.yaml` | Fix stale EPW comment, add defaults block |
| Modify | `configs/config_time_based.yaml` | Add commented defaults block |
| Modify | `configs/config_radiative_cooling.yaml` | Fix false "no analysis period" claim, add period fields, add defaults block |
| Modify | `configs/config_tilted_plane.yaml` | Fix stale EPW/otsu comments, add defaults block |
| Delete | `configs/config_timebased.yaml` | Duplicate of `config_time_based.yaml` |
| Modify | `docs/modes.md` | Remove otsu ref, add violation_count docs, add thresholding guide |
| Modify | `grasshopper/components/USC_AnalysisPeriod.py` | Fix radiative_cooling requirement docs |
| Modify | `grasshopper/components/USC_Config.py` | Fix EPW requirement docs |
| Modify | `grasshopper/components/USC_RadCooling.py` | Add analysis period note |
| Modify | `tests/test_schemas.py` | Add `extra='forbid'` tests |

---

## Task 1: Harden Pydantic schema: reject unknown YAML keys

Unknown keys like `score_scale` or typos like `vocel_size` are currently silently ignored because Pydantic v2 defaults to `extra='ignore'`. This is the single highest-impact UX fix.

**Files:**
- Modify: `src/urbansolarcarver/pydantic_schemas.py:23`
- Test: `tests/test_schemas.py`

- [ ] **Step 1: Write the failing test**

In `tests/test_schemas.py`, add a new test class at the end of the file:

```python
class TestExtraFieldsRejected:
    def test_unknown_key_rejected(self):
        """Unknown YAML keys must raise, not be silently swallowed."""
        with pytest.raises(ValidationError, match="extra"):
            _make_config(score_scale="linear")

    def test_typo_key_rejected(self):
        with pytest.raises(ValidationError, match="extra"):
            _make_config(vocel_size=0.5)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_schemas.py::TestExtraFieldsRejected -v`
Expected: FAIL; Pydantic currently ignores extra fields.

- [ ] **Step 3: Add `extra='forbid'` to UserConfig**

In `src/urbansolarcarver/pydantic_schemas.py`, add a `model_config` inside the `UserConfig` class. At the top of the file, amend the pydantic import:

```python
from pydantic import BaseModel, Field, field_validator, model_validator, ConfigDict
```

Then inside the `UserConfig` class body, insert as the first line before any fields:

```python
    model_config = ConfigDict(extra="forbid")
```

- [ ] **Step 4: Run tests to verify**

Run: `pytest tests/test_schemas.py -v`
Expected: ALL PASS including the two new tests.

- [ ] **Step 5: Commit**

```
git add src/urbansolarcarver/pydantic_schemas.py tests/test_schemas.py
git commit -m "fix(schema): reject unknown YAML keys with extra='forbid'"
```

---

## Task 2: Remove `score_scale` and fix stale comments in full YAML configs

Both `user_config.yaml` and `REFERENCE_all_options.yaml` contain the dead `score_scale` parameter and list `'otsu'` as a valid threshold. After Task 1, these files would cause a validation error if loaded.

**Files:**
- Modify: `configs/user_config.yaml`
- Modify: `configs/REFERENCE_all_options.yaml`

- [ ] **Step 1: Fix `configs/user_config.yaml`**

Remove the `score_scale` block (lines 42-43: the comment and the value). Change the threshold comment on line 39 from:

```yaml
threshold: 'carve_fraction'  # 'otsu', 'headtail', 'carve_fraction' or numeric value (threshold will be ignored in time-based mode or classification mode)
```

to:

```yaml
threshold: 'carve_fraction'  # 'headtail', 'carve_fraction', or a numeric value. For time-based/tilted_plane, use an integer (violation count).
```

- [ ] **Step 2: Fix `configs/REFERENCE_all_options.yaml`**

Same two edits: remove the `score_scale` block (lines 42-43) and fix the threshold comment (line 39) from:

```yaml
threshold: 'carve_fraction'  # 'otsu', 'headtail', 'carve_fraction' or numeric value
```

to:

```yaml
threshold: 'carve_fraction'  # 'headtail', 'carve_fraction', or a numeric value. For time-based/tilted_plane, use an integer (violation count).
```

- [ ] **Step 3: Verify both configs parse without extra-field errors**

Run:
```bash
python -c "
from urbansolarcarver.pydantic_schemas import UserConfig
try:
    UserConfig(max_volume_path='a.ply', test_surface_path='b.ply',
               out_dir='out', mode='tilted_plane',
               tilted_plane_angle_deg=45.0, voxel_size=2, grid_step=2,
               score_scale='linear')
    print('ERROR: should have rejected score_scale')
except Exception as e:
    print(f'OK: extra field rejected: {type(e).__name__}')
"
```
Expected: `OK: extra field rejected: ValidationError`

- [ ] **Step 4: Commit**

```
git add configs/user_config.yaml configs/REFERENCE_all_options.yaml
git commit -m "fix(config): remove dead score_scale param, fix stale otsu refs in YAML"
```

---

## Task 3: Fix stale comments and add defaults to per-mode YAML configs

Several minimal configs have factually wrong comments about which modes need EPW or analysis periods. All minimal configs hide important defaults. Also delete the duplicate `config_timebased.yaml`.

**Files:**
- Modify: 6 config files
- Delete: `configs/config_timebased.yaml`

- [ ] **Step 1: Fix `configs/config_radiative_cooling.yaml`**

This file has two errors: (a) line 4 says "No analysis period needed", which is wrong: the schema requires it; (b) it's missing the period fields, so it will fail validation.

Replace the full file with:

```yaml
# UrbanSolarCarver: Radiative cooling mode [EXPERIMENTAL]
# Carves voxels based on long-wave radiative cooling potential of the night sky.
# Uses Martin-Berdahl (1984) emissivity and Bliss (1961) angular attenuation.
# Assumes clear sky, horizontal analysis surfaces (flat roofs).
# Typical use: urban heat island mitigation, passive cooling envelope design.
#
# WARNING: This mode is experimental. The physics model assumes clear-sky
# conditions and a single dew-point value. Results should be validated.

# --- Required paths ---
max_volume_path:    "path/to/maxVolume.ply"
test_surface_path:  "path/to/testSurfaces.ply"
epw_path:           "path/to/weather.epw"
out_dir:            "path/to/output"

mode: radiative_cooling

# Analysis period: defines which nighttime hours to analyse
start_month: 6
start_day:   1
start_hour:  20
end_month:   8
end_day:     31
end_hour:    6

# Radiative cooling parameters
dew_point_celsius: 14.0   # night-time dew-point (C)
bliss_k:            1.8   # angular attenuation constant (Bliss 1961)

# Grid
voxel_size: 1.0

# Thresholding
threshold: carve_fraction
carve_fraction: 0.7

# --- Defaults you may want to override --------------------------------------
# grid_step:       1.0    # test-surface sampling spacing in metres
# ray_length:      300.0  # max ray distance in metres
# apply_smoothing: false  # true = SDF smooth + marching cubes
# device:          'auto' # 'auto', 'cpu', or 'cuda'
# See REFERENCE_all_options.yaml for the complete parameter list.
```

- [ ] **Step 2: Fix `configs/config_tilted_plane.yaml`**

Two errors: (a) line 9 says EPW "still required for sun path", which is wrong: tilted_plane doesn't use EPW or sun paths; (b) line 25 mentions "otsu".

Replace the full file with:

```yaml
# UrbanSolarCarver: Tilted plane mode
# Carves voxels using a fixed angular plane per compass octant.
# No weather data or analysis period needed; purely geometric.
# Typical use: daylight envelope (Brown & DeKay), street-canyon proportions.

# --- Required paths ---
max_volume_path:    "path/to/maxVolume.ply"
test_surface_path:  "path/to/testSurfaces.ply"
out_dir:            "path/to/output"

mode: tilted_plane

# Plane angle: single value or 8-element list [N, NE, E, SE, S, SW, W, NW]
# 45 deg gives a 1:1 height-to-width ratio (classic daylight envelope)
tilted_plane_angle_deg: 45.0
# Or per-octant: [30, 27, 24, 24, 27, 30, 30, 27]

# Grid
voxel_size: 1.0

# --- Threshold ---
# tilted_plane is binary: a voxel either protrudes above the plane (culled)
# or it does not (kept). Do not set threshold; leave it unset (None).

# --- Defaults you may want to override --------------------------------------
# voxel_size:      1.0    # voxel edge in metres (0.5 = 8x more voxels)
# grid_step:       1.0    # test-surface sampling spacing in metres
# ray_length:      300.0  # max ray distance in metres
# apply_smoothing: false  # true = SDF smooth + marching cubes
# device:          'auto' # 'auto', 'cpu', or 'cuda'
# See REFERENCE_all_options.yaml for the complete parameter list.
```

- [ ] **Step 3: Fix `configs/config_daylight.yaml`**

Line 4 says "No EPW data is used for weighting (only for sun positions)", which is wrong on both counts: daylight uses neither EPW nor sun positions. The CIE overcast sky is purely geometric.

Replace line 4:

```yaml
# No EPW data is used for weighting (only for sun positions).
```

with:

```yaml
# No EPW data is needed: the CIE overcast sky is purely geometric.
# Analysis period is optional (CIE weights are time-invariant).
```

Remove the `epw_path` line (line 10) since daylight mode doesn't need it.

Append a defaults block at the end:

```yaml

# --- Defaults you may want to override --------------------------------------
# voxel_size:      1.0    # voxel edge in metres (0.5 = 8x more voxels)
# grid_step:       1.0    # test-surface sampling spacing in metres
# ray_length:      300.0  # max ray distance in metres
# apply_smoothing: false  # true = SDF smooth + marching cubes
# device:          'auto' # 'auto', 'cpu', or 'cuda'
# See REFERENCE_all_options.yaml for the complete parameter list.
```

- [ ] **Step 4: Add defaults block to remaining configs**

Append the following to `config_benefit.yaml`, `config_irradiance.yaml`:

```yaml

# --- Defaults you may want to override --------------------------------------
# voxel_size:      1.0    # voxel edge in metres (0.5 = 8x more voxels)
# grid_step:       1.0    # test-surface sampling spacing in metres
# ray_length:      300.0  # max ray distance in metres
# carve_fraction:  0.7    # fraction of obstruction weight to remove (0-1)
# threshold:       'carve_fraction'   # or 'headtail', or a numeric value
# min_altitude:    5.0    # ignore sun below this elevation (degrees)
# apply_smoothing: false  # true = SDF smooth + marching cubes
# device:          'auto' # 'auto', 'cpu', or 'cuda'
# See REFERENCE_all_options.yaml for the complete parameter list.
```

Append the following to `config_time_based.yaml`:

```yaml

# --- Defaults you may want to override --------------------------------------
# voxel_size:      1.0    # voxel edge in metres (0.5 = 8x more voxels)
# grid_step:       1.0    # test-surface sampling spacing in metres
# ray_length:      300.0  # max ray distance in metres
# threshold:       None   # integer: 0 = strict (no violations), 1 = allow 1, etc.
# min_altitude:    5.0    # ignore sun below this elevation (degrees)
# apply_smoothing: false  # true = SDF smooth + marching cubes
# device:          'auto' # 'auto', 'cpu', or 'cuda'
# See REFERENCE_all_options.yaml for the complete parameter list.
```

- [ ] **Step 5: Delete duplicate `configs/config_timebased.yaml`**

```bash
git rm configs/config_timebased.yaml
```

This file is an older duplicate of `config_time_based.yaml` with less content.

- [ ] **Step 6: Commit**

```
git add configs/
git commit -m "fix(config): fix stale EPW/period comments, add defaults blocks, remove duplicate"
```

---

## Task 4: Fix stale docstrings in Python source

Four source files contain references to removed features (Otsu, evaluation) or false claims (sum=1).

**Files:**
- Modify: `src/urbansolarcarver/carver_cli.py:6`
- Modify: `src/urbansolarcarver/carving.py:337`
- Modify: `src/urbansolarcarver/sky_patches.py:312-313`
- Modify: `src/urbansolarcarver/api_core/preprocessing.py:59,161,171`

- [ ] **Step 1: Fix `carver_cli.py` module docstring**

At line 6, change:

```python
An optional ``evaluation`` command adds post-carving performance analysis.
```

to:

```python
Performance evaluation is out of scope; use Ladybug/Honeybee/Radiance on the
exported mesh.
```

- [ ] **Step 2: Fix `carving.py` docstring**

At line 337, change:

```python
      5. Select a threshold via fixed value, Otsu, head/tail breaks or retain fraction
```

to:

```python
      5. Select a threshold via fixed value, head/tail breaks, or carve_fraction
```

- [ ] **Step 3: Fix `sky_patches.py` docstring**

At lines 312-313, change:

```python
        Weights are non-negative and, as long as the selected sky
        model is energy-conserving, Σwᵢ = 1.
```

to:

```python
        Weights are non-negative.  Only ``radiative_cooling`` normalises
        to Σwᵢ = 1.  Other modes preserve the physical scale returned
        by Ladybug (Wh/m² for irradiance/benefit) or the CIE luminance
        distribution (daylight).  Threshold methods (carve_fraction,
        headtail) are scale-invariant, so the difference does not affect
        carving results.
```

- [ ] **Step 4: Fix `preprocessing.py` docstrings**

At line 59, change:

```python
       * sky-patch modes (``sky-patch``, ``cumulative-sky``, etc.): rays are
```

to:

```python
       * sky-patch modes (``irradiance``, ``benefit``, ``daylight``,
         ``radiative_cooling``): rays are
```

At line 161, change:

```python
    # Record test surface path so evaluation can re-discretize at a different step.
```

to:

```python
    # Record test surface path for downstream re-discretization if needed.
```

At line 171, change:

```python
    # Persist analysis mesh for downstream evaluation and visualization
```

to:

```python
    # Persist analysis mesh for downstream visualization and diagnostics
```

- [ ] **Step 5: Commit**

```
git add src/urbansolarcarver/carver_cli.py src/urbansolarcarver/carving.py src/urbansolarcarver/sky_patches.py src/urbansolarcarver/api_core/preprocessing.py
git commit -m "docs: remove stale Otsu/evaluation refs, fix weight-sum docstring"
```

---

## Task 5: Fix daylight mode period handling

**The bug:** `preprocessing.py:120` computes `_needs_period = mode not in ("tilted_plane",)`, so daylight mode tries to call `sample_period(conf)`. But the schema correctly does NOT require period fields for daylight (CIE overcast is time-invariant). If a user runs daylight mode without period fields, `sample_period()` is called with `start_month=None`, which will crash.

**The fix:** Add `"daylight"` to the exclusion set. Daylight's weight computation (`sky_patches.py:349-353`) never uses `hoys`: it returns CIE weights purely from patch geometry. The `hoys` variable is passed through `carve_with_sky_patch_rays` → `get_weights` → `compute_EPW_based_weights`, but the daylight branch returns before touching it. So `hoys=[]` is safe.

**Files:**
- Modify: `src/urbansolarcarver/api_core/preprocessing.py:118-124`
- Test: `tests/test_schemas.py`

- [ ] **Step 1: Write the failing test**

In `tests/test_schemas.py`, add to the existing `TestDaylightMode` class:

```python
    def test_daylight_with_period_accepted(self):
        """Daylight with explicit period should also work."""
        cfg = _make_config(
            mode="daylight",
            tilted_plane_angle_deg=None,
            start_month=1, start_day=1, start_hour=8,
            end_month=12, end_day=31, end_hour=17,
        )
        assert cfg.mode == "daylight"
```

This is a sanity check that the schema accepts daylight with or without period. It should already pass.

- [ ] **Step 2: Fix the period logic in `preprocessing.py`**

At lines 118-124, change:

```python
    # Only build analysis period for modes that need it.
    # tilted_plane is purely geometric: no EPW, no sun positions.
    _needs_period = mode not in ("tilted_plane",)
    if _needs_period:
        datetimes, hoys = sample_period(conf)
    else:
        datetimes, hoys = [], []
```

to:

```python
    # Modes that skip analysis period entirely:
    # - tilted_plane: purely geometric, no sun/sky.
    # - daylight: CIE overcast sky is time-invariant; hoys are never used
    #   by the weight computation (sky_patches.py daylight branch).
    _needs_period = mode not in ("tilted_plane", "daylight")
    if _needs_period:
        datetimes, hoys = sample_period(conf)
    else:
        datetimes, hoys = [], []
```

- [ ] **Step 3: Run the full test suite**

Run: `pytest tests/ -v --tb=short`
Expected: ALL PASS (124+ passed, ~6 skipped).

- [ ] **Step 4: Commit**

```
git add src/urbansolarcarver/api_core/preprocessing.py tests/test_schemas.py
git commit -m "fix: daylight mode no longer requires analysis period fields"
```

---

## Task 6: Improve violation_count and thresholding documentation

`violation_count` is an important feature (integer threshold for time-based/tilted_plane modes) that gets buried. The user explicitly noted they forgot it existed. Also remove the last `otsu` reference in modes.md.

**Files:**
- Modify: `docs/modes.md`

- [ ] **Step 1: Insert a thresholding guide section**

After the mode table (after line 14, before `## time-based`), insert:

```markdown

## Thresholding strategies

USC supports three threshold strategies. The right choice depends on the mode.

### For weighted modes (irradiance, benefit, daylight, radiative_cooling)

Scores are continuous **weighted sums**: the total sky-patch weight obstructed by each voxel. Their absolute magnitude depends on the mode, weather file, and number of sample points, so they are not directly interpretable as physical quantities.

| Strategy | How it works | When to use |
|----------|---|---|
| `carve_fraction` (default) | Ranks voxels by score, removes top-scorers until the target fraction of total obstruction weight is eliminated. `0.7` = aggressive (tall, slim volumes). `0.3` = conservative (bulky volumes). | **Recommended.** Intuitive slider; no knowledge of score distribution needed. |
| `headtail` | Jiang (2013) head/tail breaks: iteratively splits the distribution at the mean. Good for heavy-tailed distributions. | When you want an automatic, data-driven split without choosing a fraction. |
| Numeric value | Manual cutoff on raw scores. Voxels scoring above this value are carved. | **Advanced.** Only useful after inspecting the score histogram in `diagnostics/`. The value is mode- and dataset-specific; not portable across runs. |

### For violation-count modes (time-based, tilted_plane)

Scores are **integer violation counts**: the number of time steps (sun hours) or plane intersections that each voxel causes. These have direct physical meaning:

| Threshold value | Meaning |
|---|---|
| `0` (default) | **Strict**: remove any voxel that causes even one violation |
| `1` | Allow one hour of shadow (or one plane intersection) |
| `2` | Allow two violations, etc. |
| `None` | Uses the default (0 = strict) |

String strategies (`carve_fraction`, `headtail`) are **not applicable** to integer counts and will raise an error for `tilted_plane`. For `time-based`, the threshold is applied as a simple integer cutoff.

!!! tip "Violation counts have a direct meaning"
    Unlike weighted modes, violation-count thresholds have a clear physical interpretation. `threshold: 0` means "zero shadow tolerance during the analysis period." `threshold: 2` means "allow up to 2 hours of shadow." This makes time-based mode the most transparent and controllable carving strategy.

```

- [ ] **Step 2: Replace the stale threshold paragraph in the time-based section**

In the `## time-based` section, replace:

```markdown
**Threshold semantics**: scores are **integer violation counts** (number of time steps in which the voxel casts a shadow). Use a non-negative integer: `threshold: 0` (default) removes any voxel that shadows even once; `threshold: 1` tolerates one time step of shadow; and so on. Statistical methods (`carve_fraction`, `otsu`, `headtail`) are not applicable to integer counts.
```

with:

```markdown
**Threshold semantics**: see [violation-count thresholds](#for-violation-count-modes-time-based-tilted_plane) above.
```

- [ ] **Step 3: Commit**

```
git add docs/modes.md
git commit -m "docs: add thresholding guide, document violation_count feature prominently"
```

---

## Task 7: Fix Grasshopper component documentation

Three GH components incorrectly describe which modes require EPW and/or analysis period.

**Files:**
- Modify: `grasshopper/components/USC_AnalysisPeriod.py:1-4,24`
- Modify: `grasshopper/components/USC_Config.py:61`
- Modify: `grasshopper/components/USC_RadCooling.py:1-18`

- [ ] **Step 1: Fix `USC_AnalysisPeriod.py`**

At lines 1-4, change:

```python
"""USC Analysis Period: define the time window for sun/sky analysis.

Required for: time-based, irradiance, benefit, daylight modes.
Not used by: tilted_plane, radiative_cooling.
```

to:

```python
"""USC Analysis Period: define the time window for sun/sky analysis.

Required for: time-based, irradiance, benefit, radiative_cooling modes.
Optional for: daylight (CIE overcast is time-invariant; defaults to full year).
Not used by: tilted_plane.
```

At line 24 (the GH description string), change:

```python
    ghenv.Component.Description = "Defines the time window for solar analysis. Specify start/end month, day, and hour. Used by time-based, irradiance, benefit, and daylight modes. Not needed for tilted_plane."
```

to:

```python
    ghenv.Component.Description = "Defines the time window for solar analysis. Required for time-based, irradiance, benefit, and radiative_cooling modes. Optional for daylight (time-invariant). Not needed for tilted_plane."
```

- [ ] **Step 2: Fix `USC_Config.py`**

At line 61, change:

```python
    ii[2].Name, ii[2].Description = "epw_path", "Full path to an EnergyPlus Weather (.epw) file for your location. Required for all modes except 'tilted_plane' and 'daylight' (which uses CIE overcast sky, geometry-only). Download from climate.onebuilding.org or ladybug.tools."
```

to:

```python
    ii[2].Name, ii[2].Description = "epw_path", "Full path to an EnergyPlus Weather (.epw) file for your location. Required for all modes except 'tilted_plane' and 'daylight'. Download from climate.onebuilding.org or ladybug.tools."
```

- [ ] **Step 3: Fix `USC_RadCooling.py`**

At lines 1-18, change the module docstring from:

```python
"""USC Radiative Cooling: parameters for experimental radiative cooling mode.

[EXPERIMENTAL] This mode estimates the directional cooling potential
of the night sky using Martin-Berdahl (1984) emissivity and Bliss (1961)
angular attenuation models.

Inputs
------
```

to:

```python
"""USC Radiative Cooling: parameters for experimental radiative cooling mode.

[EXPERIMENTAL] This mode estimates the directional cooling potential
of the night sky using Martin-Berdahl (1984) emissivity and Bliss (1961)
angular attenuation models.

Also requires: USC_AnalysisPeriod (to define the nighttime hours)
               and an EPW file (connected via USC_Config).

Inputs
------
```

- [ ] **Step 4: Commit**

```
git add grasshopper/components/USC_AnalysisPeriod.py grasshopper/components/USC_Config.py grasshopper/components/USC_RadCooling.py
git commit -m "docs(grasshopper): fix radiative_cooling EPW/period requirement docs"
```

---

## Task 8: Run full test suite and final verification

- [ ] **Step 1: Run entire test suite**

Run: `pytest tests/ -v --tb=short`
Expected: ALL PASS (124+ passed, ~6 skipped). The new tests from Task 1 and Task 5 should be included.

- [ ] **Step 2: Spot-check `extra='forbid'` works end-to-end**

Run:
```bash
python -c "
from urbansolarcarver.pydantic_schemas import UserConfig
try:
    UserConfig(max_volume_path='a.ply', test_surface_path='b.ply',
               out_dir='out', mode='tilted_plane',
               tilted_plane_angle_deg=45.0, voxel_size=2, grid_step=2,
               score_scale='linear')
    print('ERROR: should have rejected score_scale')
except Exception as e:
    print(f'OK: extra field rejected')
"
```
Expected: `OK: extra field rejected`

- [ ] **Step 3: Verify no stale references remain**

Run:
```bash
grep -rn "otsu\|score_scale\|evaluation command\|cumulative-sky\|sky-patch modes" src/ docs/modes.md configs/ --include="*.py" --include="*.yaml" --include="*.md" | grep -v "test_otsu_rejected\|__pycache__"
```
Expected: No matches (the test that validates otsu rejection is excluded from the grep).

- [ ] **Step 4: Commit (if any stragglers found)**

Fix any remaining references found in Step 3, then commit.
