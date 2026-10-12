# Grasshopper Plugin (Rhino 3D)

USC provides 24 custom Grasshopper components for visual parametric workflows in Rhino.

## Installation

Copy all `.ghuser` files from `grasshopper/USC_GHplugin/` to your Grasshopper User Objects folder, or drag them onto the Grasshopper canvas.

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
