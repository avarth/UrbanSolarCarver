"""run_chain: criteria carved in sequence on one voxel grid, then exporting and massing from the last (daylight and
tilted plane on a box with two facades, CPU, no EPW needed). Each test runs preprocessing several times."""
import json
import shutil

import numpy as np
import pytest

from _chain_scene import chain_scene, daylight_on_east, daylight_on_south, tilted_plane_on_east
from urbansolarcarver import preprocessing, run_chain
from urbansolarcarver.errors import StageChainError
from urbansolarcarver.run_context import RunContext, report_issue, stage_context

pytestmark = pytest.mark.slow


def _two_criteria(tmp_path, first=0.6, second=0.5, folder="cfg"):
    return chain_scene(tmp_path).chain_config(tmp_path / folder, [daylight_on_south(first), daylight_on_east(second)])


def test_a_chain_of_two_writes_one_folder_per_criterion_and_builds_from_the_last(tmp_path):
    result = run_chain(_two_criteria(tmp_path), tmp_path / "run", produce=("exporting", "massing"))
    for cid in ("1", "2"):
        assert (tmp_path / f"run/criteria/{cid}/preprocessing/manifest.json").is_file()
        assert (tmp_path / f"run/criteria/{cid}/thresholding/manifest.json").is_file()
    assert len(result.criteria) == 2 and result.exporting is not None and result.massing is not None
    last = result.criteria[1].thresholding.run_id
    for stage in ("exporting", "massing"):
        manifest = json.loads((tmp_path / f"run/{stage}/manifest.json").read_text())
        assert manifest["upstream_run_id"] == last
    listed = json.loads((tmp_path / "run/criteria/chain.json").read_text())["criteria"]
    assert [row["id"] for row in listed] == ["1", "2"]
    assert [row["thresholding_run_id"] for row in listed] == [r.thresholding.run_id for r in result.criteria]
    assert [row["mode"] for row in listed] == ["daylight", "daylight"]
    report = (tmp_path / "run/run_report.md").read_text(encoding="utf-8")
    assert "## Criteria" in report and "## Export" in report and "## Massing" in report


def test_the_report_lists_each_criterion_with_the_voxels_it_started_with_and_kept(tmp_path):
    result = run_chain(_two_criteria(tmp_path), tmp_path / "run")
    first, second = (r.thresholding for r in result.criteria)
    report = (tmp_path / "run/run_report.md").read_text(encoding="utf-8")
    criteria = report[report.index("## Criteria"):report.index("## Chain")]
    rows = [line for line in criteria.splitlines() if line.startswith(("| 1 |", "| 2 |"))]
    assert len(rows) == 2
    assert f"{first.voxels_kept + first.voxels_removed:,}" in rows[0] and f"{first.voxels_kept:,}" in rows[0]
    assert f"{first.voxels_kept:,}" in rows[1] and f"{second.voxels_kept:,}" in rows[1]


def test_the_report_of_a_chain_run_gives_the_volumes_and_the_total_time(tmp_path):
    result = run_chain(_two_criteria(tmp_path), tmp_path / "run")
    first, second = (r.thresholding for r in result.criteria)
    voxel_size = json.loads((tmp_path / "run/criteria/1/preprocessing/manifest.json").read_text())["voxel_size"]
    report = (tmp_path / "run/run_report.md").read_text(encoding="utf-8")
    chain = report[report.index("## Chain"):report.index("## Preprocessing")]
    for result_thr in (first, second):
        assert f"{result_thr.voxels_kept * voxel_size ** 3:,.1f}" in chain
    share = 100 * second.voxels_kept / (first.voxels_kept + first.voxels_removed)
    assert chain.rstrip().endswith(f"| {second.voxels_kept * voxel_size ** 3:,.1f} | {share:.1f} |")
    assert "| # | Name | Mode | Rule | Cutoff |" in report
    assert "**Total time:**" in report.split("## Total")[1]


def test_massing_of_a_chain_follows_the_drawn_footprint(tmp_path):
    # The max volume is a box turned 20 degrees: the ground floor plate has the box's 4 corners, not voxel steps.
    chain = chain_scene(tmp_path, turn_deg=20.0).chain_config(
        tmp_path / "cfg", [daylight_on_south(0.1), daylight_on_east(0.1)])
    result = run_chain(chain, tmp_path / "run", produce=("massing",))
    ground = [plate for plate in json.loads(result.massing.plates_path.read_text())["plates"] if plate["floor"] == 0]
    assert ground and all(len(plate["outline"]) <= 6 for plate in ground)


