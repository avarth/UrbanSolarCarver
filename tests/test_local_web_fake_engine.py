"""FakeEngine (local_web_test_support.py) writes the criteria folders that run_chain would write for the same request.

The fast chain tests of the run worker and of the stage records run on FakeEngine, which copies run_chain's rule for the
criteria a request traces again (trace_criteria) and thresholds again (from the first traced one or threshold_from_criterion).
If run_chain's rule changed and the copy did not, those tests would stay green while the service runs the wrong stages. Here
the real ``handle_engine_request`` (the function FakeEngine stands in for) runs a three-criteria chain with the stage functions
of run_chain replaced by recorders, so its own selection decides which criteria are traced and thresholded, and the result is
compared with the criteria folders to which FakeEngine writes a new manifest, over a table of requests. The service's own copy
of the rule (stage_records._criterion_stages, which says which stage records a run replaces) is compared with the same
recorded selection.
"""
import shutil
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest

from _chain_scene import chain_scene, daylight_on_east, daylight_on_south
from local_web_test_support import FakeEngine, FakeSession, run_id_in, write_fake_stage_output
from urbansolarcarver.api_core import chain as chain_module
from urbansolarcarver.engine_requests import RunRequest, handle_engine_request
from urbansolarcarver.local_web_service.stage_records import _criterion_stages
from urbansolarcarver.run_context import RunContext
from urbansolarcarver.stage_settings import PIPELINE_STAGES, stages_needed_for

# Ids that are not positions, so a rule that mixes up an id with its place in the chain shows.
CRITERION_IDS = ("a", "b", "c")
CRITERION_STAGES = ("preprocessing", "thresholding")
TRACES = (None, ["a"], ["b"], ["c"], ["a", "c"], ["b", "c"])
THRESHOLD_FROMS = (None, "a", "b", "c")


def the_requests():
    """(start_from, produce, trace_criteria, threshold_from_criterion): every pair of trace_criteria and threshold_from_criterion
    from preprocessing and every threshold_from_criterion from thresholding, with fewer cases for the stages around them, whose
    choice of criteria does not depend on the leaf stages asked for (each request costs about 15 ms)."""
    requests = [("preprocessing", ["thresholding"], trace, threshold_from) for trace in TRACES for threshold_from in THRESHOLD_FROMS]
    requests += [("preprocessing", ["exporting"], trace, threshold_from) for trace in (None, ["b"]) for threshold_from in (None, "a")]
    # Preprocessing alone, which ignores threshold_from_criterion.
    requests += [("preprocessing", ["preprocessing"], trace, threshold_from) for trace in TRACES for threshold_from in (None, "a")]
    # From thresholding, run_chain ignores trace_criteria.
    requests += [("thresholding", ["thresholding"], trace, threshold_from) for trace in (None, ["b"]) for threshold_from in THRESHOLD_FROMS]
    requests += [("thresholding", ["massing"], None, threshold_from) for threshold_from in (None, "b")]
    requests += [("exporting", ["exporting"], None, None), ("massing", ["massing"], ["b"], "b")]
    return requests


@pytest.fixture
def chain_file(tmp_path) -> Path:
    """chain.yaml of three daylight criteria a, b, c on the chain scene."""
    scene = chain_scene(tmp_path)
    criteria = [daylight_on_south(0.3), daylight_on_east(0.3), daylight_on_south(0.2)]
    scene.chain_config(tmp_path / "chain", [{**item, "id": criterion_id} for item, criterion_id in zip(criteria, CRITERION_IDS)])
    return tmp_path / "chain" / "chain.yaml"


@pytest.fixture
def stages_run_chain_calls(monkeypatch) -> list[tuple[str, str]]:
    """Replace the stages run_chain calls with recorders; the (criterion id, stage) of each call, in order."""
    calls = []

    def stage_result():
        return SimpleNamespace(run_id=uuid.uuid4().hex, export_path="export.ply", plates_path="plates.json",
                               mesh_path="plates.obj", export_mesh_path="plates.obj")

    def preprocessing(config, out_dir):
        calls.append((Path(out_dir).parent.name, "preprocessing"))
        return stage_result()

    def thresholding(upstream, config, out_dir, after=None):
        calls.append((Path(out_dir).parent.name, "thresholding"))
        return stage_result()

    monkeypatch.setattr(chain_module, "preprocessing", preprocessing)
    monkeypatch.setattr(chain_module, "thresholding", thresholding)
    monkeypatch.setattr(chain_module, "exporting", lambda upstream, config, out_dir: stage_result())
    monkeypatch.setattr(chain_module, "massing", lambda upstream, config, out_dir: stage_result())
    # A criterion run_chain does not threshold again keeps its thresholding, whose run id it reads for chain.json.
    monkeypatch.setattr(chain_module, "load_upstream", lambda folder, stage: SimpleNamespace(manifest=SimpleNamespace(run_id="kept")))
    return calls


