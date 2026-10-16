"""Load a YAML config, apply overrides, and validate it into a ``user_config``.

Overrides come from the CLI (``key=value`` strings), the daemon, or
Grasshopper. :func:`build_config` validates already-typed values (no YAML
involved) and raises a structured :class:`~urbansolarcarver.errors.ConfigError`.
The schema itself lives in :mod:`pydantic_schemas`.
"""

import json
import math
import os
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Union

import yaml
from pydantic import ValidationError

from .errors import ConfigError, ConfigFieldError
from .errors import UrbanSolarCarverWarning  # noqa: F401 (re-exported)
from .mode_registry import MODES, canonical_mode_name
from .pydantic_schemas import UserConfig as user_config
from .pydantic_schemas import expand_analysis_period

# Config fields holding file or folder paths. Relative values in a YAML file
# are resolved against the YAML's own folder, so a config means the same
# thing whichever directory the CLI, the daemon or Grasshopper runs from.
PATH_FIELDS = ("max_volume_path", "test_surface_path", "epw_path", "out_dir",
               "simulated_weights_path")


def parse_override_value(raw: str) -> Any:
    """Convert a ``key=value`` override's value into a Python value.

    "true"/"false" become bool and "null"/"none" None (case-insensitive);
    JSON lists and objects are parsed (``[45,40,35]``), then int, then float;
    anything else stays a string. "inf" and "nan" stay strings so the schema
    reports them clearly.

    >>> parse_override_value("true")
    True
    >>> parse_override_value("3.5")
    3.5
    >>> parse_override_value("foofoo")
    'foofoo'
    """
    lowered = raw.lower()
    if lowered in {"true", "false"}:
        return lowered == "true"
    if lowered in {"null", "none"}:
        return None
    stripped = raw.strip()
    if (stripped.startswith("[") and stripped.endswith("]")) or (
            stripped.startswith("{") and stripped.endswith("}")):
        try:
            return json.loads(stripped)
        except ValueError:
            pass
    try:
        return int(raw)
    except ValueError:
        pass
    try:
        value = float(raw)
        if math.isfinite(value):
            return value
    except ValueError:
        pass
    return raw


def _wrap_value_error(exc: ValueError) -> ConfigError:
    return ConfigError(str(exc), [ConfigFieldError(None, str(exc))])


def parse_overrides(overrides: Union[List[str], Mapping[str, Any]]) -> Dict[str, Any]:
    """The settings named by *overrides*: ``key=value`` strings or a mapping.

    String values are parsed by :func:`parse_override_value`.  An
    ``analysis_period`` mapping is expanded into the six flat period fields,
    so the result can replace the values of a YAML file or of a mode's
    starting values field by field.

    Raises
    ------
    ConfigError
        For an item without ``=`` or an ``analysis_period`` that is not a
        valid period (``errors`` holds one entry whose field is None).
    """
    try:
        if isinstance(overrides, Mapping):
            return dict(expand_analysis_period(dict(overrides)))
        parsed = {}
        for item in overrides:
            if "=" not in item:
                raise ValueError(f"Invalid override '{item}', expecting key=value")
            key, val = item.split("=", 1)
            parsed[key.strip()] = parse_override_value(val.strip())
        return dict(expand_analysis_period(parsed))
    except ValueError as exc:
        raise _wrap_value_error(exc) from exc


def _resolve_path_fields(data: Dict[str, Any], base_folder: Path) -> None:
    """Make the relative path settings in *data* absolute against *base_folder*."""
    for key in PATH_FIELDS:
        value = data.get(key)
        if isinstance(value, str) and value and not os.path.isabs(value):
            data[key] = str(base_folder / value)


