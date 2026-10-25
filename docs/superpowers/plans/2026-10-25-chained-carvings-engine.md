# Chained carvings, phase 1 (engine) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The engine (Python API, CLI, daemon) can run an ordered list of criteria on one voxel grid: each criterion scores the drawn maximum volume with its own rays, its thresholding decides only among the voxels the previous criterion kept, and exporting and massing are built from the last criterion.

**Architecture:** Each criterion's preprocessing is an ordinary preprocessing run on the drawn maximum volume (so the skin rule reads the chain root's solid and massing measures against the drawn volume, with no change to either). Thresholding gains an optional `after` input, the previous criterion's thresholding result: its occupancy becomes `voxel_grid & previous mask`, and every statistic, smoothing and column rule runs over that. A chain config (`criteria:` list) and `run_chain` run the criteria in order into `out_dir/criteria/<id>/`, then exporting and massing from the last.

**Tech Stack:** Python 3.10, NumPy, pydantic v2, Typer CLI, pytest (CPU Warp backend in tests).

**Spec:** `docs/superpowers/specs/2026-10-25-chained-carvings-design.md` (sections 5, 6, 10, 11, 12 step 1).

## Global Constraints

- The thresholding input is named `after` in the API, CLI (`--after`), and engine requests; `start_from` is already taken by `run_pipeline` and `RunRequest` (spec 6.1 leaves the name to the builder).
- A config without `criteria:` behaves exactly as today; every existing test passes unchanged.
- No change to scoring, the skin rule, massing or exporting rules (spec section 10).
- Shared settings are set once at the top level; a criterion may not set them, and the top level may not set criterion settings when `criteria:` is present (spec 6.5).
- Folder layout of a chain run: `<out>/criteria/<id>/preprocessing`, `<out>/criteria/<id>/thresholding`, `<out>/criteria/chain.json`, `<out>/exporting`, `<out>/massing` (spec 6.5, 8).
- Stage contract unchanged: manifests written last, `StageChainError` names the stage or folder to re-run (`docs/superpowers/specs/2026-10-16-stage-contract-design.md`).
- Tests: a test over about 1 s goes under `@pytest.mark.slow` (CLAUDE.md test tiers).
- Writing style in messages and docs: plain words, no em dashes.

## Review Focus

- A criterion left with no voxels to decide about (the previous one carved everything): thresholding must not crash; it reports `nothing_left_to_carve` and writes an all-False mask. Pinned in Task 1.
- `after` naming a thresholding run of another grid (another voxel size, origin or max volume): refused with `StageChainError` naming what differs. Pinned in Task 1.
- The previous criterion re-run after a later one: exporting and massing of the chain refuse with `StageChainError` naming the stale criterion folder. Pinned in Task 1.
- Relative paths inside a criterion (`test_surface_path`) resolve against the YAML file's folder, like top-level paths. Pinned in Task 2.
- A violation-count criterion (time-based, tilted_plane) after a weighted one: its cutoff and `carve_above` act only on the remaining voxels. Pinned in Task 3.

---

## File structure

- Modify `src/urbansolarcarver/pydantic_schemas.py`: `ThresholdingManifest` gains `after_manifest`, `after_run_id`.
- Modify `src/urbansolarcarver/api_core/thresholding.py`: `after` input, restricted occupancy, grid check, diagnostics.
- Modify `src/urbansolarcarver/api_core/_stage_io.py`: `load_upstream` also checks the `after` link of a thresholding manifest.
- Create `src/urbansolarcarver/chain_config.py`: chain config model and `load_chain`.
- Modify `src/urbansolarcarver/load_config.py`: `load_config` refuses a chain file with a pointer to `load_chain` and `usc run`.
- Create `src/urbansolarcarver/api_core/chain.py`: `run_chain`, `ChainResult`, `chain.json`.
- Modify `src/urbansolarcarver/api.py`, `src/urbansolarcarver/__init__.py`: export `run_chain`, `ChainResult`, `load_chain`.
- Modify `src/urbansolarcarver/api_core/_reporting.py` (and the report generator it calls): a "Criteria" section when `criteria/chain.json` exists.
- Modify `src/urbansolarcarver/carver_cli.py`, `src/urbansolarcarver/engine_requests.py`: chain files in `run` and `validate`, `--after` / `after`.
- Docs: `docs/criteria.md` (new, in the mkdocs nav), `docs/getting-started/configuration.md`, `docs/project-map.md`, `CHANGELOG.md`.
- Tests: `tests/_chain_scene.py` (shared scene helper), `tests/test_chained_thresholding.py`, `tests/test_chain_config.py`, `tests/test_run_chain.py`, additions to `tests/test_cli.py`.

