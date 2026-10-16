# Stage Contract Restructure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the UrbanSolarCarver stage layer one contract (per-stage settings, run IDs, one stage-folder helper, a run context for issues/progress/cancel, a small exception set, one sequencer) that the CLI, the daemon, Grasshopper and a future HTTP service share.

**Architecture:** `UserConfig` stays the validated flat config; frozen per-stage settings models are projected from it and passed to stage internals. Manifests carry a random `run_id`, relative paths and the facts downstream reads; `api_core/_stage_io.py` owns stage folders. A context variable carries the active `RunContext`, so engine code reports issues and progress without signature changes. Standard-library-only modules (`mode_registry`, `archetype_defaults`, `errors`, `run_context`) hold facts Grasshopper loads by file path.

**Tech Stack:** Python 3.10, pydantic v2, numpy, torch, NVIDIA Warp, trimesh, shapely, typer (CLI), multiprocessing.connection (daemon), Rhino 8 Python 3 script components.

**Spec:** `docs/superpowers/specs/2026-10-16-stage-contract-design.md` (local, not committed). Read it with this plan; section numbers below (S3, S4, ...) refer to it.

## Global Constraints

- Run tests from the worktree root with `PYTHONPATH=src ../../../.venv/Scripts/python.exe -m pytest` (written `$PYTEST` below). The venv's editable install points at the main checkout, so `PYTHONPATH=src` is required.
- Files use CRLF line endings and git has `core.autocrlf=true`; edit with tools that keep line endings, and never open files with Python's default encoding (it is cp1253 here): always `encoding="utf-8"`.
- Every task ends with the full fast suite green: `$PYTEST tests -q -p no:cacheprovider --ignore=tests/test_daemon.py --ignore=tests/test_typologies.py --ignore=tests/test_montecarlo.py`. Tasks 6, 8, 10, 11 and 14 also run the full suite (`$PYTEST tests -q -p no:cacheprovider`, about 3 minutes, run in the background).
- One commit per task, message style `fix(...)`/`feat(...)`/`refactor(...)`, ending with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Do not push or merge.
- Writing rules for code comments, docstrings, messages and the CHANGELOG: no em dashes, no cliché labels ("the spine", "load-bearing", ...), they/them pronouns, long descriptive names.
- No new parameters or concepts beyond the spec. Anything the plan leaves open that would add one: stop and ask the owner.
- `docs/superpowers/` is gitignored on purpose: never commit the spec or this plan.
- Standard-library-only modules: `mode_registry.py`, `archetype_defaults.py`, `errors.py`, `run_context.py` import nothing outside the standard library (no numpy, no pydantic, no package-relative imports).
- `diagnostic.json` key names do not change (the run report and Grasshopper read them).
- `UserConfig` field names, defaults and validation rules do not change (D8, D9).

## Deviations from the spec (for the owner's review)

- **S7 daemon aliases and CLI stage commands.** The spec maps the old daemon stage commands onto `run` and refuses a `from`/`out_dir` that differs from `stage_folder(...)`. The CLI stage commands accept any `-f` and `--out`, and `--daemon` forwards them, so that refusal would break CLI users with their own folder layout. This plan keeps the old stage commands (daemon and CLI) calling the public stage functions, which accept any layout, inside a `RunContext`; only `run` (daemon) and `usc run` (CLI) go through the sequencer. Grasshopper moves to `run`. No sequencing logic stays in a client.

## Review Focus

- A run folder copied to another drive letter on Windows: relative paths are impossible, so manifests keep absolute paths; `load_upstream` must still resolve them (Task 6 test `test_absolute_paths_still_load`).
- A config whose mode is changed between preprocessing and a direct `thresholding(...)` call: thresholding resolves defaults with the manifest's mode, and today's "scores come from a ... run" refusal must survive the settings refactor (Task 8 test `test_thresholding_refuses_a_config_of_another_mode`).
- A preprocessing run whose max volume has no plan area (a degenerate mesh): `footprint.json` holds an empty list, an issue is reported, massing uses the voxel footprint (Task 7 test `test_empty_footprint_falls_back_to_voxels`).
- Cancel requested while CPU worker threads are running batches: workers stop at their next batch and `RunCancelled` reaches the caller, not a thread-pool error (Task 10 test `test_cancel_stops_parallel_cpu_batches`).
- A daemon request with no `config` and no `mode` override: refused with a `ConfigError` reply naming `mode`, not a `KeyError` (Task 11 test `test_run_without_yaml_requires_mode`).

---

### Task 1: Exceptions and the run context

**Files:**
- Create: `src/urbansolarcarver/errors.py`, `src/urbansolarcarver/run_context.py`
- Test: `tests/test_run_context.py`

**Interfaces:**
- Produces (`errors.py`): `class UrbanSolarCarverError(Exception)`; `class ConfigError(UrbanSolarCarverError, ValueError)` with `__init__(self, message: str, errors: list[ConfigFieldError] | None = None)` and attribute `errors`; `@dataclass(frozen=True) class ConfigFieldError: field: str | None; message: str`; `class InputError(UrbanSolarCarverError, ValueError)`; `class StageChainError(UrbanSolarCarverError, ValueError)`; `class RunCancelled(UrbanSolarCarverError)`; `class UrbanSolarCarverWarning(UserWarning)` (moved here from `pydantic_schemas.py`, which re-exports it).
- Produces (`run_context.py`): `@dataclass(frozen=True) class Issue: stage: str | None; code: str; message: str`; `class RunContext` with `__init__(self, on_progress: Callable[[str | None, int, int], None] | None = None, forward_issues_to_warnings: bool = False)`, attributes `issues: list[Issue]`, `current_stage: str | None`, `cancel_event: threading.Event`, methods `cancel() -> None`, `raise_if_cancelled() -> None` (raises `RunCancelled`), `issues_of(stage: str) -> tuple[Issue, ...]`; `run_context(context: RunContext)` context manager that sets the context variable; `active_context() -> RunContext | None`; `report_issue(code: str, message: str) -> None`; `report_progress(done: int, total: int) -> None`; `stage_context(stage: str)` context manager yielding the active context with `current_stage` set to *stage* (restored after), or, with none active, a new `RunContext(forward_issues_to_warnings=True)` activated for the block.

- [ ] **Step 1: Write the failing tests** in `tests/test_run_context.py`:

