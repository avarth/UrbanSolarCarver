"""The run report of a chain: the Criteria table, the Chain section and the total time, from stage folders written by hand
(no chain is run)."""
import json

from urbansolarcarver.api_core._reporting import generate_run_report

VOXEL_SIZE = 2.0
# id, name, mode, method, resolved cutoff, voxels at start, voxels kept, preprocessing seconds, thresholding seconds
CRITERIA = [
    ("1", "South daylight", "daylight", "carve_fraction", 278.1, 1000, 800, 10.0, 1.0),
    ("2", "East daylight", "daylight", "cutoff", 0.0, 800, 400, 20.0, 2.0),
]


def _write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def _report_folder(tmp_path, criteria=CRITERIA, exporting_seconds=3.0, massing_seconds=4.0):
    run = tmp_path / "run"
    listed = []
    for cid, name, mode, method, cutoff, started, kept, pre_s, thr_s in criteria:
        folder = run / "criteria" / cid
        _write(folder / "thresholding/manifest.json", {"run_id": f"thr-{cid}"})
        _write(folder / "thresholding/diagnostics/diagnostic.json", {
            "threshold_method": method, "threshold_value": cutoff, "voxels_at_start": started, "voxels_kept": kept,
            "score_unit": "", "timings": {"wall_seconds": thr_s}})
        _write(folder / "preprocessing/manifest.json", {"voxel_size": VOXEL_SIZE})
        _write(folder / "preprocessing/diagnostics/diagnostic.json", {"timings": {"wall_seconds": pre_s}})
        listed.append({"id": cid, "name": name, "mode": mode, "thresholding_run_id": f"thr-{cid}"})
    _write(run / "criteria/chain.json", {"criteria": listed})
    _write(run / "exporting/diagnostics/diagnostic.json", {"timings": {"wall_seconds": exporting_seconds}})
    _write(run / "massing/diagnostics/diagnostic.json", {"timings": {"wall_seconds": massing_seconds}})
    return run


def _report(tmp_path, **kwargs):
    run = _report_folder(tmp_path, **kwargs)
    last = run / f"criteria/{kwargs.get('criteria', CRITERIA)[-1][0]}"
    return generate_run_report(run, last / "preprocessing", last / "thresholding", exporting_dir=run / "exporting",
                               massing_dir=run / "massing").read_text(encoding="utf-8")


def test_the_run_report_ends_the_criteria_with_the_chain_summary(tmp_path):
    report = _report(tmp_path)
    criteria_at, chain_at = report.index("## Criteria"), report.index("## Chain")
    assert criteria_at < chain_at < report.index("## Preprocessing")
    chain = report[chain_at:report.index("## Preprocessing")]
    # 1000 voxels of 8 m³ at the start; 800 and 400 voxels kept.
    assert "8,000.0 m³" in chain
    assert "| 1 | South daylight | 6,400.0 | 80.0 |" in chain
    assert "| 2 | East daylight | 3,200.0 | 40.0 |" in chain
    assert chain.rstrip().endswith("| 2 | East daylight | 3,200.0 | 40.0 |")      # the last row is what the chain kept


def test_the_chain_summary_is_left_out_when_a_criterion_has_no_voxel_size(tmp_path):
    run = _report_folder(tmp_path)
    (run / "criteria/2/preprocessing/manifest.json").unlink()
    report = generate_run_report(run, run / "criteria/2/preprocessing", run / "criteria/2/thresholding").read_text(encoding="utf-8")
    assert "## Criteria" in report and "## Chain" not in report


def test_the_report_of_a_one_criterion_chain_has_no_chain_section_or_note(tmp_path):
    report = _report(tmp_path, criteria=CRITERIA[:1])
    assert "## Criteria" in report and "## Chain" not in report and "Over the" not in report
    # 11 s for the criterion, 3 for exporting, 4 for massing.
    assert "**Total time:** 18.0s" in report


