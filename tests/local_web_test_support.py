"""Fakes and helpers that several tests of the local web service share (tests/test_local_web_*.py).

The engine is replaced by a fake that writes a manifest with a new run_id (and the current upstream run_id) for each stage it
runs, as the real stages do; the run folders of finished runs are written without computing anything. The fixture
``project_with_inputs`` is in conftest.py and builds its project with ``add_project_with_inputs``.
"""
import json
import os
import shutil
import subprocess
import sys
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pytest
import trimesh

from urbansolarcarver.io import load_mesh, save_mesh
from urbansolarcarver.local_web_service.example_catalog import read_examples
from urbansolarcarver.local_web_service.projects import INPUTS_FOLDER, JOINED_FOLDER, ProjectStore
from urbansolarcarver.local_web_service.run_worker import RunWorker
from urbansolarcarver.local_web_service.stage_records import UPSTREAM_STAGE
from urbansolarcarver.pydantic_schemas import ExportingManifest, PreprocessingManifest, ThresholdSpec, ThresholdingManifest, schema_to_json
from urbansolarcarver.run_context import report_issue, report_progress, run_context, stage_context
from urbansolarcarver.stage_settings import PIPELINE_STAGES, stages_needed_for

GOLDEN_EPW = Path(__file__).resolve().parent.parent / "examples" / "weather" / "USA_CO_Golden-NREL.724666_TMY3.epw"
ALL_CURRENT = {stage: "current" for stage in PIPELINE_STAGES}
ALL_MISSING = {stage: "missing" for stage in PIPELINE_STAGES}


# ---- Projects ----

class FakeRecycleBin:
    """Stands in for ``send2trash.send2trash``: records the folders it was given and removes them, as moving them away does.

    ``error`` (an exception) makes every call fail instead, leaving the folder where it is.
    """

    def __init__(self, error: Exception | None = None):
        self.folders: list[Path] = []
        self.error = error

    def __call__(self, folder) -> None:
        if self.error is not None:
            raise self.error
        self.folders.append(Path(folder))
        shutil.rmtree(folder)


def make_link_to_folder(link: Path, target: Path, kind: str) -> None:
    """A junction or a symbolic link at *link* to the folder *target*; the test is skipped where the kind cannot be made."""
    if kind == "junction":
        if sys.platform != "win32":
            pytest.skip("junctions exist on Windows only")
        subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)], check=True, capture_output=True)
        return
    try:
        os.symlink(target, link, target_is_directory=True)
    except OSError as error:
        pytest.skip(f"a symbolic link cannot be made here: {error}")


def box_bytes(center, extents=(10, 10, 10)) -> bytes:
    box = trimesh.creation.box(extents=extents)
    box.apply_translation(center)
    return box.export(file_type="ply")


def add_project_with_inputs(tmp_path: Path) -> tuple[ProjectStore, str]:
    """A daylight project (no weather file needed) with a max volume and a test surface: the store and the project name."""
    store = ProjectStore(tmp_path / "projects")
    store.create("p", "daylight")
    store.add_input("p", "max_volume", "volume.ply", box_bytes([0, 0, 5]))
    store.add_input("p", "test_surfaces", "surface.ply", box_bytes([0, 0, 0], extents=(6, 6, 0.1)))
    return store, "p"


class ExampleProjectTemplates:
    """Each packaged example made into a project once, then copied for every test that needs a project made from it.

    The template is made by ``ProjectStore.create_example_project``, as the route POST /projects/{name}/examples/{example}
    makes it (the files are read by the route's own helper). Making one joins its test surfaces (0.3-0.8 s); a copy takes
    about 0.01 s. A copy gets new file times and project.json gets its name and creation time, as a project just made.
    Tests of making an example project still call create_example_project or the route.
    """

    def __init__(self, templates_folder: Path):
        self._templates = ProjectStore(templates_folder)

    def copy_example_project(self, store: ProjectStore, project_name: str, example_name: str):
        """The project *project_name* in *store*, made from the example *example_name*; returns the example."""
        from urbansolarcarver.local_web_service.server import _example_input_files
        example = next(candidate for candidate in read_examples() if candidate.name == example_name)
        template_folder = self._templates.projects_folder / example_name
        if not template_folder.is_dir():
            self._templates.create_example_project(example_name, example, _example_input_files(example))
        project_folder = store.projects_folder / project_name
        shutil.copytree(template_folder, project_folder, copy_function=shutil.copy)     # shutil.copy gives new file times
        template_json = self._templates.read_project_json(example_name)
        created = datetime.now(timezone.utc).isoformat(timespec="seconds")
        store.write_project_json(project_name, template_json.model_copy(update={"name": project_name, "created": created}))
        return example


