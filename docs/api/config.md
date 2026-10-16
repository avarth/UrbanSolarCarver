# Configuration

USC uses YAML files for all pipeline parameters. The configuration system provides:

- **Typed values** through `build_config`, for clients that hold values rather than a file (Grasshopper through the daemon).
- **YAML loading** of a flat mapping of settings; an `analysis_period:` mapping with Ladybug `AnalysisPeriod.to_dict()` keys is expanded into the six period fields. Relative paths are resolved against the YAML file's folder.
- **Overrides** (`-o key=value` on the CLI, or a mapping in Python) that replace top-level values from the file.
- **Pydantic v2 validation** with value ranges, type coercion, rejection of unknown keys, and one error message listing every problem. Both entry points raise `ConfigError`, whose `errors` list gives the field and message of each problem.
- **Manifest schemas** for the preprocessing and thresholding stages, so a later stage can be re-run from an earlier run's output.

See also: [Configuration guide](../getting-started/configuration.md) for the user-facing parameter reference.

## Config loader

::: urbansolarcarver.load_config

::: urbansolarcarver.build_config

## Mode starting values

`mode_registry.MODES` holds one `ModeSpec` per carving mode. Its `starting_values` are the settings that differ from the schema defaults and fill a new config for the mode: the analysis period of `time-based`, `irradiance` and `benefit`, `tilted_plane_angle_deg: 45` for `tilted_plane` and `carve_fraction: 0.35` for `radiative_cooling`. A client with no YAML file (Grasshopper through the daemon's `run` command) gets its config from these values plus its overrides. The schema defaults and validation rules are unchanged, so a CLI config without `carve_fraction` keeps 0.7 in every mode and `time-based` still requires an analysis period. The files in `configs/` repeat the starting values as commented examples. `ModeSpec.description` is the text the Grasshopper mode component shows, `MODE_ALIASES` lists the accepted spellings (`time_based`, `tilted-plane`, ...) and `canonical_mode_name(name)` maps a name to the canonical one.

## Schemas

::: urbansolarcarver.pydantic_schemas