---

### Task 1: Thresholding after a previous criterion

**Files:**
- Create: `tests/_chain_scene.py`, `tests/test_chained_thresholding.py`
- Modify: `src/urbansolarcarver/pydantic_schemas.py` (`ThresholdingManifest`, near line 832), `src/urbansolarcarver/api_core/thresholding.py:136-470`, `src/urbansolarcarver/api_core/_stage_io.py:115-150`

**Interfaces:**
- Produces: `thresholding(volume, cfg, out_dir, after=None) -> ThresholdingResult`, where `after` is a `ThresholdingResult`, or a path to a thresholding folder or `manifest.json`, or None.
- Produces: `ThresholdingManifest.after_manifest: Optional[str] = None` (path relative to the manifest folder) and `after_run_id: Optional[str] = None`.
- Produces: diagnostic keys `after_run_id` (str or None) and `voxels_at_start` (int, the occupied voxels the criterion decides about).
- Produces in `tests/_chain_scene.py`: `chain_scene(tmp_path) -> ChainScene` with fields `volume`, `south`, `east` (paths: a 30 x 12 x 20 m box at the origin, a south facade 8 m away and an east facade 8 m away, both 10 m high, PLY files) and the method `config(folder, **values) -> user_config` building a daylight config on that scene with `voxel_size=1.0, grid_step=1.0, ray_length=80.0, device="cpu", min_voxels=1, min_face_count=0` (as `tests/test_massing_stage.py::_run_upstream` does).

- [ ] **Step 1: Write the failing tests** in `tests/test_chained_thresholding.py`:

```python
def test_a_criterion_after_another_equals_thresholding_on_its_kept_voxels(tmp_path):
    # Reference: the same thresholding with the preprocessing occupancy replaced by criterion 1's mask.
    s = chain_scene(tmp_path)
    c1 = s.config(tmp_path / "c1", test_surface_path=s.south, carve_fraction=0.6)
    c2 = s.config(tmp_path / "c2", test_surface_path=s.east, carve_fraction=0.5)
    pre1 = preprocessing(c1, tmp_path / "c1/pre"); thr1 = thresholding(pre1, c1, tmp_path / "c1/thr")
    pre2 = preprocessing(c2, tmp_path / "c2/pre"); thr2 = thresholding(pre2, c2, tmp_path / "c2/thr", after=thr1)
    ref_pre = copy_preprocessing_with_occupancy(pre2, np.load(thr1.mask_path), tmp_path / "ref/pre")
    ref = thresholding(ref_pre, c2, tmp_path / "ref/thr")
    assert np.array_equal(np.load(thr2.mask_path), np.load(ref.mask_path))
    assert not (np.load(thr2.mask_path) & ~np.load(thr1.mask_path)).any()
    manifest = json.loads((thr2.out_dir / "manifest.json").read_text())
    assert manifest["after_run_id"] == thr1.run_id and manifest["after_manifest"].endswith("manifest.json")
    diag = json.loads((thr2.out_dir / "diagnostics/diagnostic.json").read_text())
    assert diag["voxels_at_start"] == int(np.load(thr1.mask_path).sum()) == diag["voxels_occupied"]

def test_after_a_run_on_another_grid_is_refused(tmp_path):     # voxel_size 1.0 vs 2.0
    ...
    with pytest.raises(StageChainError, match="voxel size"):
        thresholding(pre2, c2, out, after=thr1_other_grid)

def test_nothing_left_to_carve_gives_an_empty_mask_and_an_issue(tmp_path):
    # criterion 1 with threshold cutoff below every score carves everything
    ...
    with pytest.warns(UserWarning, match="nothing_left_to_carve|nothing left"):
        thr2 = thresholding(pre2, c2, out, after=thr1_all_carved)
    assert not np.load(thr2.mask_path).any()

def test_a_stale_previous_criterion_refuses_the_chain_downstream(tmp_path):
    # re-run criterion 1's thresholding after criterion 2's: exporting from criterion 2 must refuse
    ...
    with pytest.raises(StageChainError, match=str(thr1_folder)):
        exporting(thr2, c2, tmp_path / "exp")
```