def change_settings(store: ProjectStore, name: str, **changes) -> None:
    store.write_config_from_values(name, {**store.read_settings(name), **changes})


def write_joined_test_surfaces_without_normals(store: ProjectStore, name: str) -> Path:
    """The joined test surface file as the service wrote it before it kept vertex normals: positions only; its path."""
    project_folder = store.open(name)
    file_names = sorted(store.read_project_json(name).input_files["test_surfaces"])
    meshes = [load_mesh(str(project_folder / INPUTS_FOLDER / "test_surfaces" / file_name)) for file_name in file_names]
    joined_path = project_folder / JOINED_FOLDER / "test_surfaces.ply"
    save_mesh(trimesh.util.concatenate(meshes), str(joined_path))
    assert not has_vertex_normals(joined_path)
    return joined_path


def has_vertex_normals(ply_path: Path) -> bool:
    """Whether the header of a PLY file declares the vertex property nx."""
    header_lines = ply_path.read_bytes().split(b"end_header", 1)[0].splitlines()
    return any(line.split()[-1:] == [b"nx"] for line in header_lines if line.startswith(b"property"))


# ---- The fake engine and the run worker ----

def write_fake_stage_output(run_folder: Path, stage: str) -> None:
    """What a finished stage leaves: a manifest with a new run_id and, for a stage that reads one, the upstream run_id."""
    folder = run_folder / stage
    folder.mkdir(parents=True, exist_ok=True)
    manifest = {"run_id": uuid.uuid4().hex}
    if stage == "preprocessing":
        manifest.update(max_volume_lowest_z=0.0, max_volume_highest_z=10.0)
    if stage in UPSTREAM_STAGE:
        manifest["upstream_run_id"] = json.loads((run_folder / UPSTREAM_STAGE[stage] / "manifest.json").read_text())["run_id"]
    (folder / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    if stage == "exporting":
        (folder / "export.ply").write_bytes(b"ply")
    if stage == "massing":
        (folder / "plates.json").write_text("{}", encoding="utf-8")
        (folder / "plates.obj").write_text("", encoding="utf-8")
        (run_folder / "run_report.md").write_text("report", encoding="utf-8")


def stages_the_engine_runs(request) -> list[str]:
    path = stages_needed_for(request.produce)
    return path[path.index(request.start_from):]


class FakeEngine:
    """Stands in for ``handle_engine_request``; keeps the requests it received."""

    def __init__(self):
        self.requests = []

    def __call__(self, request, session, context):
        self.requests.append(request)
        with run_context(context):
            for stage in stages_the_engine_runs(request):
                with stage_context(stage):
                    report_progress(0, 1)
                    context.raise_if_cancelled()
                    if stage == "preprocessing":
                        report_issue("fake_issue", "preprocessing noticed something")
                    write_fake_stage_output(Path(request.run_folder), stage)
                    report_progress(1, 1)


class FakeSession:
    def __init__(self, device="cpu"):
        self.device = device

    def release_memory(self):
        pass


class WaitsForCancel:
    """A handler that starts, then waits until the run is cancelled; ``started`` is set once it runs."""

    def __init__(self):
        self.started = threading.Event()

    def __call__(self, request, session, context):
        self.started.set()
        assert context.cancel_event.wait(10), "the run was never cancelled"
        context.raise_if_cancelled()


def make_worker(store, handle_request=None, device="cpu") -> RunWorker:
    return RunWorker(store, device, handle_request=handle_request or FakeEngine(), session_factory=FakeSession)


def wait_until_finished(worker: RunWorker, run_id: str, deadline_seconds: float = 20.0) -> list[dict]:
    """All events of a run once it has finished; fails the test when the run does not finish within the deadline."""
    state = worker.run_state(run_id)
    deadline = time.monotonic() + deadline_seconds
    seen = 0
    while not state.finished:
        assert time.monotonic() < deadline, f"the run did not finish within {deadline_seconds} seconds"
        seen += len(state.wait_for_events(seen, 0.2))
    return list(state.events)


def run_and_wait(worker: RunWorker, name: str, produce: list[str]):
    """Start a run and wait for it to end; the start reply."""
    reply = worker.start(name, produce)
    if reply.run_id is not None:
        wait_until_finished(worker, reply.run_id)
    return reply


# ---- Run folders of finished runs ----

def write_fake_run(tmp_path, shape=(4, 3, 2), with_mask=True, with_compared_scores=False, with_patch_weights=False,
                   thresholding_upstream_run_id="pre-run"):
    """Write the preprocessing (and thresholding) outputs of a run; every voxel with i < 3 is occupied."""
    run = tmp_path / "run"
    preprocessing = run / "preprocessing"
    preprocessing.mkdir(parents=True)
    voxel_grid = np.zeros(shape, dtype=bool)
    voxel_grid[:3] = True
    raw_scores = np.arange(np.prod(shape), dtype=np.float32).reshape(shape)
    np.save(preprocessing / "voxel_grid.npy", voxel_grid)
    np.save(preprocessing / "scores.npy", raw_scores)
    if with_patch_weights:
        np.save(preprocessing / "patch_weights.npy", np.linspace(0.0, 1.0, 145, dtype=np.float32))
    (preprocessing / "manifest.json").write_text(schema_to_json(PreprocessingManifest(
        run_id="pre-run", scores_path="scores.npy", scores_kind="violation_count", shape=shape, origin=(10.0, 20.0, 30.0),
        voxel_size=2.0, mode="time-based", voxel_grid_path="voxel_grid.npy",
        patch_weights_path="patch_weights.npy" if with_patch_weights else None,
        sample_point_count=5, footprint_path="footprint.json", max_volume_lowest_z=30.0, max_volume_highest_z=34.0)),
        encoding="utf-8")
    if with_mask:
        thresholding = run / "thresholding"
        thresholding.mkdir()
        np.save(thresholding / "mask.npy", raw_scores % 2 == 0)
        compared_path = None
        if with_compared_scores:
            np.save(thresholding / "scores_compared_with_cutoff.npy", raw_scores + 100)
            compared_path = "scores_compared_with_cutoff.npy"
        (thresholding / "manifest.json").write_text(schema_to_json(ThresholdingManifest(
            run_id="thr-run", mask_path="mask.npy", scores_compared_with_cutoff_path=compared_path,
            upstream_manifest="../preprocessing/manifest.json", upstream_run_id=thresholding_upstream_run_id,
            resolved_threshold=ThresholdSpec(method="cutoff", value=1.0), score_smoothing_m=0.0, max_slope_deg=None)),
            encoding="utf-8")
    return run


def write_diagnostic(stage_folder: Path, content: dict) -> None:
    (stage_folder / "diagnostics").mkdir(parents=True)
    (stage_folder / "diagnostics" / "diagnostic.json").write_text(json.dumps(content), encoding="utf-8")


def write_fake_finished_run(tmp_path, obstruction_fraction_carved=None):
    run = write_fake_run(tmp_path)
    thresholding_diagnostic = {
        "threshold_value": 3.5, "voxels_occupied": 100, "voxels_kept": 61, "voxels_removed": 39, "retention_pct": 61.0,
        "carve_above_extra_voxels_removed": 4, "slope_limit_extra_voxels_removed": 2, "threshold_method": "cutoff"}
    if obstruction_fraction_carved is not None:
        thresholding_diagnostic["obstruction_fraction_carved"] = obstruction_fraction_carved
    write_diagnostic(run / "thresholding", thresholding_diagnostic)
    (run / "massing").mkdir()
    (run / "massing" / "plates.json").write_text(
        json.dumps({"plates": [], "floor_area_m2_per_floor": [120.0, 80.0], "total_floor_area_m2": 200.0}), encoding="utf-8")
    write_diagnostic(run / "massing", {"floors": 3, "floors_built": 2, "envelope_volume_m3": 4321.5})
    return run


def write_fake_finished_run_with_envelope(tmp_path, obstruction_fraction_carved=None):
    """A finished run whose exporting, built on its thresholding run, left 50 voxels of 2 m after its cleanup."""
    run = write_fake_finished_run(tmp_path, obstruction_fraction_carved)
    write_diagnostic(run / "exporting", {"voxels_original": 100, "voxels_retained": 50})
    (run / "exporting" / "manifest.json").write_text(schema_to_json(ExportingManifest(
        run_id="exp-run", mesh_path="export.ply", upstream_manifest="../thresholding/manifest.json", upstream_run_id="thr-run")),
        encoding="utf-8")
    return run