def test_re_thresholding_the_chain_reuses_the_rays(tmp_path):
    out = tmp_path / "run"
    first = run_chain(_two_criteria(tmp_path), out)
    scores = [out / f"criteria/{cid}/preprocessing/scores.npy" for cid in ("1", "2")]
    before = [path.stat().st_mtime_ns for path in scores]
    again = run_chain(_two_criteria(tmp_path, first=0.8, folder="cfg2"), out, start_from="thresholding")
    assert [path.stat().st_mtime_ns for path in scores] == before
    assert all(r.preprocessing is None and r.thresholding is not None for r in again.criteria)
    assert again.criteria[0].thresholding.voxels_kept < first.criteria[0].thresholding.voxels_kept
    assert again.criteria[1].thresholding.voxels_kept < first.criteria[1].thresholding.voxels_kept


def test_a_tilted_plane_criterion_after_daylight_acts_only_on_what_is_left(tmp_path):
    chain = chain_scene(tmp_path).chain_config(tmp_path / "cfg", [daylight_on_south(0.3), tilted_plane_on_east(30)])
    result = run_chain(chain, tmp_path / "run", produce=("thresholding",))
    m1, m2 = (np.load(r.thresholding.mask_path) for r in result.criteria)
    assert not (m2 & ~m1).any() and m2.sum() < m1.sum()
    assert result.exporting is None and result.massing is None


def test_start_from_massing_builds_again_from_the_last_thresholding(tmp_path):
    chain = _two_criteria(tmp_path)
    first = run_chain(chain, tmp_path / "run")
    again = run_chain(chain, tmp_path / "run", produce=("massing",), start_from="massing")
    assert len(again.criteria) == 2 and all(r.preprocessing is None and r.thresholding is None for r in again.criteria)
    assert again.massing is not None and again.exporting is None
    manifest = json.loads((tmp_path / "run/massing/manifest.json").read_text())
    assert manifest["upstream_run_id"] == first.criteria[1].thresholding.run_id


def test_out_dir_defaults_to_the_chains_and_the_chain_may_be_a_path(tmp_path):
    chain = _two_criteria(tmp_path)
    result = run_chain(tmp_path / "cfg" / "chain.yaml", produce=("thresholding",))
    assert result.criteria[1].thresholding.out_dir == tmp_path / "cfg/run/criteria/2/thresholding"
    assert chain.shared.out_dir == str(tmp_path / "cfg" / "run")


def test_progress_and_issues_name_the_criterion(tmp_path, monkeypatch):
    import urbansolarcarver.api_core.chain as chain_module
    real_preprocessing = chain_module.preprocessing

    def preprocessing_that_reports(config, folder):
        with stage_context("preprocessing"):
            report_issue("test_issue", "an issue of the stage")
        return real_preprocessing(config, folder)

    monkeypatch.setattr(chain_module, "preprocessing", preprocessing_that_reports)
    events = []
    context = RunContext(on_progress=lambda stage, done, total: events.append((stage, done, total)))
    result = run_chain(_two_criteria(tmp_path), tmp_path / "run", produce=("thresholding",), context=context)
    assert ("criterion 1", 0, 2) in events and ("criterion 2", 2, 2) in events
    assert [issue.stage for issue in result.issues] == ["criterion 1 (preprocessing)", "criterion 2 (preprocessing)"]
    assert [issue.stage for r in result.criteria for issue in r.issues] == [
        "criterion 1 (preprocessing)", "criterion 2 (preprocessing)"]
    assert len(result.criteria[1].preprocessing.issues) == 1     # not the first criterion's issue as well


def test_a_bad_start_from_or_produce_is_refused(tmp_path):
    chain = chain_scene(tmp_path).chain_config(tmp_path / "cfg", [daylight_on_south(0.6)])
    with pytest.raises(ValueError, match="produce"):
        run_chain(chain, tmp_path / "run", produce=())
    with pytest.raises(ValueError, match="start_from"):
        run_chain(chain, tmp_path / "run", produce=("thresholding",), start_from="massing")


def test_a_single_run_in_the_folder_of_a_chain_does_not_report_the_old_criteria(tmp_path):
    from urbansolarcarver import run_pipeline
    chain = _two_criteria(tmp_path)
    run_chain(chain, tmp_path / "run")
    assert "## Criteria" in (tmp_path / "run/run_report.md").read_text(encoding="utf-8")
    run_pipeline(chain.shared, tmp_path / "run")
    assert "## Criteria" not in (tmp_path / "run/run_report.md").read_text(encoding="utf-8")


def test_re_thresholding_without_a_criterion_preprocessing_names_the_stage_to_rerun(tmp_path):
    with pytest.raises(StageChainError, match="preprocessing"):
        run_chain(_two_criteria(tmp_path), tmp_path / "run", produce=("thresholding",), start_from="thresholding")


