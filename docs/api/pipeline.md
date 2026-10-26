# Pipeline

USC runs in three stages: preprocessing, thresholding, exporting, with massing as an optional fourth that reads the thresholding output like exporting. Each stage writes a manifest, last, after all its other outputs; the next stage reads it, so you can re-run thresholding with different parameters without recomputing scores. Every manifest has a random `run_id`, new on every run of its stage, and every manifest after preprocessing records the `run_id` of the manifest it was built from (`upstream_run_id`); a stage refuses an upstream that was re-run since (`StageChainError`). Manifests store paths relative to their own folder, so a run folder can be moved or copied. A stage first deletes the manifest and the outputs of its previous run in its folder, so a failed run leaves no manifest.

`run_pipeline()` runs the stages needed for what you ask it to produce, in one call. For finer control, call each stage individually.

```python
from urbansolarcarver import load_config, run_pipeline

# One-shot: preprocessing, thresholding, exporting
result = run_pipeline(load_config("config.yaml"), out_dir="outputs")
print(result.exporting.export_path)

# Decomposed
from urbansolarcarver import preprocessing, thresholding, exporting
from pathlib import Path

cfg = load_config("config.yaml")
pre  = preprocessing(cfg, Path("outputs/preprocessing"))
thr  = thresholding(pre, cfg, Path("outputs/thresholding"))
exp  = exporting(thr, cfg, Path("outputs/exporting"))
```

## run_pipeline

`run_pipeline(config, out_dir, produce=("exporting",), start_from="preprocessing", context=None, after=None)` runs `start_from` and every later stage on the path to the stages in `produce`. Each stage writes into `<out_dir>/<stage>`; a stage before `start_from` is not run, and the next stage reads its output from its folder in `out_dir`.

```python
# Floor plates as well as the mesh: preprocessing and thresholding run once
result = run_pipeline(cfg, "outputs", produce=["exporting", "massing"])
print(result.exporting.export_path, result.massing.plates_path)

# Change a threshold setting and reuse the scores already in outputs/preprocessing
cfg = load_config("config.yaml", ["carve_fraction=0.5"])
result = run_pipeline(cfg, "outputs", start_from="thresholding")
assert result.preprocessing is None   # it did not run in this call
```

