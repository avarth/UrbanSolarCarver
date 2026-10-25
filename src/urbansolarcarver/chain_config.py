"""The ``criteria:`` form of a config: several criteria carved in sequence on one voxel grid.

A chain file sets the shared settings once at the top level (meshes, voxel size, weather file, output folder,
exporting and massing) and lists the settings of each criterion under ``criteria:`` (mode, test surface, how the
voxels are decided, the mode's own parameters, its analysis period). :func:`load_chain` turns it into one validated
``user_config`` per criterion, so everything downstream reads ordinary configs.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Union

from .errors import ConfigError, ConfigFieldError
from .load_config import (
    _resolve_path_fields, _wrap_value_error, build_config, parse_overrides, read_yaml_mapping, user_config,
)
from .mode_registry import MODES, canonical_mode_name
from .pydantic_schemas import _MODE_SPECIFIC_FIELDS, UserConfig, expand_analysis_period
from .stage_settings import ThresholdingSettings

# The settings one criterion decides. Everything else in the config is shared by the whole chain and is set at the
# top level. The weather file is mode specific but shared: one file serves every criterion that reads it.
CRITERION_KEYS = frozenset(
    {"name", "id", "mode", "test_surface_path"}
    | set(ThresholdingSettings.model_fields)
    | (_MODE_SPECIFIC_FIELDS - {"epw_path"})
    | {"edge_taper"}
)

_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,40}$")


@dataclass(frozen=True)
class Criterion:
    """One criterion of a chain: its id (also its folder name), its display name and its validated config."""
    id: str
    name: str
    config: user_config


@dataclass(frozen=True)
class ChainConfig:
    """A chain of criteria. ``shared`` is the last criterion's config: exporting and massing read their settings from
    it, and those are all shared keys, equal in every criterion."""
    criteria: tuple[Criterion, ...]
    shared: user_config


def is_chain_file(path: str) -> bool:
    """Whether the YAML at *path* is a mapping with a ``criteria`` key. A missing or malformed file is not a chain
    file; loading it reports the problem."""
    try:
        return "criteria" in read_yaml_mapping(path)
    except (FileNotFoundError, ConfigError):
        return False


def _fail(message: str, field: Optional[str] = None) -> ConfigError:
    return ConfigError(message, [ConfigFieldError(field, message)])


def _checked_criteria(raw: Any) -> List[Dict[str, Any]]:
    if not isinstance(raw, list) or not raw:
        raise _fail("criteria must be a non-empty list of mappings, one per criterion", "criteria")
    for position, item in enumerate(raw, start=1):
        if not isinstance(item, dict):
            raise _fail(f"criteria: criterion {position} must be a mapping of settings, got {type(item).__name__}", "criteria")
    return [dict(item) for item in raw]


def _criterion_id(position: int, item: Mapping[str, Any]) -> str:
    given = item.get("id")
    value = str(position) if given is None else str(given)
    if not _ID_PATTERN.match(value):
        raise _fail(f"criterion {position}: id {value!r} must be 1 to 40 letters, digits, '_' or '-' "
                    "(it names the criterion's output folder)", "id")
    return value


def _criterion_name(item: Mapping[str, Any]) -> str:
    given = item.get("name")
    return str(given) if given is not None else canonical_mode_name(item.get("mode") or "time-based")


def load_chain(
    path: str,
    overrides: Optional[Union[List[str], Mapping[str, Any]]] = None,
) -> ChainConfig:
    """Load the chain file at *path*, apply *overrides*, and validate each criterion.

    Parameters
    ----------
    path : str
        YAML file with a ``criteria:`` list. Relative paths in it (top level and criteria) are resolved against the
        file's folder.
    overrides : list[str] | Mapping[str, Any] | None
        Top-level settings that replace the YAML's: ``"key=value"`` strings or a mapping, as for
        :func:`~urbansolarcarver.load_config.load_config`. Shared settings only: a criterion setting in the overrides
        is refused.

    Each criterion's config is the shared settings plus its own, without the weather file when its mode does not read
    one. A criterion's ``id`` (default: its position from 1) names its output folder; its ``name`` (default: its mode)
    is for display.

    Raises
    ------
    FileNotFoundError
        If *path* does not exist.
    ConfigError
        On malformed YAML, a file without ``criteria``, a shared setting inside a criterion, a criterion setting at the
        top level, a missing or repeated id, or an invalid criterion (the message starts ``criterion <id> (<name>): ``).
    """
    raw = read_yaml_mapping(path)
    if "criteria" not in raw:
        raise _fail(f"{path} has no criteria: list; load it with load_config()", "criteria")
    criteria = _checked_criteria(raw["criteria"])
    top = {key: value for key, value in raw.items() if key != "criteria"}
    base_folder = Path(path).resolve().parent
    try:
        top = dict(expand_analysis_period(top))
    except ValueError as exc:
        raise _wrap_value_error(exc) from exc
    _resolve_path_fields(top, base_folder)
    if overrides:
        top.update(parse_overrides(overrides))
    for position, item in enumerate(criteria, start=1):
        try:
            criteria[position - 1] = dict(expand_analysis_period(item))
        except ValueError as exc:
            raise _fail(f"criterion {position}: {exc}", "analysis_period") from exc
        _resolve_path_fields(criteria[position - 1], base_folder)

    misplaced = sorted(set(top) & CRITERION_KEYS)
    if misplaced:
        raise _fail(f"{', '.join(misplaced)}: a criterion setting; with criteria: present, set it inside a criterion, "
                    f"not at the top level", misplaced[0])

    ids = [_criterion_id(position, item) for position, item in enumerate(criteria, start=1)]
    first_use: Dict[str, int] = {}  # by lower-cased id: the id names a folder, and Windows and macOS ignore case there
    for position, value in enumerate(ids, start=1):
        earlier = first_use.setdefault(value.casefold(), position)
        if earlier != position:
            raise _fail(f"criterion {position}: id {value!r} is the same as the id {ids[earlier - 1]!r} of criterion "
                        f"{earlier}, ignoring case (the id names the criterion's output folder)", "id")

    built = []
    for item, criterion_id in zip(criteria, ids):
        label = f"criterion {criterion_id} ({_criterion_name(item)}): "
        shared_inside = sorted(key for key in item if key in UserConfig.model_fields and key not in CRITERION_KEYS)
        if shared_inside:
            raise _fail(f"{label}{', '.join(shared_inside)}: shared by every criterion; set it once at the top level",
                        shared_inside[0])
        settings = {**top, **{key: value for key, value in item.items() if key not in ("name", "id")}}
        spec = MODES.get(canonical_mode_name(settings.get("mode") or "time-based"))
        if spec is not None and not spec.needs_epw:
            settings.pop("epw_path", None)
        try:
            config = build_config(settings)
        except ConfigError as exc:
            raise ConfigError(f"{label}{exc}", exc.errors) from exc
        built.append(Criterion(criterion_id, _criterion_name(item), config))
    return ChainConfig(tuple(built), built[-1].config)
