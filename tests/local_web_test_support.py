"""Fakes and helpers that several tests of the local web service share (tests/test_local_web_*.py).

The engine is replaced by a fake that writes a manifest with a new run_id (and the current upstream run_id) for each stage it
runs, as the real stages do, in the chain layout of run_chain (run/criteria/<id>/<stage>, then run/exporting and run/massing).
The run folders of finished runs are written without computing anything. The fixture
``project_with_inputs`` is in conftest.py and builds its project with ``add_project_with_inputs``.
"""
import dataclasses
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
from typing import Collection

import numpy as np
import pytest
import trimesh
import yaml

from urbansolarcarver.io import load_mesh, save_mesh
from urbansolarcarver.local_web_service import test_surfaces
from urbansolarcarver.local_web_service.api_models import StageRecord
from urbansolarcarver.local_web_service.example_catalog import read_examples
from urbansolarcarver.local_web_service.projects import INPUTS_FOLDER, JOINED_FOLDER, ProjectStore
from urbansolarcarver.local_web_service.run_worker import RunWorker
from urbansolarcarver.mode_registry import MODES
from urbansolarcarver.pydantic_schemas import ExportingManifest, MassingManifest, PreprocessingManifest, ThresholdSpec, ThresholdingManifest, schema_to_json
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
    """A daylight project (no weather file needed) with a max volume and a test surface, which criterion "1" protects: the store and
    the project name."""
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


def write_joined_test_surfaces_without_normals(store: ProjectStore, name: str, criterion_id: str = "1") -> Path:
    """The joined test surface file of a criterion as the service wrote it before it kept vertex normals: positions only; its path."""
    project_folder = store.open(name)
    file_names = sorted(next(entry for entry in store.criteria(name) if entry.id == criterion_id).test_surface_files)
    meshes = [load_mesh(str(project_folder / INPUTS_FOLDER / "test_surfaces" / file_name)) for file_name in file_names]
    joined_path = project_folder / JOINED_FOLDER / f"test_surfaces_{criterion_id}.ply"
    save_mesh(trimesh.util.concatenate(meshes), str(joined_path))
    assert not has_vertex_normals(joined_path)
    return joined_path


def has_vertex_normals(ply_path: Path) -> bool:
    """Whether the header of a PLY file declares the vertex property nx."""
    header_lines = ply_path.read_bytes().split(b"end_header", 1)[0].splitlines()
    return any(line.split()[-1:] == [b"nx"] for line in header_lines if line.startswith(b"property"))


# ---- The fake engine and the run worker ----

def criteria_in_config(run_folder: Path) -> list[tuple[str, str]]:
    """The id and mode of each criterion that the config.yaml of the project whose run folder this is lists (the ones that are
    on), in order; one criterion "1" of daylight, the test projects' mode, for a config.yaml without criteria."""
    config_path = run_folder.parent / "config.yaml"
    stored = (yaml.safe_load(config_path.read_text(encoding="utf-8")) if config_path.is_file() else None) or {}
    if not stored.get("criteria"):
        return [("1", stored.get("mode", "daylight"))]
    return [(str(criterion["id"]), criterion.get("mode", "daylight")) for criterion in stored["criteria"]]


def run_id_in(manifest_folder: Path) -> str:
    """The run_id of the manifest in a stage folder."""
    return json.loads((manifest_folder / "manifest.json").read_text(encoding="utf-8"))["run_id"]


def write_fake_chain_file(run_folder: Path, criteria: list[tuple[str, str]]) -> None:
    """criteria/chain.json as run_chain writes it once the criteria are thresholded: each criterion and its thresholding run."""
    listed = [{"id": criterion_id, "name": criterion_id, "mode": mode,
               "thresholding_run_id": run_id_in(run_folder / "criteria" / criterion_id / "thresholding")}
              for criterion_id, mode in criteria]
    (run_folder / "criteria" / "chain.json").write_text(json.dumps({"criteria": listed}), encoding="utf-8")