The `PipelineResult` has one attribute per stage (`preprocessing`, `thresholding`, `exporting`, `massing`): the Result of a stage that ran in this call, None for the others. Its `issues` are the conditions noticed during the call (see [Issues and run context](#issues-and-run-context)). A `start_from` stage that is not on the path to a produced stage raises `ValueError`; a missing or stale upstream output raises `StageChainError`. `after` is given to the thresholding stage as its `after` (see [Thresholding](#thresholding)).

::: urbansolarcarver.api
    options:
      members: [run_pipeline, PipelineResult]

## run_chain

`run_chain(chain, out_dir=None, produce=("exporting",), start_from="preprocessing", context=None, trace=None, threshold_from=None)` runs the criteria of a chain file in order on one voxel grid, then exporting and massing from the last (see [Criteria](../criteria.md)). *chain* is a path or a `ChainConfig` from `load_chain`. Each criterion's stages write to `<out_dir>/criteria/<id>/<stage>`, and a criterion's thresholding takes the previous criterion's as `after`. It returns a `ChainResult`: one `PipelineResult` per criterion in `criteria`, then `exporting`, `massing` and the `issues` of the call. With `trace` (ids of criteria), only those criteria run preprocessing again and the others read their existing preprocessing folder; every criterion from the first traced one on is thresholded again. With `threshold_from` (an id of the chain), thresholding starts at the earlier of that criterion and the first traced one; the earlier criterion's preprocessing is read as it is.

::: urbansolarcarver.api_core.chain
    options:
      members: [run_chain, ChainResult]

## Deciding what to re-run

`stages_to_rerun(previous_config, new_config, produce)` lists, in pipeline order, the stages that have to run to bring `produce` up to date after a config change. It compares the settings each stage reads (preprocessing, then thresholding, then each produced leaf stage) and does not look at input files or at which stages exist on disk; that is for the caller to decide. With no previous config it lists every stage `produce` needs.

::: urbansolarcarver.stage_settings
    options:
      members: [stages_to_rerun, stage_folder]

## Issues and run context

Conditions that are not errors (settings the mode ignores, nothing carved, a footprint that could not be read, ...) are reported as issues: an `Issue` has the `stage` it was noticed in, a short `code` and a `message`. Each stage Result has `issues`, and `PipelineResult.issues` holds those of the whole call. Without a run context the engine also emits each issue as a warning.

A `RunContext` passed to `run_pipeline` collects the issues, calls `on_progress(stage, done, total)` as a stage advances, and stops the run when `cancel()` is called (`RunCancelled`; stages that finished keep their output). `report_issue(code, message)` records an issue on the active context.

```python
from urbansolarcarver.run_context import RunContext

context = RunContext(on_progress=lambda stage, done, total: print(stage, done, total))
result = run_pipeline(cfg, "outputs", context=context)
for issue in result.issues:
    print(issue.stage, issue.code, issue.message)
```

::: urbansolarcarver.run_context
    options:
      members: [RunContext, Issue, report_issue, report_progress, run_context]

## Errors

Errors raised on purpose derive from `UrbanSolarCarverError`. `ConfigError`, `InputError` and `StageChainError` are also `ValueError`.

| Error | Raised when |
|-------|-------------|
| `ConfigError` | A config is invalid. `errors` lists a `ConfigFieldError(field, message)` per problem (`field` is None for checks that involve several fields). |
| `InputError` | An input file or input data is missing or unusable: a mesh or EPW file, an empty voxel grid, no sample points. |
| `StageChainError` | A stage's upstream output is missing, unreadable or from another run: the message names the stage to re-run. |
| `RunCancelled` | The run context was cancelled. |

::: urbansolarcarver.errors

## Preprocessing

Voxelizes the max volume, samples the test surfaces, generates rays toward sky patches (or sun positions, or the tilted-plane direction), traces them through the voxel grid, and writes per-voxel obstruction scores to `scores.npy`.

::: urbansolarcarver.api_core.preprocessing
    options:
      members: [preprocessing, PreprocessingResult]

## Thresholding

Converts the score array into a binary carving mask: optional score smoothing, then `carve_fraction`, head/tail breaks, or a numeric cutoff over the occupied voxels, with `carve_above` applied through `column_postprocessing.carve_above_scores` (the cutoff at which carve_above removes each voxel, so that `carve_fraction` counts what carve_above removes), then the slope limit (`max_slope_deg`, 75 degrees for the weighted modes; `column_postprocessing.limit_column_slope`). Writes `mask.npy` and `scores_compared_with_cutoff.npy` (float32, the grid shape: the values the cutoff is applied to before the slope limit, which are the `carve_above` removal cutoffs when `carve_above` is on and the smoothed scores otherwise); the diagnostics record `max_slope_deg`, `slope_limit_extra_voxels_removed` and `obstruction_fraction_carved_by_slope_limit`.

With `after=` (the previous criterion's `ThresholdingResult`, thresholding folder or `manifest.json`), the stage decides only among the voxels the previous criterion kept and never keeps a voxel it removed. The manifest records `after_manifest` and `after_run_id`, the diagnostics record `voxels_at_start`, and a previous criterion on another grid, one re-run since, or the previous criterion's own output folder as `out_dir` raises `StageChainError`.

::: urbansolarcarver.api_core.thresholding
    options:
      members: [thresholding, ThresholdingResult]

## Exporting

Reconstructs a triangle mesh from the binary mask, either as cubic voxel faces or as SDF-smoothed marching cubes with Taubin polishing. Writes `export.<format>` (`ply` by default, set by `final_mesh_format`), `manifest.json` and diagnostics, and the run's `run_report.md`. The report has a Massing section too when the run's massing folder was built from the same thresholding run.

::: urbansolarcarver.api_core.exporting
    options:
      members: [exporting, ExportingResult]

## Massing

Builds stacked floor plates that follow the footprint from the carving mask (see [Floor-plate massing](../massing.md)). Writes `plates.json`, `plates.obj`, the same plates as `plates.<format>` when `final_mesh_format` is not `obj`, `manifest.json` and diagnostics, and adds a Massing section to the run report. Returns a `MassingResult` with the paths, the floor areas per floor and in total, and the number of plates. The geometry is in `urbansolarcarver.floor_plates`.

::: urbansolarcarver.api_core.massing
    options:
      members: [massing, MassingResult]
