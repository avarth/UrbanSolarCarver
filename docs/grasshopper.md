# Grasshopper Plugin (Rhino 3D)

USC provides 25 custom Grasshopper components for visual parametric workflows in Rhino.

## Installation

Copy all `.ghuser` files from `grasshopper/USC_GHplugin/` to your Grasshopper User Objects folder, or drag them onto the Grasshopper canvas. Requires Rhino 8 (the components are Python 3 script components).

## Updating components on existing canvases

Components already placed on a canvas keep the code they were placed with. After installing new `.ghuser` files, drop **USC_SyncCanvas** (ribbon: *Session*) on the canvas:

1. Leave `update` unconnected and read `report`: it lists which USC components are up to date and which would change. Components whose code you edited by hand count as outdated and would be overwritten.
2. Connect a Button to `update` and click it. Components whose inputs and outputs are unchanged are replaced in place, keeping position, wires, internalised values (*Set One String*), graft/flatten/simplify settings, enabled/preview state and group membership. Components whose inputs or outputs changed are placed beside the old one inside a red group that names the new or removed ports: rewire the new component, then delete the old one and the group.
3. The whole update is one undo step (Ctrl+Z). If anything fails mid-update, the canvas is rolled back and the error appears in `report`.

By default the updates come from the installed user objects (Grasshopper's User Objects folders); wire a folder path into `folder` to update from elsewhere, e.g. `grasshopper/USC_GHplugin` in a checkout.

## Rebuilding the components

The `.ghuser` files are generated from the sources in `grasshopper/components/`; edit the `.py`, never the `.ghuser`. Each source declares its own ports: names and descriptions in its "GH UI" block, order and types in the numpydoc `Inputs` / `Outputs` docstring. `grasshopper/components.json` holds the ribbon subcategory and the stable user-object GUID; icons are `grasshopper/icons/<source name>.png` (24x24).

Code shared by several components (daemon calls, the `run` command wrapper `run_stages`, engine issues shown as warnings by `show_issues`, loading the engine's `mode_registry.py` and `archetype_defaults.py` by path with `engine_module`, PLY reading and writing, mesh conversion, override parsing) lives in `grasshopper/usc_gh.py`. The components load it at run time from `<carver_root>/grasshopper/`, where `carver_root` is the repository folder given to USC_Session, so editing it takes effect on the next solve without rebuilding any `.ghuser`. It uses only the standard library, RhinoCommon and the Grasshopper SDK, because the component scripts run in Rhino's own Python, not in the USC environment.

```bash
pip install -e .[ghbuild]                       # pythonnet
python grasshopper/build_ghuser.py              # rebuild into USC_GHplugin/
python grasshopper/build_ghuser.py --check      # exit 1 if any .ghuser is stale
```

The builder uses `GH_IO.dll` from the Rhino 8 install (`--ghio <folder>` to point elsewhere); Rhino does not need to be running. Rebuilds are byte-for-byte reproducible, so an unchanged source leaves its `.ghuser` untouched. `tests/test_gh_components.py` checks that every source's UI block matches its docstring and that every docstring type maps to a Grasshopper type hint.

A component already placed on a saved canvas keeps the code it was placed with; USC_SyncCanvas updates it (see above).

## Daemon

The components send their work to a persistent daemon process that keeps the CUDA context and compiled kernels loaded, so repeated runs skip the start-up cost:

```bash
urbansolarcarver daemon start       # start GPU daemon
# ... use Grasshopper components ...
urbansolarcarver daemon stop        # stop when done
```

The daemon binds to localhost only. Clients authenticate with a random key that the daemon generates on first start and stores in `~/.urbansolarcarver/.daemon_authkey`.

## Components

The ribbon shows each component as `USC <Name>` (for example *USC Session*). Below they are listed by their source file name in `grasshopper/components/`, grouped by ribbon tab.

**Session** (`0::Session`)

- **USC_Session**: finds the USC Python environment and starts or checks the daemon. Wire a Boolean `True` to `start_daemon` to launch the daemon; when the input is unconnected or `False`, the component only reports whether a daemon is running.
- **USC_SyncCanvas**: updates the USC components on the canvas to the installed versions (see [Updating components on existing canvases](#updating-components-on-existing-canvases))

**Configuration** (`1::Config`)

- **USC_Config**: builds a pipeline configuration from a mode, an EPW path, an output folder, an optional base YAML and the override strings of the parameter components below. With no YAML, the daemon starts from the mode's starting values (for example the analysis period of the benefit, irradiance and time-based modes) and applies the overrides; `configs/` is not read. Spellings such as `time_based` or `tilted-plane` are accepted.
- **USC_Mode**: selects the carving mode by number and outputs its name for USC_Config's `mode` input. The mode list and descriptions come from the engine (`mode_registry.py`), so solve USC_Session first; without it the component shows a message that says so.
- **USC_EPW** (*USC EPW Path*): passes the EPW file path
- **USC_AnalysisPeriod**: defines the analysis date/time range
- **USC_GridSettings**: voxel size, surface sampling spacing (`grid_step`), grid padding (`margin_frac`)
- **USC_RaySettings**: ray length, minimum sun altitude, north direction (`north_deg`)
- **USC_BenefitParams**: benefit-mode hour weighting: balance temperature and offset (simple weights), or a `simulated_weights.json` artifact plus the experimental `include_harm` toggle (simulated weights)
- **USC_TiltedPlane**: fixed-angle envelope parameters
- **USC_RadCooling** (*USC Radiative Cooling*): radiative cooling parameters (dew point, Bliss constant)
- **USC_Threshold**: thresholding strategy, score smoothing, column carve-above post-processing, and the slope limit (`max_slope`; empty = 75 degrees for the weighted modes, 90 = off). Connect its output to **USC_ThresholdStage**'s `threshold_overrides` input (not Config) so threshold changes only re-run thresholding.
- **USC_Postprocess**: smoothing and cleanup settings. Connect its output to **USC_Export**'s `postprocess_overrides` input (not Config) so mesh cleanup changes only re-run export.
- **USC_Diagnostics**: detailed score statistics and diagnostic plot images

**Pipeline execution** (`2::Main`)

- **USC_RunPipeline**: runs all three stages in one go (quick prototyping)
- **USC_Preprocess**: runs preprocessing only (ray tracing + scoring). Errors turn the component red.

The stage components send the daemon's `run` command, each producing its own stage, and read the stage folders from the reply. A stage reads the output of the stage before it from `<out_dir>/<stage>` of its Config, so Preprocess and the stages after it need the same Config `out_dir`; the `pre_result` and `thr_result` inputs order the solve and still have to be connected. Conditions the engine reports (a setting the mode ignores, nothing carved, a footprint that could not be read, ...) appear as warnings on the component, one per issue, as `<stage>: <message>`. Re-running preprocessing makes the stages after it refuse their old output until they run again (the error names the stage to re-run).

- **USC_ThresholdStage**: runs thresholding only. Accepts `threshold_overrides` directly. Its summary shows the slope limit (angle, voxels removed, share of the obstruction score). Errors turn the component red.
- **USC_Export**: runs exporting only. Accepts `postprocess_overrides` directly. Errors turn the component red.
- **USC_Massing**: stage 4, builds floor plates from the carving mask (inputs `config`, `thr_result`, `massing_overrides`, `run`; outputs closed Breps, floor areas per floor and in total, and the `plates.json` path). See [Floor-plate massing](massing.md).
- **USC_MassingSettings**: floor heights, bay width, tolerance and stacking for USC_Massing. Connect its output to USC_Massing's `massing_overrides` input so changes re-run only massing.

**Simulated weights** (`3::Weights`)

- **USC_Archetype**: assembles a typical building for the simulated weights from the five parameter families below; every input is optional (neutral defaults, read from the engine's `archetype_defaults.py`, so solve USC_Session first)
- **USC_ZoneGeometry / USC_ZoneFabric / USC_ZoneVent / USC_ZoneOperation / USC_ZoneShading**: Honeybee-style family feeders for USC_Archetype: shoebox dimensions + per-facade window-to-wall ratio, envelope U-values + g-value + mass class, air-change rates + heat recovery, setpoints + internal gains, and declared shading coefficients. Each family is one wire into USC_Archetype.
- **USC_SimulateWeights**: runs the ISO 13790 5R1C simulation through the daemon; outputs the `simulated_weights.json` path (wire into USC_BenefitParams) and a heatmap preview image

## Input geometry

Test surfaces must be **individual flat panels**. If you are using extruded block boundaries or any joined polysurface, explode it into its faces before connecting it to USC_Preprocess. Otherwise the planarity check rejects the combined surface and preprocessing fails with a "No points sampled" error.

## Recommended workflow

Use the **decomposed pipeline** (Preprocess → ThresholdStage → Export as separate components) rather than RunPipeline. This lets you:

- Adjust **threshold** parameters (USC_Threshold → USC_ThresholdStage) and re-export without re-running the expensive ray-tracing step.
- Adjust **mesh cleanup** settings (USC_PostProcess → USC_Export) and regenerate the mesh without re-thresholding or re-preprocessing.

Only USC_Preprocess needs to re-run when you change geometry, mode, or the analysis period.