`copy_preprocessing_with_occupancy(pre, occupancy, out)` is a helper in `tests/_chain_scene.py`: copy the preprocessing folder to `out` and overwrite `voxel_grid.npy` with `occupancy & original` (same dtype as the original), keeping `manifest.json` (same run id is fine for a reference).

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_chained_thresholding.py -v`
Expected: FAIL with `TypeError: thresholding() got an unexpected keyword argument 'after'`.

- [ ] **Step 3: Implement**

- `ThresholdingManifest`: add `after_manifest: Optional[str] = None` and `after_run_id: Optional[str] = None` with a comment ("the previous criterion's thresholding manifest and run id when this run decided only among the voxels it kept; None for a first or only criterion").
- `thresholding(volume, cfg, out_dir, after=None)`: load `after` with `load_upstream(after, "thresholding")` when given; pass it to `_run_thresholding` as `previous: LoadedManifest | None`. Update both overloads and the docstring (a paragraph on `after`, the sequential base, and the new manifest fields).
- In `_run_thresholding`, right after `occ = load_occupancy(pre)`: with `previous`, call a new `_check_same_grid(pre, previous_pre)` (previous_pre = `load_upstream(previous.resolve(previous.manifest.upstream_manifest), "preprocessing")`) that compares `shape`, `origin` (to 1e-9), `voxel_size`, and the occupancy arrays, raising `StageChainError` with "voxel size", "grid origin", "grid shape" or "maximum volume" in the message and the hint "every criterion of a chain must share the max volume, context, terrain, voxel size and margin". Then `occ = occ & np.load(previous mask) .astype(bool)`. Everything below already uses `occ`, so smoothing, `carve_fraction`, `carve_above_scores` and `limit_column_slope` act on the remaining voxels.
- When `occ` has no voxel: `report_issue("nothing_left_to_carve", "thresholding: the previous criterion kept no voxel, so this criterion has nothing to decide; the mask is empty")`, write an all-False mask, the diagnostics with zeros and the manifest, and return; do not call `_resolve_threshold` on an empty array.
- Diagnostics: add `after_run_id` and `voxels_at_start` (= `int(occ.sum())`). Manifest: fill `after_manifest` (via `stored_path`) and `after_run_id`.
- `load_upstream` in `_stage_io.py`: for a thresholding manifest whose `after_manifest` is set, load it as `"thresholding"` and raise `StageChainError` when its `run_id` differs from `after_run_id`: "The previous criterion's thresholding at <folder> was re-run after this one. Re-run thresholding of the criteria after it." The recursive load also checks that criterion's own links.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_chained_thresholding.py tests/test_pipeline.py tests/test_stage_chain.py -m "not slow" -v`
Expected: PASS (mark any test of this file over about 1 s as slow, then run it with `-m slow` too).

- [ ] **Step 5: Commit**

```bash
git add tests/_chain_scene.py tests/test_chained_thresholding.py src/urbansolarcarver/pydantic_schemas.py src/urbansolarcarver/api_core/thresholding.py src/urbansolarcarver/api_core/_stage_io.py
git commit -m "feat(thresholding): decide after a previous criterion (after=), only among the voxels it kept"
```

---

### Task 2: Chain config (`criteria:`)