```python
import threading, warnings, pytest
from urbansolarcarver.run_context import (RunContext, Issue, run_context, report_issue,
                                          report_progress, stage_context, active_context)
from urbansolarcarver.errors import (RunCancelled, ConfigError, ConfigFieldError, InputError,
                                     StageChainError, UrbanSolarCarverError, UrbanSolarCarverWarning)

def test_issues_are_collected_with_their_stage_and_repeats_kept():
    context = RunContext()
    with run_context(context), stage_context("thresholding"):
        report_issue("nothing_carved", "all kept")
        report_issue("nothing_carved", "all kept")
    assert context.issues == [Issue("thresholding", "nothing_carved", "all kept")] * 2

def test_without_a_context_an_issue_is_a_warning():
    with pytest.warns(UrbanSolarCarverWarning, match="all kept"):
        report_issue("nothing_carved", "all kept")

def test_stage_context_without_an_active_context_collects_and_warns():
    with pytest.warns(UrbanSolarCarverWarning):
        with stage_context("massing") as context:
            report_issue("no_plates_fit", "none")
    assert context.issues_of("massing") == (Issue("massing", "no_plates_fit", "none"),)
    assert active_context() is None

def test_progress_reaches_the_callback_with_the_stage():
    calls = []
    with run_context(RunContext(on_progress=lambda s, d, t: calls.append((s, d, t)))), stage_context("preprocessing"):
        report_progress(2, 5)
    assert calls == [("preprocessing", 2, 5)]

def test_cancel_raises_run_cancelled():
    context = RunContext()
    context.cancel()
    with pytest.raises(RunCancelled):
        context.raise_if_cancelled()

def test_exception_classes_keep_their_builtin_bases():
    assert issubclass(ConfigError, ValueError) and issubclass(InputError, ValueError)
    assert issubclass(StageChainError, ValueError)
    assert ConfigError("bad", [ConfigFieldError("voxel_size", "too small")]).errors[0].field == "voxel_size"
    assert all(issubclass(c, UrbanSolarCarverError) for c in (ConfigError, InputError, StageChainError, RunCancelled))
```

- [ ] **Step 2: Run them, expect ImportError.** `$PYTEST tests/test_run_context.py -q`
- [ ] **Step 3: Implement both modules.** The context variable is a module-level `contextvars.ContextVar("urbansolarcarver_run_context", default=None)`. `report_issue` appends `Issue(context.current_stage, code, message)` and, when `forward_issues_to_warnings` is set or no context is active, calls `warnings.warn(message, UrbanSolarCarverWarning, stacklevel=3)`. `report_progress` calls `on_progress(current_stage, done, total)` when set. In `pydantic_schemas.py`, replace the class body of `UrbanSolarCarverWarning` with `from .errors import UrbanSolarCarverWarning`.
- [ ] **Step 4: Run the new tests and the fast suite; expect PASS.**
- [ ] **Step 5: Commit** `feat(engine): exceptions and a run context for issues, progress and cancel`.

### Task 2: Engine warnings become issues; Results carry them

**Files:**
- Modify: `src/urbansolarcarver/pydantic_schemas.py` (6 sites), `sky_patches.py` (5), `api_core/thresholding.py` (4), `api_core/massing.py` (4), `carving.py` (3), `grid.py` (3), `api_core/preprocessing.py` (1), `api_core/_diagnostics.py` (1), `sun.py` (1); `raytracer.py:980` and `simulated_weights.py:347` become `log.warning`; `api_core/exporting.py:157` is removed in Task 8 (leave it).
- Modify: the four public stage functions and their Result dataclasses.
- Test: `tests/test_run_context.py`, `tests/test_stage_outputs.py`

**Interfaces:**
- Consumes: Task 1 `report_issue`, `stage_context`, `Issue`.
- Produces: every Result dataclass gains `issues: tuple[Issue, ...] = ()`; each public stage function body runs inside `with stage_context("<stage>") as context:` and returns `issues=context.issues_of("<stage>")`.

Issue codes (snake_case, stable; one per site, the same code where two sites report the same condition):

| Site | Code |
|---|---|
| pydantic_schemas experimental mode / threshold-carve_fraction disagree / carve_fraction unused / fields unused by mode / balance-point unused / ray_batch_size clamped | `experimental_mode`, `threshold_value_disagrees`, `carve_fraction_unused`, `settings_unused_by_mode`, `balance_point_unused`, `ray_batch_size_clamped` |
| thresholding no voxel_size / smoothing clipped / all kept / all carved | `smoothing_skipped`, `smoothing_radius_clipped`, `nothing_carved`, `everything_carved` |
| massing footprint unreadable / mismatch / raised part / no plates | `footprint_unreadable`, `footprint_mismatch`, `raised_part`, `no_plates_fit` |
| carving float32 georeferenced / no sun vectors (and sun.py) / horizontal tilted-plane surfaces | `float32_coordinates`, `no_sun_vectors`, `horizontal_test_surfaces` |
| grid edge_taper component excluded / test-surface components skipped / cleanup kept largest part | `edge_taper_excluded_component`, `test_surface_components_skipped`, `mesh_cleanup_kept_largest_part` |
| preprocessing edge_taper ignored; _diagnostics non-finite scores | `edge_taper_ignored`, `nonfinite_scores` |
| sky_patches dew point outside fit / each all-zero or degenerate weights site | `dew_point_outside_fit`, `zero_patch_weights` |

- [ ] **Step 1: Write the failing tests.** In `tests/test_run_context.py`:

```python
def test_config_warnings_land_in_an_active_run_context():
    from urbansolarcarver.pydantic_schemas import UserConfig
    context = RunContext()
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        with run_context(context):
            UserConfig(max_volume_path="v", test_surface_path="s", out_dir="o",
                       mode="radiative_cooling")
    assert [i.code for i in context.issues] == ["experimental_mode"]
```

In `tests/test_stage_outputs.py`:

```python
def test_thresholding_result_carries_its_issues(tmp_path, thresholded_run):
    from urbansolarcarver import thresholding
    from urbansolarcarver.pydantic_schemas import ThresholdSpec
    conf, thr = thresholded_run
    keep_everything = conf.model_copy(update={"threshold": ThresholdSpec(method="cutoff", value=1e9)})
    result = _quietly(thresholding, thr.upstream_manifest, keep_everything, thr.out_dir)
    assert [i.code for i in result.issues] == ["nothing_carved"]
```

- [ ] **Step 2: Run them; expect FAIL** (no `issues`, wrong codes).
- [ ] **Step 3: Replace each listed `warnings.warn(...)` with `report_issue("<code>", <same message>)`**, wrap each public stage function body in `stage_context`, add `issues` to the Results. Keep messages unchanged. Remove `stacklevel` arguments and now-unused `import warnings`.
- [ ] **Step 4: Run the fast suite; expect PASS** (existing `pytest.warns(UserWarning, ...)` tests keep passing because direct stage calls forward issues to warnings).
- [ ] **Step 5: Commit** `refactor(engine): report user-facing warnings as run issues with codes`.