def write_fake_stage_output(run_folder: Path, stage: str, criteria: list[tuple[str, str]] | None = None,
                            criterion_ids: Collection[str] | None = None) -> None:
    """What a finished stage leaves in the chain layout of run_chain: a manifest with a new run_id and the run_ids it read.

    *criteria* is the chain as (id, mode) pairs (default: config.yaml's). Preprocessing and thresholding write the folder of each
    criterion in *criterion_ids* (default: every one); a thresholding names its criterion's preprocessing as upstream and the
    previous criterion's thresholding as after (none for the first). Thresholding of every criterion (no *criterion_ids*) writes
    criteria/chain.json too; a caller that thresholds one criterion at a time writes it with write_fake_chain_file when done.
    Exporting and massing name the last criterion's thresholding as upstream.
    """
    criteria = criteria_in_config(run_folder) if criteria is None else criteria
    if stage in ("preprocessing", "thresholding"):
        previous_thresholding = None
        for criterion_id, mode in criteria:
            folder = run_folder / "criteria" / criterion_id / stage
            if criterion_ids is None or criterion_id in criterion_ids:
                manifest = {"run_id": uuid.uuid4().hex}
                if stage == "preprocessing":
                    # As the engine records them; stage status reads grid_step only to tell a manifest from before it was
                    # recorded, and score_unit to tell scores of another unit than the criterion's mode now writes.
                    manifest.update(max_volume_lowest_z=0.0, max_volume_highest_z=10.0, grid_step=0.5, score_unit=MODES[mode].score_unit)
                else:
                    manifest.update(upstream_manifest="../preprocessing/manifest.json", upstream_run_id=run_id_in(folder.parent / "preprocessing"))
                    if previous_thresholding is not None:
                        manifest.update(after_manifest=f"../../{previous_thresholding.parent.name}/thresholding/manifest.json",
                                        after_run_id=run_id_in(previous_thresholding))
                folder.mkdir(parents=True, exist_ok=True)
                (folder / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            previous_thresholding = run_folder / "criteria" / criterion_id / "thresholding"
        if stage == "thresholding" and criterion_ids is None:
            write_fake_chain_file(run_folder, criteria)
        return
    last_id = criteria[-1][0]
    folder = run_folder / stage
    folder.mkdir(parents=True, exist_ok=True)
    manifest = {"run_id": uuid.uuid4().hex, "upstream_run_id": run_id_in(run_folder / "criteria" / last_id / "thresholding"),
                "upstream_manifest": f"../criteria/{last_id}/thresholding/manifest.json"}
    if stage == "massing":      # the fake writes its plates as OBJ whatever the format chosen
        manifest.update(plates_path="plates.json", mesh_path="plates.obj", export_mesh_path="plates.obj")
    (folder / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    if stage == "exporting":
        (folder / "export.ply").write_bytes(b"ply")
    if stage == "massing":
        (folder / "plates.json").write_text("{}", encoding="utf-8")
        (folder / "plates.obj").write_text("", encoding="utf-8")
        (run_folder / "run_report.md").write_text("report", encoding="utf-8")


def write_fake_chain_run(store: ProjectStore, name: str, criterion_ids: list[str]) -> None:
    """A finished run of every stage of the chain *criterion_ids* (in order) and the records a run leaves: every stage is current.

    The manifests are those of write_fake_stage_output. Each criterion's records hold its settings, the inputs revision and the
    fingerprint of its test surfaces; exporting's and massing's hold the settings of the last criterion.
    """
    project_folder = store.open(name)
    run_folder = project_folder / "run"
    modes = {entry.id: entry.settings.get("mode", "daylight") for entry in store.criteria(name)}
    criteria = [(criterion_id, modes[criterion_id]) for criterion_id in criterion_ids]
    for stage in PIPELINE_STAGES:
        write_fake_stage_output(run_folder, stage, criteria)
    settings = {criterion_id: store.read_stored_config(name, criterion_id) for criterion_id in criterion_ids}
    with store.project_lock(name):
        project_json = store.read_project_json(name)
        for criterion_id in criterion_ids:
            project_json.criterion_records[criterion_id] = {stage: StageRecord(
                config=settings[criterion_id], inputs_revision=project_json.inputs_revision,
                manifest_run_id=run_id_in(run_folder / "criteria" / criterion_id / stage),
                test_surfaces_fingerprint=test_surfaces.fingerprint(project_folder, criterion_id))
                for stage in ("preprocessing", "thresholding")}
        for stage in ("exporting", "massing"):
            project_json.stage_records[stage] = StageRecord(
                config=settings[criterion_ids[-1]], inputs_revision=project_json.inputs_revision, manifest_run_id=run_id_in(run_folder / stage))
        store.write_project_json(name, project_json)


def write_envelope_as_exported(project_folder: Path, extents=(8, 8, 6)) -> trimesh.Trimesh:
    """Put a real envelope mesh where the fake exporting stage left its placeholder, named by the manifest as the engine does."""
    exporting_folder = project_folder / "run" / "exporting"
    envelope = trimesh.creation.box(extents=extents)
    envelope.apply_translation([0, 0, extents[2] / 2])
    envelope.export(exporting_folder / "export.ply")
    manifest = json.loads((exporting_folder / "manifest.json").read_text(encoding="utf-8"))
    manifest.update(mesh_path="export.ply")     # as the engine writes it; the run_id stays, so the stage stays current
    (exporting_folder / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return envelope


def stages_the_engine_runs(request) -> list[str]:
    path = stages_needed_for(request.produce)
    return path[path.index(request.start_from):]


def criteria_the_engine_runs(request, stage: str, criterion_ids: list[str]) -> list[str]:
    """The criteria whose *stage* folder run_chain writes for *request*: preprocessing traces the criteria in trace_criteria (every
    one without it), and thresholding starts at the first traced one or at threshold_from_criterion, whichever comes first, or at
    the first criterion when preprocessing does not run."""
    traces = request.start_from == "preprocessing"
    traced = [criterion_id for criterion_id in criterion_ids
              if not traces or request.trace_criteria is None or criterion_id in request.trace_criteria]
    if stage == "preprocessing":
        return traced
    if not (traces and traced):
        return list(criterion_ids)
    starts = [criterion_ids.index(traced[0])]
    if request.threshold_from_criterion is not None:
        starts.append(criterion_ids.index(request.threshold_from_criterion))
    return criterion_ids[min(starts):]


class FakeEngine:
    """Stands in for ``handle_engine_request``; keeps the requests it received. It writes the chain layout and reports progress
    as run_chain does: each criterion's stages inside ``criterion <id>``, its issues named ``criterion <id> (<stage>)``, then
    exporting and massing."""

    def __init__(self):
        self.requests = []

    def __call__(self, request, session, context):
        self.requests.append(request)
        run_folder = Path(request.run_folder)
        criteria = criteria_in_config(run_folder)
        criterion_ids = [criterion_id for criterion_id, _mode in criteria]
        stages = stages_the_engine_runs(request)
        analysis_stages = [stage for stage in ("preprocessing", "thresholding") if stage in stages]
        with run_context(context):
            if "thresholding" in analysis_stages:
                (run_folder / "criteria" / "chain.json").unlink(missing_ok=True)
            for position, criterion_id in enumerate(criterion_ids, start=1):
                with stage_context(f"criterion {criterion_id}"):
                    context.raise_if_cancelled()
                    report_progress(position - 1, len(criteria))
                    first_new_issue = len(context.issues)
                    for stage in analysis_stages:
                        if criterion_id in criteria_the_engine_runs(request, stage, criterion_ids):
                            self._run_criterion_stage(run_folder, stage, criteria, criterion_id, context)
                    for index in range(first_new_issue, len(context.issues)):
                        issue = context.issues[index]
                        context.issues[index] = dataclasses.replace(issue, stage=f"criterion {criterion_id} ({issue.stage})")
                    report_progress(position, len(criteria))
            if "thresholding" in analysis_stages:
                write_fake_chain_file(run_folder, criteria)
            for stage in stages:
                if stage in ("exporting", "massing"):
                    with stage_context(stage):
                        report_progress(0, 1)
                        context.raise_if_cancelled()
                        write_fake_stage_output(run_folder, stage, criteria)
                        report_progress(1, 1)

    @staticmethod
    def _run_criterion_stage(run_folder, stage, criteria, criterion_id, context) -> None:
        with stage_context(stage):
            report_progress(0, 1)
            context.raise_if_cancelled()
            if stage == "preprocessing":
                report_issue("fake_issue", "preprocessing noticed something")
            write_fake_stage_output(run_folder, stage, criteria, [criterion_id])
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
    (run / "massing" / "manifest.json").write_text(schema_to_json(MassingManifest(
        run_id="mas-run", plates_path="plates.json", mesh_path="plates.obj", export_mesh_path="plates.stl",
        upstream_manifest="../thresholding/manifest.json", upstream_run_id="thr-run")), encoding="utf-8")
    return run


EARLIER_JOINED_TEST_SURFACES = "inputs/joined/test_surfaces.ply"     # the one joined test surface file of an earlier version


def write_earlier_version_project(store: ProjectStore, name: str, stages: Collection[str] = PIPELINE_STAGES,
                                  carved_further: bool = False) -> None:
    """A daylight project as an earlier version of the service left it: project.json without criteria, a config.yaml of one
    criterion (the flat form), its test surface file joined in inputs/joined/test_surfaces.ply, and for each of *stages* the
    folder of the single-criterion run layout (run/<stage>, manifests as the engine writes them, after write_fake_finished_run)
    with the stage's record in stage_records. The stages written are current as that version told it: each record holds the
    config.yaml content, the inputs revision and the run id of its manifest, and each manifest names its upstream's run id.

    *carved_further*: the project was carved further once (the Allatini form), so its maximum volume is carved_envelope_1.ply,
    the uploaded one is in inputs/earlier_max_volumes/1/ and project.json has a carving_chain step.
    """
    store.create(name, "daylight")
    store.add_input(name, "max_volume", "volume.ply", box_bytes([0, 0, 5]))
    store.add_input(name, "test_surfaces", "surface.ply", box_bytes([0, 0, 0], extents=(6, 6, 0.1)))
    project_folder = store.open(name)
    if carved_further:
        envelope_path = project_folder / "envelope.ply"
        envelope_path.write_bytes(box_bytes([0, 0, 3], extents=(8, 8, 6)))
        store.replace_max_volume_with_envelope(name, envelope_path, "daylight", store.read_settings(name))
        envelope_path.unlink()
    config = {**store.read_stored_config(name), "test_surface_path": EARLIER_JOINED_TEST_SURFACES}
    os.replace(test_surfaces.joined_path(project_folder, "1"), project_folder / EARLIER_JOINED_TEST_SURFACES)
    (project_folder / "config.yaml").write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    run = project_folder / "run"
    run_ids = {"preprocessing": "pre-run", "thresholding": "thr-run", "exporting": "exp-run", "massing": "mas-run"}
    if "preprocessing" in stages:
        (run / "preprocessing").mkdir(parents=True)
        np.save(run / "preprocessing" / "voxel_grid.npy", np.ones((4, 3, 2), dtype=bool))
        np.save(run / "preprocessing" / "scores.npy", np.arange(24, dtype=np.float32).reshape(4, 3, 2))
        (run / "preprocessing" / "manifest.json").write_text(schema_to_json(PreprocessingManifest(
            run_id="pre-run", scores_path="scores.npy", scores_kind="weighted_sum", shape=(4, 3, 2), origin=(-5.0, -5.0, 0.0),
            voxel_size=2.0, mode="daylight", voxel_grid_path="voxel_grid.npy", sample_point_count=5, grid_step=0.5,
            score_unit=MODES["daylight"].score_unit, footprint_path="footprint.json", max_volume_lowest_z=0.0,
            max_volume_highest_z=10.0)), encoding="utf-8")
    if "thresholding" in stages:
        (run / "thresholding").mkdir(parents=True)
        np.save(run / "thresholding" / "mask.npy", np.arange(24).reshape(4, 3, 2) % 2 == 0)
        write_diagnostic(run / "thresholding", {"threshold_value": 3.5, "voxels_occupied": 24, "voxels_kept": 12})
        (run / "thresholding" / "manifest.json").write_text(schema_to_json(ThresholdingManifest(
            run_id="thr-run", mask_path="mask.npy", upstream_manifest="../preprocessing/manifest.json", upstream_run_id="pre-run",
            resolved_threshold=ThresholdSpec(method="cutoff", value=1.0), score_smoothing_m=0.0, max_slope_deg=None)), encoding="utf-8")
    if "exporting" in stages:
        (run / "exporting").mkdir(parents=True)
        (run / "exporting" / "export.ply").write_bytes(box_bytes([0, 0, 3], extents=(8, 8, 6)))
        (run / "exporting" / "manifest.json").write_text(schema_to_json(ExportingManifest(
            run_id="exp-run", mesh_path="export.ply", upstream_manifest="../thresholding/manifest.json", upstream_run_id="thr-run")),
            encoding="utf-8")
    if "massing" in stages:
        (run / "massing").mkdir(parents=True)
        (run / "massing" / "plates.json").write_text(
            json.dumps({"plates": [], "floor_area_m2_per_floor": [120.0, 80.0], "total_floor_area_m2": 200.0}), encoding="utf-8")
        (run / "massing" / "plates.obj").write_text("", encoding="utf-8")
        (run / "massing" / "manifest.json").write_text(schema_to_json(MassingManifest(
            run_id="mas-run", plates_path="plates.json", mesh_path="plates.obj", export_mesh_path="plates.obj",
            upstream_manifest="../thresholding/manifest.json", upstream_run_id="thr-run")), encoding="utf-8")
        (run / "run_report.md").write_text("report", encoding="utf-8")
    with store.project_lock(name):
        project_json = store.read_project_json(name)
        records = {stage: StageRecord(config=config, inputs_revision=project_json.inputs_revision, manifest_run_id=run_ids[stage])
                   for stage in PIPELINE_STAGES if stage in stages}
        store.write_project_json(name, project_json.model_copy(update={
            "criteria": [], "next_criterion_id": 1, "criterion_records": {}, "stage_records": records}))


def write_fake_finished_run_with_envelope(tmp_path, obstruction_fraction_carved=None):
    """A finished run whose exporting, built on its thresholding run, left 50 voxels of 2 m after its cleanup."""
    run = write_fake_finished_run(tmp_path, obstruction_fraction_carved)
    write_diagnostic(run / "exporting", {"voxels_original": 100, "voxels_retained": 50})
    (run / "exporting" / "manifest.json").write_text(schema_to_json(ExportingManifest(
        run_id="exp-run", mesh_path="export.ply", upstream_manifest="../thresholding/manifest.json", upstream_run_id="thr-run")),
        encoding="utf-8")
    return run