def build_config(
    values: Mapping[str, Any],
    base_folder: Optional[Union[Path, str]] = None,
) -> user_config:
    """Validate *values* into a ``user_config``.

    Parameters
    ----------
    values : Mapping[str, Any]
        Config settings by name, already typed (what a YAML file or a client
        such as Grasshopper holds). An ``analysis_period`` mapping is expanded
        into the six flat period fields.
    base_folder : Path | str | None
        When given, relative values of the path settings (meshes, EPW,
        out_dir, simulated weights) are resolved against it; otherwise they
        are kept as written.

    Raises
    ------
    ConfigError
        On any invalid value. ``errors`` lists each problem with the field it
        concerns (``None`` for checks that involve several fields).
    """
    try:
        data = dict(expand_analysis_period(dict(values)))
    except ValueError as exc:
        raise _wrap_value_error(exc) from exc
    if base_folder is not None:
        _resolve_path_fields(data, Path(base_folder))
    try:
        return user_config(**data)
    except ValidationError as exc:
        field_errors = []
        lines = []
        for err in exc.errors():
            loc = ".".join(map(str, err.get("loc", ())))
            msg = err.get("msg", "")
            field_errors.append(ConfigFieldError(loc or None, msg))
            lines.append(f"{loc}: {msg}" if loc else msg)
        raise ConfigError(
            "Configuration validation error:\n  " + "\n  ".join(lines), field_errors
        ) from exc


def build_config_from_mode_starting_values(
    values: Mapping[str, Any],
    base_folder: Optional[Union[Path, str]] = None,
) -> user_config:
    """Validate *values* on top of the starting values of the mode they name.

    This is how a client without a YAML file gets a complete config: the
    mode's ``starting_values`` (see :mod:`mode_registry`) fill every setting
    *values* leaves out, and every setting *values* gives wins.  The mode
    name may be an alias (``tilted-plane``).  An ``analysis_period`` mapping
    in *values* is expanded first, so it replaces the starting period field
    by field.  *base_folder* resolves relative paths as in
    :func:`build_config`.

    Raises
    ------
    ConfigError
        When *values* has no ``mode`` (the error is on field ``mode``), and
        for every problem :func:`build_config` reports, an unknown mode
        included.
    """
    given = parse_overrides(values)
    if given.get("mode") is None:
        message = "mode: required to choose the starting values"
        raise ConfigError(message, [ConfigFieldError("mode", "required to choose the starting values")])
    mode_name = canonical_mode_name(given["mode"])
    if mode_name not in MODES:
        return build_config(given, base_folder)  # the schema reports the unknown mode
    return build_config({**MODES[mode_name].starting_values, **given, "mode": mode_name}, base_folder)


def load_config(
    path: str,
    overrides: Optional[Union[List[str], Mapping[str, Any]]] = None,
) -> user_config:
    """Load the YAML at *path*, apply *overrides*, and validate.

    Parameters
    ----------
    path : str
        YAML config file. Relative paths inside it (meshes, EPW, out_dir,
        simulated weights) are resolved against the file's folder.
    overrides : list[str] | Mapping[str, Any] | None
        Top-level config keys that replace the YAML's values: ``"key=value"``
        strings (values parsed by :func:`parse_override_value`) or a mapping.
        They win over the YAML, including over its ``analysis_period`` block.
        Relative paths in overrides are left as given (relative to the
        current directory).

    Raises
    ------
    FileNotFoundError
        If *path* does not exist.
    ConfigError
        On malformed YAML, an override string without ``=``, or invalid
        values (a ``ValueError`` listing all validation errors in one
        message).
    """
    if not os.path.isfile(path):
        raise FileNotFoundError(
            f"Configuration file not found at {path!r}. "
            "Please check the file path and try again."
        )
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f)
    except yaml.YAMLError as exc:
        message = f"Malformed YAML in {path!r}: {exc}"
        raise ConfigError(message, [ConfigFieldError(None, message)]) from exc
    if raw is None:
        raw = {}
    elif not isinstance(raw, dict):
        message = f"Expected a YAML mapping at the top level, got {type(raw).__name__}"
        raise ConfigError(message, [ConfigFieldError(None, message)])
    try:
        data = dict(expand_analysis_period(raw))
        # The YAML's own period block is expanded before the overrides are
        # applied, so that flat start_*/end_* overrides replace it.
        _resolve_path_fields(data, Path(path).resolve().parent)
    except ValueError as exc:
        raise _wrap_value_error(exc) from exc
    if overrides:
        data.update(parse_overrides(overrides))
    return build_config(data)
