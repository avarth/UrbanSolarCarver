"""The sequencer: ``produce`` and ``start_from``, collected issues, progress
and cancellation (daylight mode on a 10 m cube, CPU, no EPW needed)."""
import json

import pytest

from _stage_scene import daylight_cube_config
from urbansolarcarver import run_pipeline
from urbansolarcarver.errors import RunCancelled
from urbansolarcarver.run_context import RunContext


def test_produce_massing_skips_exporting(tmp_path):
    result = run_pipeline(daylight_cube_config(tmp_path), tmp_path / "run", produce={"massing"})
    assert result.exporting is None and result.massing.n_plates > 0
    assert not (tmp_path / "run" / "exporting").exists()


def test_default_runs_preprocessing_thresholding_and_exporting(tmp_path):
    result = run_pipeline(daylight_cube_config(tmp_path), tmp_path / "run")
    assert result.preprocessing is not None and result.thresholding is not None
    assert result.exporting.export_path.is_file()
    assert result.massing is None


def test_produce_exporting_and_massing_runs_both_after_one_thresholding(tmp_path):
    result = run_pipeline(daylight_cube_config(tmp_path), tmp_path / "run",
                          produce=("massing", "exporting"))
    assert result.exporting is not None and result.massing is not None
    assert result.exporting.export_path.is_file() and result.massing.plates_path.is_file()


def test_produce_preprocessing_alone_stops_there(tmp_path):
    result = run_pipeline(daylight_cube_config(tmp_path), tmp_path / "run",
                          produce={"preprocessing"})
    assert result.preprocessing is not None
    assert result.thresholding is None and result.exporting is None
    assert not (tmp_path / "run" / "thresholding").exists()


def test_start_from_thresholding_reuses_preprocessing(tmp_path):
    conf = daylight_cube_config(tmp_path)
    first = run_pipeline(conf, tmp_path / "run")
    again = run_pipeline(conf.model_copy(update={"carve_fraction": 0.5}), tmp_path / "run",
                         start_from="thresholding")
    assert again.preprocessing is None
    assert again.thresholding.upstream_run_id == first.preprocessing.run_id