### Task 3: Config input and input errors

**Files:**
- Modify: `src/urbansolarcarver/load_config.py`, `grid_planning.py`, `carving.py` (`validate_inputs`), `grid.py` (`voxelize` empty grid), `api_core/preprocessing.py` (no sample points, radiative surface)
- Test: `tests/test_schemas.py`, `tests/test_grid.py`, `tests/test_pipeline.py`

**Interfaces:**
- Consumes: Task 1 `ConfigError`, `ConfigFieldError`, `InputError`.
- Produces: `build_config(values: Mapping[str, Any], base_folder: Path | str | None = None) -> UserConfig` in `load_config.py`, exported from `urbansolarcarver/__init__.py` (light import, next to `load_config`). `load_config(path, overrides=None)` reads YAML and returns `build_config(merged, base_folder=Path(path).resolve().parent)`. `check_voxel_grid_budget` raises `ConfigError` with one `ConfigFieldError("voxel_size", ...)`.

- [ ] **Step 1: Write the failing tests** in `tests/test_schemas.py`:

```python
class TestBuildConfig:
    def test_relative_paths_resolve_against_the_base_folder(self, tmp_path):
        from urbansolarcarver.load_config import build_config
        conf = build_config({"max_volume_path": "vol.ply", "test_surface_path": "srf.ply",
                             "out_dir": "out", "mode": "daylight"}, base_folder=tmp_path)
        assert conf.max_volume_path == str(tmp_path / "vol.ply")

    def test_field_errors_are_structured(self):
        from urbansolarcarver.load_config import build_config
        from urbansolarcarver.errors import ConfigError
        with pytest.raises(ConfigError) as caught:
            build_config({"max_volume_path": "v", "test_surface_path": "s", "out_dir": "o",
                          "mode": "daylight", "voxel_size": 0.0})
        assert [e.field for e in caught.value.errors] == ["voxel_size"]

    def test_whole_config_checks_have_no_field(self):
        from urbansolarcarver.load_config import build_config
        from urbansolarcarver.errors import ConfigError
        with pytest.raises(ConfigError) as caught:
            build_config({"max_volume_path": "v", "test_surface_path": "s", "out_dir": "o",
                          "mode": "daylight", "voxel_size": 1.0, "grid_step": 2.0})
        assert caught.value.errors[0].field is None and "grid_step" in caught.value.errors[0].message
```

In `tests/test_grid.py::TestVoxelGridPlan`, change the budget test's `pytest.raises(ValueError, ...)` to `pytest.raises(ConfigError)` and assert `errors[0].field == "voxel_size"`. In `tests/test_pipeline.py`, add a test that `preprocessing` with a missing max volume file raises `InputError` matching `max_volume file missing`.

- [ ] **Step 2: Run; expect FAIL.**
- [ ] **Step 3: Implement.** `build_config` holds today's `load_config` body after the YAML read (period expansion, path resolution when `base_folder` is given, validation); pydantic errors map to `ConfigFieldError(".".join(loc) or None, msg)`; the `ConfigError` message is today's `"Configuration validation error:\n  ..."` text. Malformed YAML raises `ConfigError`; a missing YAML file stays `FileNotFoundError`. `validate_inputs` missing files, `voxelize` empty grid, preprocessing no sample points and radiative surface raise `InputError` (fix the preprocessing docstring that says `RuntimeError`). Update tests that expected `FileNotFoundError`/`RuntimeError` at these sites.
- [ ] **Step 4: Run the fast suite; expect PASS.**
- [ ] **Step 5: Commit** `feat(config): build_config from typed values; ConfigError with field errors; InputError`.

### Task 4: Per-stage settings models and rerun decisions

**Files:**
- Create: `src/urbansolarcarver/stage_settings.py`
- Test: `tests/test_stage_settings.py`

**Interfaces:**
- Consumes: `UserConfig`, `resolve_threshold` (pydantic_schemas), `mode_registry.MODES`, `_MODE_SPECIFIC_FIELDS`.
- Produces: frozen pydantic models `PreprocessingSettings`, `ThresholdingSettings`, `ExportingSettings`, `MassingSettings`, `RunOptions` with the fields of spec S3 (same names and types as `UserConfig`), each with `@classmethod from_config(cls, config: UserConfig)`. `PreprocessingSettings.effective_values() -> dict`; `ThresholdingSettings.effective_values(mode: str, voxel_size: float) -> dict` with keys `threshold` (the resolved `ThresholdSpec` dumped), `score_smoothing_m`, `max_slope_deg`, `carve_above`, `carve_above_min_consecutive`; `ExportingSettings.effective_values() -> dict`; `MassingSettings.effective_values() -> dict`. `PIPELINE_STAGES = ("preprocessing", "thresholding", "exporting", "massing")`; `stages_to_rerun(previous_config: UserConfig | None, new_config: UserConfig, produce: Iterable[str]) -> list[str]`.
- Also produces, in `stage_settings.py`, the pure helper `applied_smoothing_radius_m(kind: str, voxel_size: float, score_smoothing: float | None) -> float` (the radius `_apply_score_smoothing` applies after the 0.5-8 voxel clip, 0 when off). `api_core/thresholding._apply_score_smoothing` imports and uses it, so the stage and the comparison cannot disagree (`stage_settings.py` must not import `api_core`, which pulls torch).

- [ ] **Step 1: Write the failing tests** in `tests/test_stage_settings.py` (use `daylight_cube_config` from `_stage_scene` for configs):

