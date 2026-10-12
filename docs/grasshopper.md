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

```bash
pip install -e .[ghbuild]                       # pythonnet
python grasshopper/build_ghuser.py              # rebuild into USC_GHplugin/
python grasshopper/build_ghuser.py --check      # exit 1 if any .ghuser is stale
```

The builder uses `GH_IO.dll` from the Rhino 8 install (`--ghio <folder>` to point elsewhere); Rhino does not need to be running. Rebuilds are byte-for-byte reproducible, so an unchanged source leaves its `.ghuser` untouched. `tests/test_gh_components.py` checks that every source's UI block matches its docstring and that every docstring type maps to a Grasshopper type hint.

A component already placed on a saved canvas keeps the code it was placed with; USC_SyncCanvas updates it (see above).

## Daemon

The plugin communicates with a persistent daemon process that keeps the CUDA context warm for sub-second response times:

```bash
urbansolarcarver daemon start       # start GPU daemon
# ... use Grasshopper components ...
urbansolarcarver daemon stop        # stop when done
```

The daemon binds to localhost only and uses a random authkey for authentication.

## Components

All components are prefixed with `USC_`:

**Session management**

- **USC_Session**  -- daemon lifecycle and CUDA initialization. Wire a Boolean `True` to the `start_daemon` input to launch the daemon; leaving it unconnected keeps the component idle.
- **USC_SyncCanvas**  -- update the USC components on the canvas to the installed versions (see [Updating components on existing canvases](#updating-components-on-existing-canvases))

**Configuration (Tier 1)**

- **USC_Config**  -- build a pipeline configuration from visual parameters
- **USC_AnalysisPeriod**  -- define the analysis date/time range
- **USC_GridSettings**  -- voxel size, ray length, surface sampling
- **USC_RaySettings**  -- ray batch size, altitude limits
- **USC_BenefitParams**  -- benefit-mode hour weighting: balance temperature and offset (simple weights), or a `simulated_weights.json` artifact plus the experimental `include_harm` toggle (simulated weights)
- **USC_Archetype**  -- assemble a typical building for the simulated weights from the five parameter families below; every input optional (neutral defaults)
- **USC_ZoneGeometry / USC_ZoneFabric / USC_ZoneVentilation / USC_ZoneOperation / USC_ZoneShading**  -- Honeybee-style family feeders for USC_Archetype: shoebox dimensions + per-facade WWR, envelope U-values + g-value + mass class, air-change rates + heat recovery, setpoints + internal gains, and declared shading coefficients. Each family is one wire into USC_Archetype.
- **USC_SimulateWeights**  -- run the ISO 13790 5R1C simulation through the daemon; outputs the `simulated_weights.json` path (wire into USC_BenefitParams) and a heatmap preview image
- **USC_TiltedPlane**  -- fixed-angle envelope parameters
- **USC_RadCool**  -- radiative cooling parameters (dew point, Bliss constant)
- **USC_Threshold**  -- thresholding strategy, score smoothing, and column carve-above post-processing. Connect output to **USC_ThresholdStage**'s `threshold_overrides` input (not Config) so threshold changes only re-run thresholding.
- **USC_PostProcess**  -- smoothing and cleanup settings. Connect output to **USC_Export**'s `postprocess_overrides` input (not Config) so mesh cleanup changes only re-run export.
- **USC_Diagnostics**  -- enable/disable diagnostic exports

**Pipeline execution (Tier 2)**

- **USC_RunPipeline**  -- run all three stages in one go (quick prototyping)
- **USC_Preprocess**  -- run preprocessing only (ray tracing + scoring). Errors turn the component red.
- **USC_ThresholdStage**  -- run thresholding only. Accepts `threshold_overrides` directly. Errors turn the component red.
- **USC_Export**  -- run exporting only. Accepts `postprocess_overrides` directly. Errors turn the component red.

## Input geometry

Test surfaces must be **individual flat panels**. If you are using extruded block boundaries or any joined polysurface, explode it into its constituent faces before connecting to USC_Preprocess  -- otherwise the planarity check will reject the combined surface and preprocessing will fail with a "No points sampled" error.

## Recommended workflow

Use the **decomposed pipeline** (Preprocess → ThresholdStage → Export as separate components) rather than RunPipeline. This lets you:

- Adjust **threshold** parameters (USC_Threshold → USC_ThresholdStage) and re-export without re-running the expensive ray-tracing step.
- Adjust **mesh cleanup** settings (USC_PostProcess → USC_Export) and regenerate the mesh without re-thresholding or re-preprocessing.

Only USC_Preprocess needs to re-run when you change geometry, mode, or the analysis period.
