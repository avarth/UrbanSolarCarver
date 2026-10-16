"""Stage folders and manifests: the one place that knows the run-folder layout,
how a stage starts and finishes, and how a stage reads its upstream.

A run folder holds one subfolder per stage (``<run>/preprocessing``, ...).
Each stage

* starts with :func:`begin_stage`, which deletes the outputs of an earlier
  run of that stage;
* writes the paths in its manifest with :func:`stored_path` (relative to the
  manifest's folder, so a run folder can be moved or copied);
* ends with :func:`commit_manifest`, so a run that fails midway leaves no
  manifest.

A downstream stage reads its upstream with :func:`load_upstream`, which also
checks that the upstream is the run the downstream manifest was built from.
"""
from __future__ import annotations

import os
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Union

from pydantic import BaseModel

from ..errors import StageChainError
from ..pydantic_schemas import (
    ExportingManifest, MassingManifest, PreprocessingManifest, ThresholdingManifest,
    schema_from_json, schema_to_json,
)
from ..stage_settings import stage_folder  # noqa: F401 (the run-folder layout, re-exported)

MANIFEST_NAME = "manifest.json"

_MANIFEST_CLASSES = {
    "preprocessing": PreprocessingManifest,
    "thresholding": ThresholdingManifest,
    "exporting": ExportingManifest,
    "massing": MassingManifest,
}

# The stage whose manifest each downstream manifest names as its upstream.
_UPSTREAM_STAGE = {
    "thresholding": "preprocessing",
    "exporting": "thresholding",
    "massing": "thresholding",
}


def new_run_id() -> str:
    """A random identifier for one run of a stage."""
    return uuid.uuid4().hex


def begin_stage(out_dir: Union[Path, str], output_names: Iterable[str]) -> Path:
    """Create the stage folder and delete the outputs of an earlier run in it.

    *output_names* are the paths, relative to *out_dir*, that the stage
    writes (diagnostics included).  The manifest goes first and each stage
    writes it last, so a run that fails midway leaves no manifest, and an
    output the new run does not write (another mesh format, a plot that is
    now off) does not survive beside the new ones.  Only these names are
    deleted; other files in the folder are left alone.  Returns the folder.
    """
    if out_dir is None:
        raise ValueError("An explicit out_dir must be provided for a stage")
    folder = Path(out_dir)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / MANIFEST_NAME).unlink(missing_ok=True)
    for name in output_names:
        (folder / name).unlink(missing_ok=True)
    return folder


def commit_manifest(folder: Path, manifest: BaseModel) -> None:
    """Write *manifest* as ``manifest.json`` in *folder*; a stage does this last."""
    (Path(folder) / MANIFEST_NAME).write_text(schema_to_json(manifest), encoding="utf-8")


def stored_path(path: Union[Path, str], manifest_folder: Union[Path, str]) -> str:
    """The text a manifest stores for *path*: relative to *manifest_folder*
    with forward slashes, or the absolute path when no relative path exists
    (another drive on Windows)."""
    try:
        return Path(os.path.relpath(path, manifest_folder)).as_posix()
    except ValueError:
        return Path(os.path.abspath(path)).as_posix()


@dataclass(frozen=True)
class LoadedManifest:
    """A parsed manifest with the folder it lives in."""
    manifest: BaseModel
    folder: Path
    manifest_path: Path

    def resolve(self, relative_path: str) -> Path:
        """The file a stored path points at (absolute paths are returned as they are)."""
        path = Path(relative_path)
        return path if path.is_absolute() else Path(os.path.normpath(self.folder / path))


def _manifest_path_of(source) -> Path:
    """The ``manifest.json`` that *source* (a Result, a folder or a manifest path) names."""
    manifest_path = getattr(source, "manifest_path", None)
    if manifest_path is not None:
        return Path(manifest_path)
    out_dir = getattr(source, "out_dir", None)
    if out_dir is not None:
        return Path(out_dir) / MANIFEST_NAME
    path = Path(os.fspath(source))
    return path / MANIFEST_NAME if path.is_dir() else path


def load_upstream(source, expected_stage: str) -> LoadedManifest:
    """Read the manifest of *expected_stage* that *source* names.

    *source* is a stage Result, a stage folder or a ``manifest.json`` path.
    For a downstream manifest, the upstream manifest it names is read as
    well, and its ``run_id`` must equal the ``upstream_run_id`` recorded in
    the downstream one: otherwise the upstream stage was re-run since, and
    its new outputs do not belong to this run.

    Raises :class:`StageChainError`, naming the stage to re-run, when a
    manifest is missing or unreadable (a manifest written by an older
    version has no ``run_id``) or the run IDs differ.
    """
    manifest_path = _manifest_path_of(source)
    try:
        manifest = schema_from_json(
            _MANIFEST_CLASSES[expected_stage], manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise StageChainError(
            f"Unable to read a {expected_stage} manifest at {manifest_path} (it is missing, "
            f"damaged, or written by an older version); re-run {expected_stage}."
        ) from exc
    loaded = LoadedManifest(manifest, manifest_path.parent, manifest_path)
    upstream_stage = _UPSTREAM_STAGE.get(expected_stage)
    if upstream_stage is not None:
        upstream = load_upstream(loaded.resolve(manifest.upstream_manifest), upstream_stage)
        if upstream.manifest.run_id != manifest.upstream_run_id:
            raise StageChainError(
                f"The {upstream_stage} output at {upstream.manifest_path} is not the run that "
                f"the {expected_stage} output at {manifest_path} was built from (it has been "
                f"re-run since). Re-run the stages after {upstream_stage}."
            )
    return loaded