```python
from urbansolarcarver.stage_settings import (PreprocessingSettings, ThresholdingSettings, ExportingSettings,
    MassingSettings, RunOptions, stages_to_rerun)
from urbansolarcarver.pydantic_schemas import UserConfig

def test_every_config_field_belongs_to_exactly_one_settings_model():
    models = (PreprocessingSettings, ThresholdingSettings, ExportingSettings, MassingSettings, RunOptions)
    owners = {}
    for model in models:
        for name in model.model_fields:
            owners.setdefault(name, []).append(model.__name__)
    assert set(owners) == set(UserConfig.model_fields)
    assert all(len(v) == 1 for v in owners.values())

def test_unset_and_explicit_defaults_compare_equal(tmp_path):
    a = daylight_cube_config(tmp_path)                       # max_slope_deg None, weighted mode
    b = daylight_cube_config(tmp_path, max_slope_deg=75.0, score_smoothing=1.1)
    assert stages_to_rerun(a, b, {"exporting"}) == []

def test_a_massing_setting_reruns_massing_only(tmp_path):
    a = daylight_cube_config(tmp_path)
    assert stages_to_rerun(a, daylight_cube_config(tmp_path, plate_tolerance=0.3),
                           {"exporting", "massing"}) == ["massing"]

def test_a_threshold_change_reruns_thresholding_and_the_produced_leaves(tmp_path):
    a = daylight_cube_config(tmp_path)
    assert stages_to_rerun(a, daylight_cube_config(tmp_path, carve_fraction=0.5),
                           {"exporting"}) == ["thresholding", "exporting"]

def test_a_field_the_mode_does_not_read_reruns_nothing(tmp_path):
    a = daylight_cube_config(tmp_path)
    with pytest.warns(UserWarning):                      # settings_unused_by_mode
        b = daylight_cube_config(tmp_path, bliss_k=1.5)
    assert stages_to_rerun(a, b, {"exporting"}) == []

def test_run_options_never_cause_a_rerun(tmp_path):
    a = daylight_cube_config(tmp_path)
    assert stages_to_rerun(a, daylight_cube_config(tmp_path, ray_batch_size=1000, diagnostics=True),
                           {"exporting"}) == []

def test_no_previous_config_runs_everything_needed(tmp_path):
    assert stages_to_rerun(None, daylight_cube_config(tmp_path), {"massing"}) == [
        "preprocessing", "thresholding", "massing"]

def test_smooth_iters_is_ignored_without_smoothing(tmp_path):
    a = daylight_cube_config(tmp_path)
    assert stages_to_rerun(a, daylight_cube_config(tmp_path, smooth_iters=4), {"exporting"}) == []
```

- [ ] **Step 2: Run; expect ImportError.**
- [ ] **Step 3: Implement.** Field lists exactly as spec S3. `stages_to_rerun` validates `produce` against `PIPELINE_STAGES` (`ValueError` for unknown names) and follows the three rules of S3; the leaves are the produced stages among exporting and massing, in `PIPELINE_STAGES` order. Producing "preprocessing" or "thresholding" alone is allowed (the list stops there).
- [ ] **Step 4: Run the fast suite; expect PASS.**
- [ ] **Step 5: Commit** `feat(stages): per-stage settings models and stages_to_rerun`.

### Task 5: Diagnostics separated from compute

**Files:**
- Modify: `src/urbansolarcarver/api_core/_diagnostics.py`, `api_core/preprocessing.py` (summary building and plot block, about lines 349-440), `api_core/thresholding.py` (diagnostics block)
- Test: `tests/test_util.py`, `tests/test_pipeline.py`

**Interfaces:**
- Produces: `write_preprocessing_diagnostics(summary: dict, folder: Path, config: UserConfig, plot_inputs: PreprocessingPlotInputs) -> None` and `write_thresholding_diagnostics(summary: dict, folder: Path, plot_inputs: ThresholdingPlotInputs, diagnostic_plots: bool) -> None` in `_diagnostics.py`, where the two small frozen dataclasses hold the arrays the plots need (raw scores, patch weights and unit for preprocessing; occupied scores, threshold value, method and unit for thresholding). Exporting and massing keep writing their `diagnostic.json` with `write_json` (they draw no plots). (The config parameter of the preprocessing writer becomes `PreprocessingSettings` plus `RunOptions` in Task 8.)

- [ ] **Step 1: Write the failing tests.** In `tests/test_util.py`:

```python
def test_importing_the_api_does_not_import_matplotlib():
    import subprocess, sys
    code = "import sys, urbansolarcarver.api; print('matplotlib' in sys.modules)"
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    assert out.stdout.strip() == "False"
```

Keep the existing diagnostic-key tests in `test_pipeline.py` as the guard that keys do not change.
- [ ] **Step 2: Run; expect FAIL ("True").**
- [ ] **Step 3: Move the code.** The stage keeps computing `summary`; everything that writes files (`dump_config_snapshot`, `write_json`, plots, the benefit comparison with its EPW re-read) moves into the writer. Plot helpers build `matplotlib.figure.Figure()` and save through `FigureCanvasAgg`, as `simulated_weights._save_heatmaps` does; `matplotlib` is imported inside the plot helpers only, and the module-level backend selection is deleted.
- [ ] **Step 4: Run the fast suite; expect PASS.** Also run a preprocessing with `diagnostic_plots=True` (the `TestStageOutputs` plot test from A5) to confirm the PNGs are still written.
- [ ] **Step 5: Commit** `refactor(diagnostics): write diagnostics after compute; no matplotlib at import`.

### Task 6: Manifests with run IDs and relative paths; the stage folder helper

**Files:**
- Create: `src/urbansolarcarver/api_core/_stage_io.py`
- Modify: `pydantic_schemas.py` (manifests; delete `UpstreamMismatchError`), `api_core/_util.py` (delete `remove_previous_stage_outputs`, `verify_upstream_hash`; `load_thresholded_grid` uses `load_upstream`), the four stage modules, `api_core/_reporting.py` (`_leaf_stage_dir` compares `upstream_run_id`), `carver_cli.py` (prints `Run ID` instead of `Hash`), CHANGELOG
- Test: `tests/test_stage_chain.py`, `tests/test_stage_outputs.py`, `tests/test_pipeline.py`, `tests/test_massing_stage.py` (helper `_set_mask`), `tests/oracle.py`

**Interfaces:**
- Consumes: Task 1 `StageChainError`.
- Produces in `_stage_io.py`: `stage_folder(run_folder: Path | str, stage: str) -> Path`; `begin_stage(out_dir: Path | str, output_names: Iterable[str]) -> Path`; `commit_manifest(folder: Path, manifest: BaseModel) -> None`; `load_upstream(source, expected_stage: str) -> LoadedManifest` where `@dataclass(frozen=True) class LoadedManifest: manifest: BaseModel; folder: Path; manifest_path: Path` and `resolve(self, relative_path: str) -> Path`; `new_run_id() -> str` (`uuid.uuid4().hex`); `stored_path(path: Path, manifest_folder: Path) -> str` (relative via `os.path.relpath`, absolute on `ValueError`).
- Manifests (pydantic_schemas): fields exactly as spec S4 plus `run_id: str`; downstream ones add `upstream_manifest: str`, `upstream_run_id: str`; `hash` and `upstream_hash` removed. `PreprocessingManifest.footprint_path` is added in Task 7 (not here).
- Results: `PreprocessingResult.hash` becomes `run_id`; `ThresholdingResult.hash`/`upstream` become `run_id`/`upstream_run_id`.

