# Configuration

USC uses YAML files for all pipeline parameters. The configuration system provides:

- **YAML loading** of a flat mapping of settings; an `analysis_period:` mapping with Ladybug `AnalysisPeriod.to_dict()` keys is expanded into the six period fields. Relative paths are resolved against the YAML file's folder.
- **Overrides** (`-o key=value` on the CLI, or a mapping in Python) that replace top-level values from the file.
- **Pydantic v2 validation** with value ranges, type coercion, rejection of unknown keys, and one error message listing every problem.
- **Manifest schemas** for the preprocessing and thresholding stages, so a later stage can be re-run from an earlier run's output.

See also: [Configuration guide](../getting-started/configuration.md) for the user-facing parameter reference.

## Config loader

::: urbansolarcarver.load_config

## Schemas

::: urbansolarcarver.pydantic_schemas