**Files:**
- Create: `src/urbansolarcarver/chain_config.py`, `tests/test_chain_config.py`
- Modify: `src/urbansolarcarver/load_config.py:191-245`, `src/urbansolarcarver/api.py`, `src/urbansolarcarver/__init__.py`

**Interfaces:**
- Produces: `CRITERION_KEYS: frozenset[str]`: `{"name", "id", "mode", "test_surface_path"} | set(ThresholdingSettings.model_fields) | _MODE_SPECIFIC_FIELDS (from pydantic_schemas, minus "epw_path") | {"edge_taper"}`. Everything else is shared and set at the top level.
- Produces: `@dataclass(frozen=True) class Criterion: id: str; name: str; config: user_config`.
- Produces: `@dataclass(frozen=True) class ChainConfig: criteria: tuple[Criterion, ...]; shared: user_config` (`shared` = the last criterion's config; exporting and massing read their settings from it, which are all shared keys).
- Produces: `load_chain(path: str, overrides=None) -> ChainConfig` and `is_chain_file(path: str) -> bool` (top-level YAML mapping with a `criteria` key).
- `load_config(path)` on a chain file raises `ConfigError`: "<path> lists criteria; load it with load_chain() or run it with `usc run`".

- [ ] **Step 1: Write the failing tests** in `tests/test_chain_config.py`:

```python
def test_each_criterion_gets_the_shared_settings_and_its_own(tmp_path):
    path = write_yaml(tmp_path, {"max_volume_path": "vol.ply", "voxel_size": 2.0, "out_dir": "run",
        "criteria": [{"name": "Daylight on windows", "mode": "daylight", "test_surface_path": "w.ply", "carve_fraction": 0.7},
                     {"mode": "tilted_plane", "test_surface_path": "y.ply", "tilted_plane_angle_deg": 30}]})
    chain = load_chain(str(path))
    assert [c.id for c in chain.criteria] == ["1", "2"]
    assert [c.name for c in chain.criteria] == ["Daylight on windows", "tilted_plane"]
    assert all(c.config.voxel_size == 2.0 for c in chain.criteria)
    assert chain.criteria[0].config.carve_fraction == 0.7
    assert chain.criteria[1].config.test_surface_path == str((tmp_path / "y.ply").resolve())  # relative to the YAML

def test_a_shared_setting_inside_a_criterion_is_refused(tmp_path):      # voxel_size in a criterion
    with pytest.raises(ConfigError, match="voxel_size.*shared"): load_chain(...)

def test_a_criterion_setting_at_the_top_level_is_refused(tmp_path):     # carve_fraction next to criteria:
    with pytest.raises(ConfigError, match="carve_fraction.*criteria"): load_chain(...)

def test_the_weather_file_reaches_only_the_criteria_that_read_it(tmp_path):
    # top-level epw_path, one benefit and one daylight criterion: no settings_unused_by_mode issue, daylight config has epw_path None
    ...

def test_a_criterion_error_names_the_criterion(tmp_path):              # benefit criterion without a period
    with pytest.raises(ConfigError, match="criterion 2"): load_chain(...)

def test_ids_must_be_unique_and_safe_folder_names(tmp_path):           # id "a/b" or two ids "x"
    with pytest.raises(ConfigError, match="id"): load_chain(...)

def test_load_config_points_a_chain_file_to_load_chain(tmp_path):
    with pytest.raises(ConfigError, match="load_chain"): load_config(str(chain_yaml))
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_chain_config.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'urbansolarcarver.chain_config'`.

- [ ] **Step 3: Implement `chain_config.py`**

Read the YAML as `load_config` does (same error handling), expand `analysis_period` in the top level and in each criterion, resolve `PATH_FIELDS` in both against the YAML folder, apply `overrides` to the top level (shared keys only; a criterion key in overrides is a `ConfigError`), check the two key rules, then for each criterion build `{**shared, **criterion minus name/id}`, drop `epw_path` when `MODES[mode].needs_epw` is false, and validate with `build_config`, re-raising a `ConfigError` whose message starts "criterion <id> (<name>): ". Default `id` = position from 1 as a string; default `name` = the mode. An `id` must match `^[A-Za-z0-9_-]{1,40}$`. Export `load_chain`, `ChainConfig`, `Criterion` from `api.py` and `__init__.py`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_chain_config.py tests/test_schemas.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/urbansolarcarver/chain_config.py src/urbansolarcarver/load_config.py src/urbansolarcarver/api.py src/urbansolarcarver/__init__.py tests/test_chain_config.py
git commit -m "feat(config): criteria list for chained carvings (load_chain)"
```

---

### Task 3: `run_chain` and the run report

**Files:**
- Create: `src/urbansolarcarver/api_core/chain.py`, `tests/test_run_chain.py`
- Modify: `src/urbansolarcarver/api.py`, `src/urbansolarcarver/__init__.py`, `src/urbansolarcarver/api_core/_reporting.py` and the report generator it calls (`generate_run_report`)

**Interfaces:**
- Consumes: `thresholding(..., after=...)` (Task 1), `load_chain`, `ChainConfig`, `Criterion` (Task 2).
- Produces: `run_chain(chain: ChainConfig | str | Path, out_dir: str | Path | None = None, produce: Iterable[str] = ("exporting",), start_from: str = "preprocessing", context: RunContext | None = None) -> ChainResult`. `out_dir` defaults to the shared config's `out_dir`. `start_from` as in `run_pipeline`: "preprocessing" traces every criterion; "thresholding" reuses every criterion's existing preprocessing folder and re-thresholds the chain; "exporting"/"massing" reuse the last criterion's thresholding.
- Produces: `@dataclass(frozen=True) class ChainResult: criteria: tuple[PipelineResult, ...]; exporting: ExportingResult | None; massing: MassingResult | None; issues: tuple[Issue, ...]`.
- Produces: `<out>/criteria/chain.json`: `{"criteria": [{"id", "name", "mode", "thresholding_run_id"}]}`, written after the last criterion's thresholding.
- Produces in `tests/_chain_scene.py`: the method `ChainScene.chain_config(folder, criteria: list[dict]) -> ChainConfig` (writes a chain YAML on the scene and returns `load_chain(...)`), and criterion dict helpers `daylight_on_south(carve_fraction)`, `daylight_on_east(carve_fraction)`, `tilted_plane_on_east(angle_deg)`.

- [ ] **Step 1: Write the failing tests** in `tests/test_run_chain.py` (mark the module `pytest.mark.slow`: each runs preprocessing several times):

```python
def test_a_chain_of_two_writes_one_folder_per_criterion_and_builds_from_the_last(tmp_path):
    chain = chain_scene(tmp_path).chain_config(tmp_path / "cfg", [daylight_on_south(0.6), daylight_on_east(0.5)])
    result = run_chain(chain, tmp_path / "run", produce=("exporting", "massing"))
    for cid in ("1", "2"):
        assert (tmp_path / f"run/criteria/{cid}/preprocessing/manifest.json").is_file()
        assert (tmp_path / f"run/criteria/{cid}/thresholding/manifest.json").is_file()
    assert result.exporting.upstream_run_id == result.criteria[1].thresholding.run_id
    assert json.loads((tmp_path / "run/criteria/chain.json").read_text())["criteria"][1]["id"] == "2"
    assert "## Criteria" in (tmp_path / "run/run_report.md").read_text()

def test_massing_of_a_chain_follows_the_drawn_footprint(tmp_path):
    # the max volume is a box turned 20 degrees: the ground floor plate has the box's 4 corners, not voxel steps
    ...
    assert len(ground_plate.exterior.coords) <= 6

def test_re_thresholding_the_chain_reuses_the_rays(tmp_path):
    run_chain(chain, out)
    scores_before = (out / "criteria/2/preprocessing/scores.npy").stat().st_mtime_ns
    run_chain(chain_with_criterion_1_at_0_8, out, start_from="thresholding")
    assert (out / "criteria/2/preprocessing/scores.npy").stat().st_mtime_ns == scores_before

def test_a_tilted_plane_criterion_after_daylight_acts_only_on_what_is_left(tmp_path):
    result = run_chain(chain_daylight_then_tilted_plane, out, produce=("thresholding",))
    m1, m2 = (np.load(r.thresholding.mask_path) for r in result.criteria)
    assert not (m2 & ~m1).any() and m2.sum() < m1.sum()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_run_chain.py -v -m slow`
Expected: FAIL with `ImportError: cannot import name 'run_chain'`.

- [ ] **Step 3: Implement `api_core/chain.py`**

Loop over the criteria in one `run_context` (as `run_pipeline` does): for each, run preprocessing into `criteria/<id>/preprocessing` (skipped when `start_from` is later; the folder is then read) and thresholding into `criteria/<id>/thresholding` with `after=` the previous criterion's result; wrap each criterion in `stage_context(f"criterion {id}")` so progress and issues name it. Then exporting and/or massing with the shared config from the last thresholding into `<out>/exporting` and `<out>/massing`. Write `chain.json` before exporting. Report: when `criteria/chain.json` exists next to the report, `generate_run_report` adds a "## Criteria" section with one row per criterion (name, mode, threshold method and value, voxels at start, voxels kept), read from each criterion's thresholding diagnostics; the existing preprocessing and thresholding sections describe the last criterion. Export `run_chain`, `ChainResult` from `api.py` and `__init__.py`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_run_chain.py tests/test_pipeline.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/urbansolarcarver/api_core/chain.py src/urbansolarcarver/api.py src/urbansolarcarver/__init__.py src/urbansolarcarver/api_core/_reporting.py tests/test_run_chain.py tests/_chain_scene.py
git commit -m "feat(api): run_chain runs criteria in sequence and builds from the last"
```

---

### Task 4: CLI and daemon

**Files:**
- Modify: `src/urbansolarcarver/carver_cli.py` (`run`, `cmd_thresholding`, `validate`), `src/urbansolarcarver/engine_requests.py` (`StageRequest`, the run handler)
- Test: `tests/test_cli.py`, `tests/test_engine_requests.py`

**Interfaces:**
- Consumes: `is_chain_file`, `load_chain` (Task 2), `run_chain` (Task 3), `thresholding(..., after=)` (Task 1).
- Produces: `usc run -c chain.yaml [--produce ...] [--start-from ...]` runs `run_chain`; `usc thresholding -c cfg.yaml -f <pre> --after <thresholding folder or manifest>`; `usc validate -c chain.yaml` validates every criterion and prints one line per criterion.
- Produces: `StageRequest.after: Optional[str] = None` (key `after`), passed to `api.thresholding`; a `RunRequest` whose `config` is a chain file runs `run_chain` and replies with the last criterion's paths.

- [ ] **Step 1: Write the failing tests**: in `tests/test_cli.py`, `test_run_on_a_chain_file_runs_every_criterion` (CliRunner, chain YAML from `tests/_chain_scene.py`, asserts both `criteria/<id>/thresholding/manifest.json` exist and exit code 0; slow), `test_thresholding_after_flag_writes_the_after_link` (runs `usc thresholding --after`; manifest has `after_run_id`), `test_validate_lists_the_criteria` (output contains both criterion names); in `tests/test_engine_requests.py`, `test_a_thresholding_stage_request_passes_after` (monkeypatched `api.thresholding` receives `after`).

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_cli.py tests/test_engine_requests.py -k "chain or after or criteria" -v`
Expected: FAIL (unknown option `--after`; chain file refused by `load_config`).

- [ ] **Step 3: Implement**: branch on `is_chain_file(config)` at the top of `run` and `validate`; add `--after` to `cmd_thresholding` and to the daemon payload; add `after` to `StageRequest` and the thresholding branch of `_run_stage`; in the run handler, a chain config goes to `api.run_chain`. `--override` on a chain file applies to shared settings only (Task 2 refuses criterion keys).

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_cli.py tests/test_engine_requests.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/urbansolarcarver/carver_cli.py src/urbansolarcarver/engine_requests.py tests/test_cli.py tests/test_engine_requests.py
git commit -m "feat(cli): run chain files; thresholding --after"
```

---

### Task 5: Oracle cases for chains

**Files:**
- Modify: `tests/montecarlo.py`, `tests/test_montecarlo.py`

**Interfaces:**
- Consumes: `run_chain` (Task 3), `copy_preprocessing_with_occupancy` (Task 1), the existing per-case checks of `montecarlo.run_case` and `oracle.score_agreement`.
- Produces: `montecarlo.run_chain_case(seed: int, epw: str, device: str, tmp: Path, modes: tuple[str, str]) -> dict` with the same record shape as `run_case` (`failed`, `metrics`, `error`, `traceback`).

- [ ] **Step 1: Write the failing test** in `tests/test_montecarlo.py`, marked `slow` and `sweep` like the others:

```python
CHAIN_CASES = [(1042, ("daylight", "benefit")), (1036, ("time-based", "daylight"))]   # spec section 11

@pytest.mark.parametrize("seed, modes", CHAIN_CASES)
def test_montecarlo_chain_case(tmp_path, epw, seed, modes):
    rec = montecarlo.run_chain_case(seed, epw, "cpu", tmp_path, modes)
    assert not rec["failed"], (rec["failed"], rec.get("error"), rec.get("traceback"), rec["metrics"])
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python -m pytest tests/test_montecarlo.py -k chain -v`
Expected: FAIL with `AttributeError: module 'montecarlo' has no attribute 'run_chain_case'`.

- [ ] **Step 3: Implement `run_chain_case`**: build the seed's random scene as `run_case` does, with two criteria on it (each its own random test surfaces and threshold, in the given modes); run `run_chain`; check criterion 1 with `run_case`'s existing checks; for criterion 2 check `oracle.score_agreement` on its preprocessing, that its mask is inside criterion 1's, and that its mask equals thresholding its preprocessing with the occupancy replaced by criterion 1's mask (`copy_preprocessing_with_occupancy`). Each failed check is a `failed` entry naming the criterion.

- [ ] **Step 4: Run it to verify it passes**

Run: `python -m pytest tests/test_montecarlo.py -k chain -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tests/montecarlo.py tests/test_montecarlo.py
git commit -m "test(montecarlo): chained criteria cases against the oracle"
```

---

### Task 6: Documentation and the merge tier

**Files:**
- Create: `docs/criteria.md` (add to `mkdocs.yml` nav next to the modes page)
- Modify: `docs/getting-started/configuration.md` (a `criteria` row and the shared/criterion key rule), `docs/project-map.md` (`chain_config.py`, `api_core/chain.py`, the `after` input of thresholding), `CHANGELOG.md` (`### Added (chained carvings, engine)`)

- [ ] **Step 1: Write `docs/criteria.md`**: what a chain is (sequential base: each criterion's carve amount refers to what the previous one kept), the YAML example from spec 6.5, the folder layout, `usc run`, `usc thresholding --after`, `run_chain`, which settings are shared and which belong to a criterion, why re-thresholding is cheap (scores do not depend on other criteria), and that the browser app and Grasshopper follow in later phases (carve further remains in the app until then).

- [ ] **Step 2: Build the docs strictly**

Run: `mkdocs build --strict -d <scratch folder>`
Expected: "Documentation built", no WARNING lines.

- [ ] **Step 3: Run the merge tier once**

Run: `python -m pytest -n 8`
Expected: all pass (the slow chain tests included).

- [ ] **Step 4: Commit**

```bash
git add docs/criteria.md mkdocs.yml docs/getting-started/configuration.md docs/project-map.md CHANGELOG.md
git commit -m "docs: chained carvings in the engine (criteria, run_chain, --after)"
```

---

## Not in this phase

- Browser service and app (spec phases 2 and 3), the Grasshopper input on `USC_ThresholdStage` (it runs through `RunRequest`; added with the service phase), removing **Carve further**.
- A separate chain-root stage folder or cache (spec 6.2, builder's call): each criterion voxelizes the same max volume; Task 1's grid check guarantees the grids agree.