- [ ] **Step 1: Write the failing tests.** Retarget `tests/test_stage_chain.py` to `StageChainError` and `run_id` (`manifest.upstream_run_id == pre.run_id`, `thr.run_id`). Add:

```python
def test_rerunning_preprocessing_with_identical_settings_still_refuses_the_old_mask(tmp_path):
    # identical config twice: settings equal, run IDs differ
    ...  # preprocessing, thresholding, preprocessing again with the same config
    with pytest.raises(StageChainError, match="preprocessing"):
        exporting(thr, conf, tmp_path / "run" / "exporting")

def test_a_moved_run_folder_still_exports(tmp_path):
    # run pre + thr in tmp_path/"run", shutil.move to tmp_path/"moved", delete nothing else
    result = exporting(tmp_path / "moved" / "thresholding", conf, tmp_path / "moved" / "exporting")
    assert result.export_path.is_file()
    manifest = json.loads((tmp_path / "moved" / "thresholding" / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["mask_path"] == "mask.npy"
    assert manifest["upstream_manifest"] == "../preprocessing/manifest.json".replace("/", os.sep)

def test_absolute_paths_still_load(tmp_path):
    # rewrite the thresholding manifest's paths as absolute, then export: succeeds

def test_a_manifest_without_run_id_asks_for_a_rerun(tmp_path):
    # delete "run_id" from preprocessing/manifest.json, then thresholding(...)
    with pytest.raises(StageChainError, match="re-run preprocessing"):
        ...
```

Write the three elided bodies with the `thresholded_run` fixture pattern of `test_stage_outputs.py`.
- [ ] **Step 2: Run; expect FAIL.**
- [ ] **Step 3: Implement.** `load_upstream` accepts a Result (uses its `manifest_path`, or `out_dir / "manifest.json"`), a folder, or a manifest path; parses with the manifest class for `expected_stage`; on parse or validation failure raises `StageChainError(f"... re-run {expected_stage}")`; for downstream manifests it loads the referenced upstream manifest and raises `StageChainError` naming the upstream stage when `upstream_run_id` differs. Stage modules call `begin_stage` at the start (replacing `remove_previous_stage_outputs`), write paths with `stored_path`, and `commit_manifest` last. `load_thresholded_grid` keeps its return type and is rebuilt on `load_upstream`. Update `tests/test_massing_stage.py::_set_mask` and `tests/oracle.py` to resolve manifest paths relative to the manifest folder. CHANGELOG: replace the A1 entry's `upstream_hash`/`UpstreamMismatchError` wording with run IDs and `StageChainError`, and add the migration note of spec S11 (one re-run from preprocessing).
- [ ] **Step 4: Run the full suite (background); expect PASS.**
- [ ] **Step 5: Commit** `refactor(stages): run IDs and relative paths in manifests; one stage folder helper`.

### Task 7: Preprocessing saves the footprint; massing reads it

**Files:**
- Modify: `api_core/preprocessing.py`, `api_core/massing.py` (`_footprint`), `pydantic_schemas.py` (`footprint_path` added, `max_volume_path` removed), `docs/massing.md`
- Test: `tests/test_massing_stage.py`

**Interfaces:**
- Consumes: Task 6 `LoadedManifest.resolve`, `stored_path`.
- Produces: `footprint.json` in the preprocessing folder: `{"polygons": [{"exterior": [[x, y], ...], "holes": [[[x, y], ...], ...]}, ...]}` in world xy; `PreprocessingManifest.footprint_path: str`. `floor_plates.footprint_polygons(mesh, offset_xy)` is called with `offset_xy=(0, 0)` on the world-space mesh (before the local frame shift), so stored coordinates are world coordinates; massing translates by `-origin[:2]` to local.

- [ ] **Step 1: Write the failing tests** in `tests/test_massing_stage.py`: replace `test_outline_not_matching_the_voxels_falls_back` and `test_footprint_comes_from_the_mesh_preprocessing_read` with:

```python
def test_massing_ignores_a_max_volume_file_edited_after_preprocessing(tmp_path):
    cfg, thr = _run_upstream(tmp_path, _box([30, 12, 20]))
    _set_mask(thr, lambda occ: occ)
    _box([36, 18, 20]).export(tmp_path / "max_volume.ply")      # edited in place
    res = _massing(cfg, thr, tmp_path / "m")
    assert res.floor_areas[0] == pytest.approx(30 * 12, rel=1e-6)

def test_empty_footprint_falls_back_to_voxels(tmp_path, monkeypatch):
    from urbansolarcarver import floor_plates as mg
    monkeypatch.setattr(mg, "footprint_polygons", lambda mesh, offset_xy: [])
    cfg, thr = _run_upstream(tmp_path, _box([30, 12, 20]))     # preprocessing writes []
    _set_mask(thr, lambda occ: occ)
    with pytest.warns(UserWarning, match="voxel footprint"):
        res = _massing(cfg, thr, tmp_path / "m")
    assert res.n_plates == 6
```

`_run_upstream` must not swallow the preprocessing issue in the second test (it filters warnings; check `pre.issues` codes include `footprint_unreadable` by returning `pre` too, or assert on `footprint.json` content `{"polygons": []}`).
- [ ] **Step 2: Run; expect FAIL** (the edited file changes the plates today).
- [ ] **Step 3: Implement.** Preprocessing computes the footprint from the loaded max volume (world coordinates) and writes it; a projection error or empty result writes `{"polygons": []}` and reports `footprint_unreadable`. Massing builds shapely polygons from the file and keeps the `FOOTPRINT_MISMATCH_SHARE` check. Add `footprint.json` to the preprocessing output names. Update `docs/massing.md` (footprint from the preprocessing run) and the CHANGELOG A4 entry.
- [ ] **Step 4: Run the fast suite; expect PASS.**
- [ ] **Step 5: Commit** `fix(massing): read the footprint preprocessing saved, never the input mesh`.

### Task 8: Stage internals take their settings models

**Files:**
- Modify: the four stage modules, `carving.py` (`_resolve_batch_size`, `_count_ray_hits`, `carve_with_sun_rays`, `carve_with_sky_patch_rays`, `carve_with_planes`, `validate_inputs`, `sample_period`, `load_meshes`), `grid.py` (`voxelize`, `sample_surface`, `finalize_mesh`), `sun.py`, `api_core/_diagnostics.py` (preprocessing writer signature)
- Test: `tests/test_grid.py` (395-399, 611-626), `tests/test_north.py` (69-90), `tests/test_pipeline.py`