def test_start_from_exporting_reuses_thresholding(tmp_path):
    conf = daylight_cube_config(tmp_path)
    first = run_pipeline(conf, tmp_path / "run")
    again = run_pipeline(conf, tmp_path / "run", start_from="exporting")
    assert again.preprocessing is None and again.thresholding is None
    manifest = json.loads((tmp_path / "run" / "exporting" / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["upstream_run_id"] == first.thresholding.run_id


def test_start_from_a_stage_that_was_never_run_is_a_stage_chain_error(tmp_path):
    from urbansolarcarver.errors import StageChainError
    with pytest.raises(StageChainError):
        run_pipeline(daylight_cube_config(tmp_path), tmp_path / "run", start_from="thresholding")


def test_start_from_outside_the_path_is_refused(tmp_path):
    with pytest.raises(ValueError, match="start_from"):
        run_pipeline(daylight_cube_config(tmp_path), tmp_path / "run", produce={"preprocessing"},
                     start_from="massing")


def test_unknown_or_empty_produce_is_refused(tmp_path):
    conf = daylight_cube_config(tmp_path)
    with pytest.raises(ValueError, match="produce"):
        run_pipeline(conf, tmp_path / "run", produce={"rendering"})
    with pytest.raises(ValueError, match="produce"):
        run_pipeline(conf, tmp_path / "run", produce=())


def test_config_can_be_a_yaml_path(tmp_path):
    import yaml
    conf = daylight_cube_config(tmp_path)
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(conf.model_dump(mode="json", exclude_none=True)),
                    encoding="utf-8")
    result = run_pipeline(path, tmp_path / "run")
    assert result.exporting.export_path.is_file()


def test_issues_of_all_stages_are_collected(tmp_path):
    conf = daylight_cube_config(tmp_path, threshold=1e9)            # nothing carved
    result = run_pipeline(conf, tmp_path / "run")
    assert ("thresholding", "nothing_carved") in [(i.stage, i.code) for i in result.issues]


def test_issues_reach_a_context_the_caller_passes(tmp_path):
    context = RunContext()
    result = run_pipeline(daylight_cube_config(tmp_path, threshold=1e9), tmp_path / "run",
                          context=context)
    assert result.issues and set(result.issues) <= set(context.issues)
    assert result.thresholding.issues  # the stage Result still carries its own


def test_progress_reports_each_stage_and_batch(tmp_path):
    calls = []
    run_pipeline(daylight_cube_config(tmp_path, ray_batch_size=500), tmp_path / "run",
                 context=RunContext(on_progress=lambda s, d, t: calls.append((s, d, t))))
    assert {s for s, _, _ in calls} >= {"preprocessing", "thresholding", "exporting"}
    assert any(s == "preprocessing" and t > 1 for s, _, t in calls)
    for stage in ("preprocessing", "thresholding", "exporting"):
        assert (stage, 0, 1) in calls and (stage, 1, 1) in calls


def test_batch_progress_counts_up_to_the_batch_total(tmp_path):
    calls = []
    run_pipeline(daylight_cube_config(tmp_path, ray_batch_size=500), tmp_path / "run",
                 produce={"preprocessing"},
                 context=RunContext(on_progress=lambda s, d, t: calls.append((s, d, t))))
    batches = [(d, t) for s, d, t in calls if t > 1]
    total = batches[0][1]
    assert [d for d, _ in batches] == list(range(1, total + 1))


def test_cancel_between_stages(tmp_path):
    context = RunContext(on_progress=lambda s, d, t: context.cancel() if s == "thresholding" else None)
    with pytest.raises(RunCancelled):
        run_pipeline(daylight_cube_config(tmp_path), tmp_path / "run", context=context)
    assert not (tmp_path / "run" / "exporting" / "manifest.json").exists()


def test_cancel_stops_parallel_cpu_batches(tmp_path):
    # ray_batch_size small enough for several CPU batches; cancel on the first batch progress call
    context = RunContext(on_progress=lambda s, d, t: context.cancel() if (s, d) == ("preprocessing", 1) and t > 2 else None)
    with pytest.raises(RunCancelled):
        run_pipeline(daylight_cube_config(tmp_path, ray_batch_size=200), tmp_path / "run", context=context)
    assert not (tmp_path / "run" / "preprocessing" / "manifest.json").exists()


def test_cancelled_batches_launch_nothing_more(tmp_path):
    import torch
    from urbansolarcarver.carving import _run_batches
    from urbansolarcarver.run_context import run_context
    context = RunContext(on_progress=lambda s, d, t: context.cancel() if d == 1 else None)
    launched = []
    batches = [(i, i + 1) for i in range(12)]
    with run_context(context), pytest.raises(RunCancelled):
        _run_batches(batches, lambda start, end, buf: launched.append(start),
                     torch.zeros(4), torch.device("cpu"), parallel=True)
    assert launched == [0]


def _parallel_batches_need_two_workers():
    import os
    if (os.cpu_count() or 1) < 2:
        pytest.skip("the threaded batch loop needs at least two CPU cores")


def test_final_progress_call_survives_a_late_finished_batch(monkeypatch):
    """The calling thread can see an empty queue just before the last tokens
    arrive; those tokens are still reported, so (total, total) is never lost."""
    import queue
    import time
    import types

    import torch
    from urbansolarcarver import carving
    from urbansolarcarver.run_context import run_context

    _parallel_batches_need_two_workers()

    class LateQueue(queue.Queue):
        first_get = True

        def get(self, block=True, timeout=None):
            if LateQueue.first_get:
                LateQueue.first_get = False
                time.sleep(0.5)  # the workers finish every batch meanwhile
                raise queue.Empty
            return super().get(block, timeout)

    monkeypatch.setattr(carving, "queue", types.SimpleNamespace(Queue=LateQueue, Empty=queue.Empty))
    calls = []
    context = RunContext(on_progress=lambda stage, done, total: calls.append((done, total)))
    batches = [(i, i + 1) for i in range(9)]
    with run_context(context):
        carving._run_batches(batches, lambda start, end, buf: None,
                             torch.zeros(4), torch.device("cpu"), parallel=True)
    assert calls[-1] == (9, 9)
    assert [done for done, _ in calls] == list(range(1, 10))


def test_a_failing_worker_stops_the_other_workers():
    import time

    import torch
    from urbansolarcarver.carving import _run_batches

    _parallel_batches_need_two_workers()
    launched = []

    def launch(start, end, buffer):
        launched.append(start)
        if start == 1:
            raise RuntimeError("batch failed")
        time.sleep(0.05)

    batches = [(i, i + 1) for i in range(41)]
    with pytest.raises(RuntimeError, match="batch failed"):
        _run_batches(batches, launch, torch.zeros(4), torch.device("cpu"), parallel=True)
    assert len(launched) < 20
