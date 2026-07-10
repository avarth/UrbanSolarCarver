"""
UrbanSolarCarver — Configuration loading and validation

Purpose
-------
Read a YAML config, apply optional overrides from CLI or dicts, validate
everything with Pydantic, and hand the pipeline a typed `user_config`.
Also emits a human-readable sample YAML.

Highlights
----------
• Strict schema: fails fast on typos or bad values
• Overrides: flat "key=value" pairs or a flat mapping (the schema itself is flat)
• Clear errors: aggregates Pydantic messages into one readable string
• Sample writer: exports a ready-to-edit template with sane defaults

This module does not touch geometry. It only prepares inputs for the
carving and meshing stages.
"""

import math
import os
import yaml
from typing import Optional, List, Any, Dict, Mapping, Union
from pydantic import ValidationError
from .pydantic_schemas import UserConfig as user_config
from .pydantic_schemas import UrbanSolarCarverWarning  # noqa: F401 (re-exported)


# --- utility functions for parsing overrides, merging configs and exporting default config.YAML ---
   
def parse_override_value(raw: str) -> Any:
    """
    Convert a CLI override scalar into a Python type.

    Accepted literals
    -----------------
    • "true"/"false" → bool
    • "null"/"none"  → None
    • ints and floats (simple forms)
    • everything else stays as a string

    Examples
    --------
    >>> parse_override_value("true")  # bool
    True
    >>> parse_override_value("3.5")   # float
    3.5
    >>> parse_override_value("foofoo")   # str
    'foofoo'
    """
    lowered = raw.lower()
    if lowered in {"true", "false"}:
        return lowered == "true"
    if lowered in {"null", "none"}:
        return None
    # JSON-like list or object? e.g. "[45,40,35]" or '{"method":"headtail"}'
    stripped = raw.strip()
    if (stripped.startswith("[") and stripped.endswith("]")) or (
            stripped.startswith("{") and stripped.endswith("}")):
        import json
        try:
            return json.loads(stripped)
        except (json.JSONDecodeError, ValueError):
            pass
    # int, then float (also covers scientific notation like "1e-3").
    try:
        return int(raw)
    except ValueError:
        pass
    try:
        value = float(raw)
        # Reject inf/nan spellings ("inf", "nan"): as config values they are
        # almost certainly typos, so keep them as strings and let the schema
        # produce a clear validation error.
        if math.isfinite(value):
            return value
    except ValueError:
        pass
    return raw  # keep as string

# --- Load and validate YAML config via Pydantic. Exits on validation errors ---
def load_config(
    path: str,
    overrides: Optional[Union[List[str], Mapping[str, Any]]] = None
) -> user_config:
    """
    Load a YAML config, apply overrides, and return a validated `user_config`.

    Parameters
    ----------
    path : str
        Path to the YAML file.
    overrides : list[str] | Mapping[str, Any] | None
        Optional overrides for top-level config keys (the schema is flat).
        • list[str]: each item is "key=value"; scalars are type-coerced,
          JSON lists/objects are parsed (e.g. "tilted_plane_angle_deg=[30,27,...]")
        • mapping  : flat dict of key → value, used as-is

    Returns
    -------
    user_config

    Raises
    ------
    FileNotFoundError
        If `path` does not exist.
    ValueError
        If validation fails. The error message aggregates all Pydantic errors.

    Notes
    -----
    • Scalars in CLI overrides are type-coerced by `parse_override_value`.
    • The function does not mutate the YAML on disk.
    """
    if not os.path.isfile(path):
        # Fail loudly with a clear Python exception
        raise FileNotFoundError(
            f"Configuration file not found at {path!r}. "
            "Please check the file path and try again."
        )
    try:
        # ensure we read the YAML as UTF-8 to avoid platform-specific codecs
        with open(path, 'r', encoding='utf-8') as f:
            raw = yaml.safe_load(f)
        if raw is None:
            data: Dict[str, Any] = {}
        elif not isinstance(raw, dict):
            raise ValueError(
                f"Expected a YAML mapping at the top level, got {type(raw).__name__}"
            )
        else:
            data = raw

        # Apply overrides (list[str] "k=v" or flat Mapping) before validation.
        # The schema is flat, so overrides address top-level keys directly;
        # unknown keys are rejected by validation (extra='forbid').
        if overrides:
            if isinstance(overrides, Mapping):
                data.update(overrides)
            else:
                for item in overrides:
                    if "=" not in item:
                        raise ValueError(f"Invalid override '{item}', expecting key=value")
                    key, val = item.split("=", 1)
                    data[key.strip()] = parse_override_value(val.strip())

        # Now validate
        return user_config(**data)
    
    except yaml.YAMLError as exc:
        raise ValueError(
            f"Malformed YAML in {path!r}: {exc}"
        ) from exc
    except ValidationError as exc:
        # Aggregate Pydantic errors into a single message
        lines = []
        for err in exc.errors():
            loc = ".".join(map(str, err.get("loc", ())))
            msg = err.get("msg", "")
            lines.append(f"{loc}: {msg}" if loc else msg)
        raise ValueError(
            "Configuration validation error:\n  " + "\n  ".join(lines)
        ) from exc