**Interfaces:**
- Consumes: Task 4 models; Task 6 `load_upstream`.
- Produces: internal functions `_run_preprocessing(settings: PreprocessingSettings, options: RunOptions, out_path: Path, context: RunContext) -> PreprocessingResult`, and likewise `_run_thresholding(settings, options, upstream: LoadedManifest, out_path, context)`, `_run_exporting(settings, options, upstream, out_path, context)`, `_run_massing(settings, options, upstream, out_path, context)`. Public functions keep `stage(config, [upstream,] out_dir)` and only project the config, load the upstream and call the internal function inside `stage_context`. Carving and grid functions take the settings model in place of `config` (same attribute names); `ray_batch_size` becomes an explicit keyword `ray_batch_size: int` of `_resolve_batch_size`, `_count_ray_hits`, `carve_with_sun_rays`, `carve_with_sky_patch_rays`, `carve_with_planes`. `finalize_mesh(carved_grid, grid_origin, settings: ExportingSettings, voxel_size: float)`.

- [ ] **Step 1: Write the failing tests** in `tests/test_pipeline.py`:

```python
def test_thresholding_refuses_a_config_of_another_mode(tmp_path):
    # preprocessing in daylight mode, then thresholding with mode="irradiance" (+ epw/period)
    with pytest.raises(StageChainError, match="daylight"):
        ...

def test_exporting_meshes_with_the_preprocessing_voxel_size(tmp_path):
    # export with a config whose voxel_size differs: no issue, bounds match the run's grid
```

Today the first raises `ValueError` (adapt to `StageChainError`: a config that does not fit the upstream run is a chain error); the second emits a warning today (`voxel_size` mismatch) and must not after this task.
- [ ] **Step 2: Run; expect FAIL.**
- [ ] **Step 3: Refactor.** Thresholding takes `mode` and `voxel_size` from the preprocessing manifest and resolves its defaults with `ThresholdingSettings.effective_values(mode, voxel_size)`; it refuses a config whose `mode` differs from the manifest's with `StageChainError`. Exporting takes `voxel_size` from the manifest and drops its config-voxel-size warning. Update the four tests that pass a `UserConfig` or `SimpleNamespace` into internals to pass the settings model.
- [ ] **Step 4: Run the full suite (background); expect PASS.**
- [ ] **Step 5: Commit** `refactor(stages): stage internals receive only their own settings`.

### Task 9: Mode facts and archetype defaults in standard-library modules

**Files:**
- Create: `src/urbansolarcarver/archetype_defaults.py`
- Modify: `mode_registry.py`, `simulated_weights.py` (defaults from `archetype_defaults`), `carver_cli.py` (`_ARCHETYPE_DEFAULTS`, `_ARCHETYPE_OPTIONAL` replaced by imports), `configs/config_benefit.yaml`, `configs/config_irradiance.yaml`, `configs/config_time_based.yaml` (remove the UTF-8 BOM only)
- Test: `tests/test_modes.py`

**Interfaces:**
- Produces: `ModeSpec.description: str` (text from `USC_Mode.py` `_DESCRIPTIONS`), `ModeSpec.starting_values: Mapping[str, object]` (default empty); `MODES` reordered to time-based, irradiance, benefit, daylight, radiative_cooling, tilted_plane; `MODE_ALIASES: dict[str, str]` (the `_mode_canonical` map of `USC_Config.py`); `canonical_mode_name(name: str) -> str` (strip, lower, alias). Starting values: benefit `{"start_month": 10, "start_day": 15, "start_hour": 7, "end_month": 4, "end_day": 15, "end_hour": 19}`; irradiance `{1, 1, 0, 12, 31, 23}` as the same six keys; time-based `{12, 21, 10, 12, 21, 14}`; tilted_plane `{"tilted_plane_angle_deg": 45.0}`; radiative_cooling `{"carve_fraction": 0.35}`; daylight empty. `archetype_defaults.py`: `ARCHETYPE_DEFAULTS` (the scalar dict of `carver_cli.py:593-602` without `wwr`), `WINDOW_TO_WALL_DEFAULTS = {"south": 0.35, "east": 0.15, "west": 0.15, "north": 0.0}`, `ARCHETYPE_OPTIONAL_KEYS = ("shading_permanent", "shading_hot", "hot_months")`.

- [ ] **Step 1: Write the failing tests** in `tests/test_modes.py`:

```python
import subprocess, sys, pathlib
LIGHT_MODULES = ("mode_registry", "archetype_defaults", "errors", "run_context")

@pytest.mark.parametrize("name", LIGHT_MODULES)
def test_light_module_imports_with_the_standard_library_alone(name):
    path = pathlib.Path(__file__).parents[1] / "src" / "urbansolarcarver" / f"{name}.py"
    code = ("import importlib.util, sys; sys.path = [p for p in sys.path if 'site-packages' not in p]; "
            f"spec = importlib.util.spec_from_file_location('m', r'{path}'); "
            "m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)")
    subprocess.run([sys.executable, "-I", "-c", code], check=True)

@pytest.mark.parametrize("mode", ["benefit", "irradiance", "time-based", "tilted_plane", "radiative_cooling", "daylight"])
def test_example_configs_agree_with_the_starting_values(mode):
    import yaml
    from urbansolarcarver.mode_registry import MODES
    from urbansolarcarver.pydantic_schemas import expand_analysis_period
    path = pathlib.Path(__file__).parents[1] / "configs" / f"config_{mode.replace('-', '_')}.yaml"
    raw = path.read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf")
    values = expand_analysis_period(yaml.safe_load(raw.decode("utf-8")))
    for key, value in MODES[mode].starting_values.items():
        assert values[key] == value

def test_mode_order_matches_the_grasshopper_menu():
    from urbansolarcarver.mode_registry import MODES
    assert list(MODES) == ["time-based", "irradiance", "benefit", "daylight", "radiative_cooling", "tilted_plane"]
```

- [ ] **Step 2: Run; expect FAIL.**
- [ ] **Step 3: Implement** the additions; strip the BOMs (no other change to the YAML files). `errors.py` and `run_context.py` already pass the import test if Task 1 kept them standard-library only.
- [ ] **Step 4: Run the fast suite; expect PASS.**
- [ ] **Step 5: Commit** `feat(modes): mode descriptions, aliases, starting values and archetype defaults in light modules`.

### Task 10: The sequencer, progress and cancel

**Files:**
- Modify: `src/urbansolarcarver/api.py`, `src/urbansolarcarver/__init__.py` (export `PipelineResult`, `stages_to_rerun`, `build_config`), `carving.py` (`_run_batches`)
- Test: `tests/test_sequencer.py` (new), `tests/test_pipeline.py::test_run_pipeline_convenience`, `tests/test_modes.py` (callers of `run_pipeline`), `tests/test_typologies.py:222` (monkeypatch of `_run_batches` keeps its signature)