def test_a_criterions_scores_in_a_chain_equal_an_unchained_run_of_its_config(tmp_path):
    chain = _two_criteria(tmp_path)
    run_chain(chain, tmp_path / "run")
    alone = preprocessing(chain.criteria[1].config, tmp_path / "alone")
    in_chain = np.load(tmp_path / "run/criteria/2/preprocessing/scores.npy")
    assert np.array_equal(in_chain, np.load(alone.out_dir / "scores.npy"))


def _run_id(folder):
    """The run id in the manifest of a stage folder."""
    return json.loads((folder / "manifest.json").read_text())["run_id"]


def test_tracing_one_criterion_reuses_the_rays_of_the_others(tmp_path):
    out = tmp_path / "run"
    chain = _two_criteria(tmp_path)
    run_chain(chain, out)
    scores_1 = out / "criteria/1/preprocessing/scores.npy"
    mtime_1 = scores_1.stat().st_mtime_ns
    old = {name: _run_id(out / folder) for name, folder in (
        ("thr_1", "criteria/1/thresholding"), ("pre_2", "criteria/2/preprocessing"),
        ("thr_2", "criteria/2/thresholding"), ("export", "exporting"))}
    again = run_chain(chain, out, trace={"2"})
    assert scores_1.stat().st_mtime_ns == mtime_1
    assert _run_id(out / "criteria/1/thresholding") == old["thr_1"]
    assert _run_id(out / "criteria/2/preprocessing") != old["pre_2"]
    assert _run_id(out / "criteria/2/thresholding") != old["thr_2"]
    assert _run_id(out / "exporting") != old["export"]
    first, second = again.criteria
    assert first.preprocessing is None and first.thresholding is None
    assert second.preprocessing is not None and second.thresholding is not None and again.exporting is not None
    # Criterion 2 decided among the voxels criterion 1 kept before, and the chain list still names that run.
    manifest_2 = json.loads((out / "criteria/2/thresholding/manifest.json").read_text())
    assert manifest_2["after_run_id"] == old["thr_1"]
    listed = json.loads((out / "criteria/chain.json").read_text())["criteria"]
    assert [row["thresholding_run_id"] for row in listed] == [old["thr_1"], second.thresholding.run_id]


def test_tracing_the_first_rethresholds_the_ones_after(tmp_path):
    out = tmp_path / "run"
    chain = _two_criteria(tmp_path)
    run_chain(chain, out)
    scores_2 = out / "criteria/2/preprocessing/scores.npy"
    mtime_2 = scores_2.stat().st_mtime_ns
    old_pre_2 = _run_id(out / "criteria/2/preprocessing")
    old_thr_2 = _run_id(out / "criteria/2/thresholding")
    again = run_chain(chain, out, trace={"1"})
    assert scores_2.stat().st_mtime_ns == mtime_2 and _run_id(out / "criteria/2/preprocessing") == old_pre_2
    first, second = again.criteria
    assert first.preprocessing is not None and first.thresholding is not None
    assert second.preprocessing is None and second.thresholding is not None
    assert second.thresholding.run_id != old_thr_2
    manifest_2 = json.loads((out / "criteria/2/thresholding/manifest.json").read_text())
    assert manifest_2["after_run_id"] == first.thresholding.run_id


def test_tracing_a_later_criterion_can_rethreshold_an_earlier_one_without_its_preprocessing(tmp_path):
    out = tmp_path / "run"
    chain = _two_criteria(tmp_path)
    run_chain(chain, out)
    scores_1 = out / "criteria/1/preprocessing/scores.npy"
    mtime_1 = scores_1.stat().st_mtime_ns
    old = {name: _run_id(out / folder) for name, folder in (
        ("pre_1", "criteria/1/preprocessing"), ("thr_1", "criteria/1/thresholding"),
        ("pre_2", "criteria/2/preprocessing"), ("thr_2", "criteria/2/thresholding"))}
    again = run_chain(chain, out, trace={"2"}, threshold_from="1")
    assert scores_1.stat().st_mtime_ns == mtime_1 and _run_id(out / "criteria/1/preprocessing") == old["pre_1"]
    first, second = again.criteria
    assert first.preprocessing is None and first.thresholding is not None
    assert second.preprocessing is not None and second.thresholding is not None
    assert first.thresholding.run_id != old["thr_1"] and _run_id(out / "criteria/2/preprocessing") != old["pre_2"]
    manifest_2 = json.loads((out / "criteria/2/thresholding/manifest.json").read_text())
    assert manifest_2["after_run_id"] == first.thresholding.run_id
    listed = json.loads((out / "criteria/chain.json").read_text())["criteria"]
    assert [row["thresholding_run_id"] for row in listed] == [first.thresholding.run_id, second.thresholding.run_id]