def criteria_run_chain_runs(request: RunRequest, calls: list[tuple[str, str]]) -> dict[str, list[str]]:
    """The criteria the real handle_engine_request runs each analysis stage for, with the recorders of stages_run_chain_calls."""
    calls.clear()
    handle_engine_request(request, FakeSession(), RunContext())
    return {stage: [criterion_id for criterion_id, called in calls if called == stage] for stage in CRITERION_STAGES}


def criteria_with_new_manifests(run_folder: Path, before: dict) -> dict[str, list[str]]:
    return {stage: [criterion_id for criterion_id in CRITERION_IDS
                    if run_id_in(run_folder / "criteria" / criterion_id / stage) != before[criterion_id, stage]]
            for stage in CRITERION_STAGES}


def test_the_fake_engine_traces_and_thresholds_the_criteria_run_chain_does(tmp_path, chain_file, stages_run_chain_calls):
    # FakeEngine reads the criteria from the config.yaml next to its run folder, as in a project.
    project = tmp_path / "project"
    project.mkdir()
    shutil.copyfile(chain_file, project / "config.yaml")
    fake_run_folder = project / "run"
    for stage in CRITERION_STAGES:
        write_fake_stage_output(fake_run_folder, stage)
    fake = FakeEngine()
    differences = []
    for start_from, produce, trace, threshold_from in the_requests():
        request = RunRequest(cmd="run", produce=produce, start_from=start_from, config=str(chain_file),
                             run_folder=str(tmp_path / "real_run"), trace_criteria=trace, threshold_from_criterion=threshold_from)
        real = criteria_run_chain_runs(request, stages_run_chain_calls)

        before = {(criterion_id, stage): run_id_in(fake_run_folder / "criteria" / criterion_id / stage)
                  for criterion_id in CRITERION_IDS for stage in CRITERION_STAGES}
        fake(request.model_copy(update={"run_folder": str(fake_run_folder)}), FakeSession(), RunContext())
        written = criteria_with_new_manifests(fake_run_folder, before)
        if written != real:
            differences.append(f"start_from={start_from} produce={produce} trace={trace} threshold_from={threshold_from}: "
                               f"run_chain {real}, FakeEngine {written}")
    assert not differences, ("FakeEngine (criteria_the_engine_runs in local_web_test_support.py) no longer follows run_chain's "
                             "choice of criteria:\n" + "\n".join(differences))


def test_the_stage_records_name_the_criteria_run_chain_traces_and_thresholds(tmp_path, chain_file, stages_run_chain_calls):
    """choose_stages tells the app (StartRunReply.criterion_stages) and forget_stages which criteria's stage records a run
    replaces, by stage_records._criterion_stages, a second copy of run_chain's rule. It is checked over the requests of the
    table the service can send: run_worker passes trace_criteria only from preprocessing (StageChoice.trace_criteria or None),
    and choose_stages starts at preprocessing only with a criterion to trace."""
    differences, starts_checked = [], set()
    for start_from, produce, trace, threshold_from in the_requests():
        if (trace is not None) != (start_from == "preprocessing"):
            continue
        starts_checked.add(start_from)
        request = RunRequest(cmd="run", produce=produce, start_from=start_from, config=str(chain_file),
                             run_folder=str(tmp_path / "real_run"), trace_criteria=trace, threshold_from_criterion=threshold_from)
        real = criteria_run_chain_runs(request, stages_run_chain_calls)
        # The stages the run executes, as choose_stages lists them: from start_from on, those produce needs.
        stages = [stage for stage in stages_needed_for(produce) if PIPELINE_STAGES.index(stage) >= PIPELINE_STAGES.index(start_from)]
        per_criterion = _criterion_stages(list(CRITERION_IDS), stages, trace or [], threshold_from)
        named = {stage: [criterion_id for criterion_id in CRITERION_IDS if stage in per_criterion[criterion_id]]
                 for stage in CRITERION_STAGES}
        if named != real:
            differences.append(f"start_from={start_from} produce={produce} trace={trace} threshold_from={threshold_from}: "
                               f"run_chain {real}, stage_records {named}")
    assert starts_checked == {"preprocessing", "thresholding", "exporting"}     # the table's massing row traces, so is left out
    assert not differences, ("stage_records._criterion_stages no longer follows run_chain's choice of criteria:\n"
                             + "\n".join(differences))


def test_a_chain_run_of_preprocessing_alone_that_leaves_the_last_criterion_untraced_replies(chain_file, tmp_path, stages_run_chain_calls):
    request = RunRequest(cmd="run", produce=["preprocessing"], start_from="preprocessing", config=str(chain_file),
                         run_folder=str(tmp_path / "run"), trace_criteria=["a"])
    reply = handle_engine_request(request, FakeSession(), RunContext())
    assert stages_run_chain_calls == [("a", "preprocessing")]
    assert Path(reply.manifest) == tmp_path / "run" / "criteria" / "a" / "preprocessing" / "manifest.json"