**Interfaces:**
- Consumes: Tasks 1, 4, 6, 8.
- Produces: `run_pipeline(config: UserConfig | str | Path, out_dir: str | Path, produce: Iterable[str] = ("exporting",), start_from: str = "preprocessing", context: RunContext | None = None) -> PipelineResult`; `@dataclass(frozen=True) class PipelineResult: preprocessing: PreprocessingResult | None; thresholding: ThresholdingResult | None; exporting: ExportingResult | None; massing: MassingResult | None; issues: tuple[Issue, ...]`. `_run_batches` keeps its signature, calls `report_progress(batches_done, len(batch_ranges))` after each batch and the active context's `raise_if_cancelled()` before each; in the threaded path each worker checks the event captured before submission (`active_context()` read on the calling thread) and the first `RunCancelled` is re-raised after the pool exits.

- [ ] **Step 1: Write the failing tests** in `tests/test_sequencer.py`:

```python
def test_produce_massing_skips_exporting(tmp_path):
    result = run_pipeline(daylight_cube_config(tmp_path), tmp_path / "run", produce={"massing"})
    assert result.exporting is None and result.massing.n_plates > 0
    assert not (tmp_path / "run" / "exporting").exists()

def test_start_from_thresholding_reuses_preprocessing(tmp_path):
    conf = daylight_cube_config(tmp_path)
    first = run_pipeline(conf, tmp_path / "run")
    again = run_pipeline(conf.model_copy(update={"carve_fraction": 0.5}), tmp_path / "run",
                         start_from="thresholding")
    assert again.preprocessing is None
    assert again.thresholding.upstream_run_id == first.preprocessing.run_id

def test_start_from_outside_the_path_is_refused(tmp_path):
    with pytest.raises(ValueError, match="start_from"):
        run_pipeline(daylight_cube_config(tmp_path), tmp_path / "run", produce={"preprocessing"},
                     start_from="massing")

def test_issues_of_all_stages_are_collected(tmp_path):
    conf = daylight_cube_config(tmp_path, threshold=1e9)            # nothing carved
    result = run_pipeline(conf, tmp_path / "run")
    assert ("thresholding", "nothing_carved") in [(i.stage, i.code) for i in result.issues]

def test_progress_reports_each_stage_and_batch(tmp_path):
    calls = []
    run_pipeline(daylight_cube_config(tmp_path, ray_batch_size=500), tmp_path / "run",
                 context=RunContext(on_progress=lambda s, d, t: calls.append((s, d, t))))
    assert {s for s, _, _ in calls} >= {"preprocessing", "thresholding", "exporting"}
    assert any(s == "preprocessing" and t > 1 for s, _, t in calls)

def test_cancel_between_stages(tmp_path):
    context = RunContext(on_progress=lambda s, d, t: context.cancel() if s == "thresholding" else None)
    with pytest.raises(RunCancelled):
        run_pipeline(daylight_cube_config(tmp_path), tmp_path / "run", context=context)
    assert not (tmp_path / "run" / "exporting" / "manifest.json").exists()

def test_cancel_stops_parallel_cpu_batches(tmp_path):
    # ray_batch_size small enough for several CPU batches; cancel on the first batch progress call
    context = RunContext(on_progress=lambda s, d, t: context.cancel() if (s, d) == ("preprocessing", 1) and t > 2 else None)
    with pytest.raises(RunCancelled):
        run_pipeline(daylight_cube_config(tmp_path, ray_batch_size=200), tmp_path / "run", context=context)
```

(`threshold=1e9` passes a numeric cutoff; `daylight_cube_config` forwards it.)
- [ ] **Step 2: Run; expect FAIL.**
- [ ] **Step 3: Implement.** Stage order and path from `PIPELINE_STAGES`; preprocessing and thresholding are on the path to every produced stage; `start_from` must be one of the stages on the path (else `ValueError`); starting later loads upstream manifests through `load_upstream(stage_folder(out_dir, upstream))`. The sequencer reports `report_progress(0, 1)` and `(1, 1)` around each stage and checks cancel between stages. Update `run_pipeline` callers to `result.exporting.export_path` (`test_run_pipeline_convenience`, `test_modes.py`, the daemon in Task 11 and the CLI `run` command in Task 12; for now adapt the CLI and daemon call sites minimally so the suite stays green).
- [ ] **Step 4: Run the full suite (background); expect PASS.**
- [ ] **Step 5: Commit** `feat(api): run_pipeline with produce and start_from; progress and cancel`.

### Task 11: Daemon `run` command, issues and error types in replies

**Files:**
- Modify: `src/urbansolarcarver/daemon.py`
- Test: `tests/test_daemon.py`

**Interfaces:**
- Consumes: Task 3 `build_config`/`load_config`; Task 9 `MODES[...].starting_values`, `canonical_mode_name`; Task 10 `run_pipeline`.
- Produces: command `run` with keys `produce` (list), `start_from` (str), `run_folder` (str), optional `config` (YAML path), optional `overrides` (list of `key=value` or mapping). Reply `{"status": "ok", "stage_folders": {stage: path}, "issues": [{"stage", "code", "message"}], ...}` plus the produced results' paths under today's names (`manifest` of the last stage, `export_path`, `plates_path`, `mesh_path`). Every reply of a stage command (old ones included) carries `issues`; error replies carry `error` (unchanged text), `error_type` (`type(exc).__name__`) and, for `ConfigError`, `config_errors: [{"field", "message"}]`. `_REQUIRED_KEYS["run"] = ("produce", "run_folder")`.

- [ ] **Step 1: Write the failing tests** in `tests/test_daemon.py`, calling `_dispatch(msg, sess)` as the existing tests do:

```python
def test_run_builds_the_config_from_starting_values_without_a_yaml(tmp_path, tmp_mesh_files):
    vol_path, srf_path = tmp_mesh_files
    overrides = [f"mode=daylight", f"max_volume_path={vol_path}", f"test_surface_path={srf_path}",
                 f"out_dir={tmp_path / 'run'}", "device=cpu", "voxel_size=2.0", "grid_step=2.0",
                 "ray_length=50.0"]
    with CarverSession(device="cpu") as sess:
        reply = _dispatch({"cmd": "run", "produce": ["thresholding"],
                           "run_folder": str(tmp_path / "run"), "overrides": overrides}, sess)
    assert reply["status"] == "ok"
    assert set(reply["stage_folders"]) == {"preprocessing", "thresholding"}

def test_run_without_yaml_requires_mode(tmp_path):
    with CarverSession(device="cpu") as sess:
        reply = _error_or_reply({"cmd": "run", "produce": ["preprocessing"],
                                 "run_folder": str(tmp_path)}, sess)
    assert reply["error_type"] == "ConfigError"
    assert [e["field"] for e in reply["config_errors"]] == ["mode"]

def test_stage_reply_carries_issues(tmp_path, tmp_mesh_files):
    # preprocessing then the old "thresholding" command with the override threshold=1e9
    ...
    assert [i["code"] for i in reply["issues"]] == ["nothing_carved"]
```

