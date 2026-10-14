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

Code shared by several components (daemon calls, PLY reading and writing, mesh conversion, override parsing) lives in `grasshopper/usc_gh.py`. The components load it at run time from `<carver_root>/grasshopper/`, where `carver_root` is the repository folder given to USC_Session, so editing it takes effect on the next solve without rebuilding any `.ghuser`. It uses only the standard library, RhinoCommon and the Grasshopper SDK, because the component scripts run in Rhino's own Python, not in the USC environment.

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

- **USC_Config**: builds a pipeline configuration from a mode, an EPW path, an output folder, an optional base YAML and the override strings of the parameter components below
- **USC_Mode**: selects the carving mode by number and outputs its name for USC_Config's `mode` input
- **USC_EPW** (*USC EPW Path*): passes the EPW file path
- **USC_AnalysisPeriod**: defines the analysis date/time range
- **USC_GridSettings**: voxel size, surface sampling spacing (`grid_step`), grid padding (`margin_frac`)
- **USC_RaySettings**: ray length, minimum sun altitude, north direction (`north_deg`)
- **USC_BenefitParams**: benefit-mode hour weighting: balance temperature and offset (simple weights), or a `simulated_weights.json` artifact plus the experimental `include_harm` toggle (simulated weights)
- **USC_TiltedPlane**: fixed-angle envelope parameters
- **USC_RadCooling** (*USC Radiative Cooling*): radiative cooling parameters (dew point, Bliss constant)
- **USC_Threshold**: how much to carve, plus the column clean-up. For the sky modes connect only `value`: the share (0-1) of the sky blocked by the maximum volume that the test surfaces get back (`recovered_sky`; 0.4 = they get back 40% of what the maximum volume takes). For `time-based`, set `method` to `numeric` and `value` to the tolerated shading in m²·h. `method` accepts `recovered_sky` (the default when it is unconnected), `carve_fraction`, `protect_share`, `headtail` and `numeric`; with `carve_fraction` or `protect_share`, `value` is that method's value. `max_slope` sets the slope limit for the score-cutoff methods (`carve_fraction`, `headtail`, `numeric`; empty = 75°, 90 = off), and `score_smoothing` also applies only to them. Connect its output to **USC_ThresholdStage**'s `threshold_overrides` input (not Config) so threshold changes only re-run thresholding.
- **USC_Postprocess**: smoothing and cleanup settings. Connect its output to **USC_Export**'s `postprocess_overrides` input (not Config) so mesh cleanup changes only re-run export.
- **USC_Diagnostics**: detailed score statistics and diagnostic plot images

**Pipeline execution** (`2::Main`)

- **USC_RunPipeline**: runs all three stages in one go (quick prototyping)
- **USC_Preprocess**: runs preprocessing only (ray tracing + scoring). Errors turn the component red.
- **USC_ThresholdStage**: runs thresholding only. Accepts `threshold_overrides` directly. With `recovered_sky`, its summary shows the share of the blocked sky actually recovered (`recovered_sky_actual`); with `protect_share`, the number of protected sky patches and the share of the patch weight they hold. Errors turn the component red.
- **USC_Export**: runs exporting only. Accepts `postprocess_overrides` directly. Errors turn the component red.

**Simulated weights** (`3::Weights`)

- **USC_Archetype**: assembles a typical building for the simulated weights from the five parameter families below; every input is optional (neutral defaults)
- **USC_ZoneGeometry / USC_ZoneFabric / USC_ZoneVent / USC_ZoneOperation / USC_ZoneShading**: Honeybee-style family feeders for USC_Archetype: shoebox dimensions + per-facade window-to-wall ratio, envelope U-values + g-value + mass class, air-change rates + heat recovery, setpoints + internal gains, and declared shading coefficients. Each family is one wire into USC_Archetype.
- **USC_SimulateWeights**: runs the ISO 13790 5R1C simulation through the daemon; outputs the `simulated_weights.json` path (wire into USC_BenefitParams) and a heatmap preview image

## Input geometry

Test surfaces must be **individual flat panels**. If you are using extruded block boundaries or any joined polysurface, explode it into its faces before connecting it to USC_Preprocess. Otherwise the planarity check rejects the combined surface and preprocessing fails with a "No points sampled" error.

## Recommended workflow

Use the **decomposed pipeline** (Preprocess → ThresholdStage → Export as separate components) rather than RunPipeline. This lets you:

- Adjust **threshold** parameters (USC_Threshold → USC_ThresholdStage) and re-export without re-running the expensive ray-tracing step.
- Adjust **mesh cleanup** settings (USC_PostProcess → USC_Export) and regenerate the mesh without re-thresholding or re-preprocessing.

Only USC_Preprocess needs to re-run when you change geometry, mode, or the analysis period.