def test_thresholding_from_a_later_criterion_than_the_first_traced_changes_nothing(tmp_path):
    out = tmp_path / "run"
    chain = _two_criteria(tmp_path)
    run_chain(chain, out)
    old_thr_1 = _run_id(out / "criteria/1/thresholding")
    again = run_chain(chain, out, trace={"1"}, threshold_from="2")
    first, second = again.criteria
    assert first.thresholding is not None and first.thresholding.run_id != old_thr_1
    assert second.preprocessing is None and second.thresholding is not None


def test_rethresholding_from_the_second_criterion_keeps_the_first(tmp_path):
    out = tmp_path / "run"
    run_chain(_two_criteria(tmp_path), out)
    scores = [out / f"criteria/{cid}/preprocessing/scores.npy" for cid in ("1", "2")]
    mtimes = [path.stat().st_mtime_ns for path in scores]
    old = {name: _run_id(out / folder) for name, folder in (
        ("thr_1", "criteria/1/thresholding"), ("thr_2", "criteria/2/thresholding"), ("export", "exporting"))}
    again = run_chain(_two_criteria(tmp_path, second=0.8, folder="cfg2"), out, start_from="thresholding", threshold_from="2")
    first, second = again.criteria
    assert first.preprocessing is None and first.thresholding is None
    assert second.preprocessing is None and second.thresholding is not None
    assert [path.stat().st_mtime_ns for path in scores] == mtimes
    assert _run_id(out / "criteria/1/thresholding") == old["thr_1"]
    assert second.thresholding.run_id != old["thr_2"] and _run_id(out / "exporting") != old["export"]
    manifest_2 = json.loads((out / "criteria/2/thresholding/manifest.json").read_text())
    assert manifest_2["after_run_id"] == old["thr_1"]
    listed = json.loads((out / "criteria/chain.json").read_text())["criteria"]
    assert [row["thresholding_run_id"] for row in listed] == [old["thr_1"], second.thresholding.run_id]


def test_rethresholding_from_the_first_criterion_thresholds_the_whole_chain(tmp_path):
    out = tmp_path / "run"
    run_chain(_two_criteria(tmp_path), out)
    old_thr = [_run_id(out / f"criteria/{cid}/thresholding") for cid in ("1", "2")]
    again = run_chain(_two_criteria(tmp_path, folder="cfg2"), out, produce=("thresholding",), start_from="thresholding",
                      threshold_from="1")
    assert all(r.preprocessing is None and r.thresholding is not None for r in again.criteria)
    assert [r.thresholding.run_id for r in again.criteria] != old_thr
    assert all(r.thresholding.run_id != old for r, old in zip(again.criteria, old_thr))


def test_rethresholding_from_a_criterion_after_one_without_thresholding_names_the_folder(tmp_path):
    out = tmp_path / "run"
    chain = _two_criteria(tmp_path)
    run_chain(chain, out, produce=("thresholding",))
    shutil.rmtree(out / "criteria/1/thresholding")
    with pytest.raises(StageChainError, match=r"criteria.1.thresholding"):
        run_chain(chain, out, produce=("thresholding",), start_from="thresholding", threshold_from="2")


def test_thresholding_from_a_criterion_not_in_the_chain_is_refused_when_starting_at_thresholding(tmp_path):
    with pytest.raises(ValueError, match="threshold_from"):
        run_chain(_two_criteria(tmp_path), tmp_path / "run", start_from="thresholding", threshold_from="7")


def test_thresholding_from_a_criterion_not_in_the_chain_is_refused(tmp_path):
    with pytest.raises(ValueError, match="threshold_from"):
        run_chain(_two_criteria(tmp_path), tmp_path / "run", trace={"2"}, threshold_from="7")


def test_tracing_no_criterion_of_the_chain_is_refused(tmp_path):
    chain = _two_criteria(tmp_path)
    for trace in ({"7"}, set()):
        with pytest.raises(ValueError, match="trace"):
            run_chain(chain, tmp_path / "run", trace=trace)


def test_tracing_a_criterion_without_the_preprocessing_of_a_later_one_names_the_folder(tmp_path):
    out = tmp_path / "run"
    chain = _two_criteria(tmp_path)
    run_chain(chain, out, produce=("thresholding",))
    shutil.rmtree(out / "criteria/2/preprocessing")
    with pytest.raises(StageChainError, match=r"criteria.2.preprocessing"):
        run_chain(chain, out, produce=("thresholding",), trace={"1"})
