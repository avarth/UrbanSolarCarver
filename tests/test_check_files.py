"""The geometries of a run that a sun and sky check traces (check_files.run_geometry_files)."""
import json

import pytest

from urbansolarcarver.check_files import run_geometry_files
from urbansolarcarver.run_context import RunContext, run_context


def _write_manifest(folder, **fields):
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "manifest.json").write_text(json.dumps(fields), encoding="utf-8")


def _write_built_stage(run_folder, stage, mesh_name, upstream_run_id="thr"):
    _write_manifest(run_folder / stage, mesh_path=mesh_name, upstream_run_id=upstream_run_id)
    (run_folder / stage / mesh_name).write_text("mesh", encoding="utf-8")


def _write_analysis(run_folder, voxel_size=2.0):
    _write_manifest(run_folder / "thresholding", run_id="thr", upstream_run_id="pre")
    _write_manifest(run_folder / "preprocessing", run_id="pre", voxel_size=voxel_size)


def test_no_run_folder_and_an_empty_one_have_no_geometries(tmp_path):
    assert run_geometry_files(None) == []
    assert run_geometry_files(tmp_path / "not_there") == []
    assert run_geometry_files(tmp_path) == []


def test_the_envelope_comes_before_the_massing_with_the_voxel_size_of_their_analysis(tmp_path):
    _write_analysis(tmp_path)
    _write_built_stage(tmp_path, "massing", "plates.obj")
    _write_built_stage(tmp_path, "exporting", "export.ply")
    found = run_geometry_files(tmp_path, fallback_voxel_size=9.0)
    assert [(item.name, item.label, item.path, item.surface_tolerance) for item in found] == [
        ("envelope", "Carved envelope", tmp_path / "exporting" / "export.ply", 2.0),
        ("massing", "Building massing", tmp_path / "massing" / "plates.obj", 2.0)]


def test_the_fallback_tolerance_stands_in_when_the_manifests_do_not_chain(tmp_path):
    _write_analysis(tmp_path)
    _write_built_stage(tmp_path, "exporting", "export.ply", upstream_run_id="an earlier thresholding")
    assert run_geometry_files(tmp_path, fallback_voxel_size=9.0)[0].surface_tolerance == 9.0


def test_a_mesh_that_is_gone_leaves_its_geometry_out_without_a_word(tmp_path):
    _write_manifest(tmp_path / "exporting", mesh_path="export.ply")
    context = RunContext()
    with run_context(context):
        assert run_geometry_files(tmp_path, report_unusable=True) == []
    assert context.issues == []


@pytest.mark.parametrize("manifest_text", ["not json", json.dumps({"run_id": "no mesh named"})], ids=["unreadable", "no mesh"])
def test_an_unusable_manifest_is_reported_only_when_asked(tmp_path, manifest_text):
    (tmp_path / "massing").mkdir()
    (tmp_path / "massing" / "manifest.json").write_text(manifest_text, encoding="utf-8")
    context = RunContext()
    with run_context(context):
        assert run_geometry_files(tmp_path) == []
        assert context.issues == []
        assert run_geometry_files(tmp_path, report_unusable=True) == []
    assert [issue.code for issue in context.issues] == ["geometry_manifest_unusable"]
    assert "Building massing" in context.issues[0].message
