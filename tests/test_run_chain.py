"""run_chain: criteria carved in sequence on one voxel grid, then exporting and massing from the last (daylight and
tilted plane on a box with two facades, CPU, no EPW needed). Each test runs preprocessing several times."""
import json

import numpy as np
import pytest

from _chain_scene import chain_scene, daylight_on_east, daylight_on_south, tilted_plane_on_east
from urbansolarcarver import run_chain
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
    rows = [line for line in (tmp_path / "run/run_report.md").read_text(encoding="utf-8").splitlines()
            if line.startswith(("| 1 |", "| 2 |"))]
    assert len(rows) == 2
    assert f"{first.voxels_kept + first.voxels_removed:,}" in rows[0] and f"{first.voxels_kept:,}" in rows[0]
    assert f"{first.voxels_kept:,}" in rows[1] and f"{second.voxels_kept:,}" in rows[1]


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
