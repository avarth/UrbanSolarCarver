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
• Overrides: dotted keys supported (e.g. "thresholding.carve_fraction=0.7")  
• Clear errors: aggregates Pydantic messages into one readable string  
• Sample writer: exports a ready-to-edit template with sane defaults

This module does not touch geometry. It only prepares inputs for the
carving and meshing stages.
"""

import os
import yaml
from typing import Optional, List, Tuple, Any, Dict, Mapping, Union
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
    # JSON-like list? e.g. "[45,40,35,30,25,30,35,40]"
    stripped = raw.strip()
    if stripped.startswith("[") and stripped.endswith("]"):
        import json
        try:
            return json.loads(stripped)
        except (json.JSONDecodeError, ValueError):
            pass
    # int or float?
    try:
        if "." in raw:
            return float(raw)
        return int(raw)
    except ValueError:
        return raw  # keep as string

def assign_override_path(root: Dict[str, Any], path: Tuple[str, ...], value: Any) -> None:
    """
    Set a nested key in-place using a path tuple.

    Parameters
    ----------
    root : dict
        Target dictionary to mutate.
    path : tuple[str, ...]
        Dotted key split into parts, e.g. ("thresholding","carve_fraction").
    value : Any
        Value to assign at the nested location.

    Notes
    -----
    Creates intermediate dictionaries as needed.
    """
    if not path:
        raise ValueError("Override path must not be empty")
    cur = root
    for key in path[:-1]:
        if key not in cur or not isinstance(cur[key], dict):
            cur[key] = {}
        cur = cur[key]
    cur[path[-1]] = value

def merge_dicts(base: Dict[str, Any],
                update: Dict[str, Any]) -> None:
    """
    Recursively overlay `update` onto `base` in place.

    Rules
    -----
    • If both sides are dicts, merge recursively.  
    • Otherwise replace the value in `base` with the one from `update`.
    """
    for k, v in update.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            merge_dicts(base[k], v)        # type: ignore[index]
        else:
            base[k] = v

def _flatten_overrides_dict(d: Mapping[str, Any], prefix: Tuple[str, ...] = ()) -> List[Tuple[Tuple[str, ...], Any]]:
    """
    Convert a nested mapping into [(path_tuple, value), ...] pairs.

    Each `path_tuple` represents a dotted key path, e.g.
    ('thresholding', 'carve_fraction').
    """
    items: List[Tuple[Tuple[str, ...], Any]] = []
    for k, v in d.items():
        p = (*prefix, k)
        if isinstance(v, Mapping):
            items.extend(_flatten_overrides_dict(v, p))
        else:
            items.append((p, v))
    return items


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
        Optional overrides.  
        • list[str]: each item is "key=value" with dotted keys allowed  
        • mapping  : nested dict mirroring YAML structure

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
    • Dotted keys in overrides are expanded via `assign_override_path`.  
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

        # Apply overrides (list[str] "k=v" or Mapping[str, Any]) before validation
        if overrides:
            update: Dict[str, Any] = {}
            if isinstance(overrides, Mapping):
                for path_tuple, value in _flatten_overrides_dict(overrides):
                    assign_override_path(update, path_tuple, value)
            else:
                for item in overrides:
                    if "=" not in item:
                        raise ValueError(f"Invalid override '{item}', expecting key=value")
                    key, val = item.split("=", 1)
                    path_tuple = tuple(k for k in key.strip().split(".") if k)
                    assign_override_path(update, path_tuple, parse_override_value(val.strip()))
            merge_dicts(data, update)

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

