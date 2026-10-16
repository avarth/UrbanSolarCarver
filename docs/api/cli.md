# CLI

Command-line interface built with Typer, installed as `urbansolarcarver` and its short alias `usc`. Provides the same 3-stage pipeline as the Python API, plus daemon management, config validation and introspection, and the simulated-weights tools.

```bash
# Run the whole pipeline
urbansolarcarver run -c config.yaml

# Produce the floor plates too, or reuse the scores and re-threshold
urbansolarcarver run -c config.yaml --produce exporting --produce massing
urbansolarcarver run -c config.yaml --start-from thresholding -o carve_fraction=0.5

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

`run` takes `--produce` (repeatable; `preprocessing`, `thresholding`, `exporting` or `massing`; default `exporting`) and runs the stages those need. `--start-from` (default `preprocessing`) skips the stages before it and reads their output from `<out>/<stage>`. Both work with `--daemon`, which sends the daemon's `run` command.

Issues noticed during a command (settings the mode ignores, nothing carved, ...) print after the result under `Issues:` as `stage: code: message`. A package error (an invalid config, an unusable input file, a missing or stale upstream output) prints `Error: <message>` and exits with 1, without a traceback.

::: urbansolarcarver.carver_cli
