# CLI

Command-line interface built with Typer, installed as `urbansolarcarver` and its short alias `usc`. Provides the same 3-stage pipeline as the Python API, plus daemon management, config validation and introspection, and the simulated-weights tools.

```bash
# Run the whole pipeline
urbansolarcarver run -c config.yaml

# Run pipeline stages
urbansolarcarver preprocessing -c config.yaml
urbansolarcarver thresholding  -c config.yaml -f outputs/preprocessing/manifest.json
urbansolarcarver exporting     -c config.yaml -f outputs/thresholding/manifest.json

# Override any config value on the fly
urbansolarcarver preprocessing -c config.yaml -o voxel_size=0.5 -o mode=irradiance

# Check a config without running anything
urbansolarcarver validate -c config.yaml

# Build and validate a building archetype (prints derived areas)
urbansolarcarver archetype -o my_building.yaml -s width=12 -s wwr_south=0.4 -s mass_class=heavy

# Generate simulated benefit weights (writes simulated_weights.json + .png preview)
urbansolarcarver simulate-weights -e weather.epw -a my_building.yaml

# List the config parameters (optionally --mode benefit or --search threshold)
urbansolarcarver schema

# Precompile the Warp kernels
urbansolarcarver warmup

# Daemon lifecycle
urbansolarcarver daemon start
urbansolarcarver daemon status
urbansolarcarver daemon stop
```

Without `-f`, `thresholding` and `exporting` look for the previous stage's `manifest.json` under the config's `out_dir`.

::: urbansolarcarver.carver_cli