Build the third test's YAML as `test_voxel_grid_cache_survives_between_commands` does. `_error_or_reply(msg, sess)` is a test helper that calls `_dispatch` and, on exception, returns `daemon._error_reply(exc)`, mirroring `serve`.
- [ ] **Step 2: Run; expect FAIL.**
- [ ] **Step 3: Implement.** Without `config`, the base values are `canonical_mode_name(overrides["mode"])`'s starting values merged under the overrides, built with `build_config` (missing `mode` raises `ConfigError([ConfigFieldError("mode", "required when no config file is given")])`). Each stage command runs inside `run_context(RunContext())` and builds the config inside it, so config issues are included. Old stage commands keep calling the public stage functions with `from` and `out_dir` as today (see "Deviations").
- [ ] **Step 4: Run the full suite (background); expect PASS.**
- [ ] **Step 5: Commit** `feat(daemon): run command, issues and error types in replies, config from starting values`.

### Task 12: CLI on the new contract

**Files:**
- Modify: `src/urbansolarcarver/carver_cli.py`, `src/urbansolarcarver/grid_planning.py` (gains `estimate_grid_memory`), `api_core/_reporting.py` (loses it)
- Test: `tests/test_cli.py`, `tests/test_util.py` (`TestEstimateGridMemory` import path)

**Interfaces:**
- Consumes: Tasks 3, 6, 9, 10, 11.
- Produces: `usc run` gains `--produce` (repeatable, default `exporting`) and `--start-from` (default `preprocessing`), local and `--daemon` (sends `run`); stage commands print issues after their result; an `UrbanSolarCarverError` prints `Error: <message>` in red and exits 1 (other exceptions keep their traceback); `_find_manifest` uses `stage_folder`; `--dry-run` imports `estimate_grid_memory` from `grid_planning` (which loads the mesh with trimesh inside the function, keeping the module numpy-only at import); the `archetype` command reads `archetype_defaults`.

- [ ] **Step 1: Write the failing tests** in `tests/test_cli.py` with typer's `CliRunner`: `run --produce massing` writes `massing/plates.json` and no `exporting/`; a config with `voxel_size: 0` exits 1 with `Error:` and no traceback; `thresholding` with a nothing-carved threshold prints `nothing_carved`.
- [ ] **Step 2: Run; expect FAIL.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the fast suite; expect PASS.**
- [ ] **Step 5: Commit** `feat(cli): produce/start-from on run, issues printed, clean errors`.

### Task 13: Grasshopper on the new contract

**Files:**
- Modify: `grasshopper/usc_gh.py`; components `USC_Config.py`, `USC_Mode.py`, `USC_Archetype.py`, `USC_Preprocess.py`, `USC_ThresholdStage.py`, `USC_Export.py`, `USC_Massing.py`, `USC_RunPipeline.py`; rebuilt `.ghuser` files under `grasshopper/USC_GHplugin/`
- Test: `tests/test_usc_gh.py`, `tests/test_gh_components.py`

**Interfaces:**
- Consumes: Task 9 light modules; Task 11 `run` command and reply fields.
- Produces in `usc_gh.py`: `engine_module(root, name)` (loads `<root>/src/urbansolarcarver/<name>.py` by path, cached and reloaded on mtime change like `_usc_gh`); `show_issues(component, reply) -> list[str]` (adds each issue as a Warning runtime message `"<stage>: <message>"`, returns the lines); `run_stages(session, config, produce, start_from, extra_overrides) -> dict` (sends `run` with `run_folder=config.out_dir`, `config=config.yaml_path` only when set, and the merged overrides). Components read stage folders from `reply["stage_folders"]`. `USCConfig.yaml_path` may be None (no YAML given). USC_Mode lists `list(MODES)` and descriptions from `mode_registry`; USC_Config uses `canonical_mode_name`; USC_Archetype uses `archetype_defaults`.

- [ ] **Step 1: Write the failing tests** in `tests/test_usc_gh.py` (it already loads `usc_gh.py` without Rhino): `engine_module(root, "mode_registry").MODES` has the six modes; `show_issues` on a fake component (an object recording `AddRuntimeMessage` calls; stub `Grasshopper.Kernel` in `sys.modules` as the existing tests do, or make `show_issues` take the level enum lazily so the stub works) records one warning per issue; `run_stages` sends `cmd="run"` and omits `config` when `yaml_path` is None (patch `call_daemon`).
- [ ] **Step 2: Run; expect FAIL.**
- [ ] **Step 3: Implement** `usc_gh.py`, then the components: each stage component replaces its `call_daemon(..., "<stage>", {...})` with `run_stages(...)`, uses `reply["stage_folders"][stage]` for `read_diagnostics`, and calls `show_issues`. USC_Config drops `_mode_default_yaml` and `_mode_canonical`. Rebuild with `python grasshopper/build_ghuser.py` (needs `pip install -e .[ghbuild]` and Rhino 8's `GH_IO.dll`); if the build cannot run on this machine, stop and ask the owner. `python grasshopper/build_ghuser.py --check` must exit 0.
- [ ] **Step 4: Run the fast suite; expect PASS.** Manual check in Rhino is the owner's: list it in the task report.
- [ ] **Step 5: Commit** `feat(gh): stage components use the run command, show engine issues, read engine facts`.

### Task 14: Documentation, changelog, final verification

**Files:**
- Modify: `CHANGELOG.md`, `docs/api/pipeline.md`, `docs/api/cli.md`, `docs/getting-started/configuration.md`, `docs/project-map.md`, `docs/grasshopper.md`
- Test: none new

- [ ] **Step 1: Document** each change of spec S11 (migration) and the new public names (`build_config`, `run_pipeline(produce, start_from, context)`, `PipelineResult`, `stages_to_rerun`, `RunContext`, `report_issue`, the four exceptions, `run_id`, `footprint.json`, the daemon `run` command). One CHANGELOG section "Changed (stage contract)" under Unreleased; keep the phase 1 entries consistent with run IDs.
- [ ] **Step 2: Run the full suite (background); expect PASS**, and `python grasshopper/build_ghuser.py --check` exit 0.
- [ ] **Step 3: Commit** `docs: stage contract restructure`.
