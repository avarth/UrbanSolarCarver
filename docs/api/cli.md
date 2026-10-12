# CLI

Command-line interface built with Typer. Provides the same 3-stage pipeline as the Python API, plus daemon management and config introspection.

```bash
# Run pipeline stages
urbansolarcarver preprocessing -c config.yaml
urbansolarcarver thresholding  -c config.yaml -f outputs/preprocessing/manifest.json
urbansolarcarver exporting     -c config.yaml -f outputs/thresholding/manifest.json

# Override any config value on the fly
urbansolarcarver preprocessing -c config.yaml -o voxel_size=0.5 -o mode=irradiance

# Build and validate a building archetype (prints derived areas)
urbansolarcarver archetype -o my_building.yaml -s width=12 -s wwr_south=0.4 -s mass_class=heavy

# Generate simulated benefit weights (writes simulated_weights.json + .png preview)
urbansolarcarver simulate-weights -e weather.epw -a my_building.yaml

# Inspect the full config schema
urbansolarcarver schema

# Daemon lifecycle
urbansolarcarver daemon start
urbansolarcarver daemon stop
```

::: urbansolarcarver.carver_cli