def test_the_total_time_note_names_the_stages_that_were_added(tmp_path):
    run = _report_folder(tmp_path)
    last = run / "criteria/2"
    both = generate_run_report(run, last / "preprocessing", last / "thresholding", exporting_dir=run / "exporting",
                               massing_dir=run / "massing").read_text(encoding="utf-8")
    exporting_only = generate_run_report(run, last / "preprocessing", last / "thresholding",
                                         exporting_dir=run / "exporting").read_text(encoding="utf-8")
    neither = generate_run_report(run, last / "preprocessing", last / "thresholding").read_text(encoding="utf-8")
    assert "- Over the 2 criteria (preprocessing and thresholding of each), exporting and massing" in both
    assert "- Over the 2 criteria (preprocessing and thresholding of each), exporting\n" in exporting_only + "\n"
    assert "**Total time:** 36.0s" in exporting_only
    assert "- Over the 2 criteria (preprocessing and thresholding of each)\n" in neither + "\n"
    assert "**Total time:** 33.0s" in neither


def test_a_missing_value_in_the_criteria_table_is_a_hyphen(tmp_path):
    run = _report_folder(tmp_path)
    (run / "criteria/2/thresholding/diagnostics/diagnostic.json").unlink()
    last = run / "criteria/2"
    report = generate_run_report(run, last / "preprocessing", last / "thresholding").read_text(encoding="utf-8")
    assert "| 2 | East daylight | daylight | - | - | - | - |" in report
    assert "—" not in report


def test_a_missing_weather_file_or_mesh_path_is_a_hyphen(tmp_path):
    run = _report_folder(tmp_path)
    last = run / "criteria/2"
    _write(last / "preprocessing/diagnostics/config_snapshot.json", {"mode": "time-based", "voxel_size": VOXEL_SIZE, "epw_path": None})
    _write(run / "exporting/diagnostics/diagnostic.json", {"vertices": 3, "triangles": 1, "timings": {"wall_seconds": 3.0}})
    report = generate_run_report(run, last / "preprocessing", last / "thresholding", exporting_dir=run / "exporting").read_text(encoding="utf-8")
    assert "| EPW | - |" in report
    assert "- **Output mesh:** `-`" in report
    assert "—" not in report


def test_the_run_report_total_time_covers_the_chain(tmp_path):
    report = _report(tmp_path)
    # (10 + 1) + (20 + 2) for the criteria, 3 for exporting, 4 for massing.
    assert "**Total time:** 40.0s" in report


def test_a_report_without_a_chain_keeps_its_own_total_time(tmp_path):
    folder = tmp_path / "single"
    _write(folder / "pre/diagnostics/diagnostic.json", {"timings": {"wall_seconds": 5.0}})
    _write(folder / "thr/diagnostics/diagnostic.json", {"timings": {"wall_seconds": 1.0}})
    report = generate_run_report(folder, folder / "pre", folder / "thr").read_text(encoding="utf-8")
    assert "**Total time:** 6.0s" in report and "## Chain" not in report


def test_the_criteria_table_separates_rule_and_cutoff(tmp_path):
    report = _report(tmp_path)
    assert "| # | Name | Mode | Rule | Cutoff | Voxels at start | Voxels kept |" in report
    assert "| 1 | South daylight | daylight | carve_fraction | 278.1 | 1,000 | 800 |" in report
    assert "| 2 | East daylight | daylight | cutoff | 0 | 800 | 400 |" in report
    assert "carve_fraction 278.1" not in report


def test_the_cutoff_has_the_score_unit_beside_it(tmp_path):
    criteria = [("1", "Time", "time-based", "cutoff", 12.5, 100, 50, 1.0, 1.0)]
    run = _report_folder(tmp_path, criteria=criteria)
    _write(run / "criteria/1/thresholding/diagnostics/diagnostic.json", {
        "threshold_method": "cutoff", "threshold_value": 12.5, "voxels_at_start": 100, "voxels_kept": 50,
        "score_unit": "m²·h", "timings": {"wall_seconds": 1.0}})
    report = generate_run_report(run, run / "criteria/1/preprocessing", run / "criteria/1/thresholding").read_text(encoding="utf-8")
    assert "| 1 | Time | time-based | cutoff | 12.5 m²·h | 100 | 50 |" in report
