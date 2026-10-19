"""The engine request core shared by every transport (engine_requests.py)."""
from pathlib import Path

import numpy as np
import pytest
import yaml

from urbansolarcarver.engine_requests import (
    RunRequest, StageRequest, answer_engine_message, config_for_engine_request,
    error_reply_for, handle_engine_request, parse_engine_request,
)
from urbansolarcarver.errors import ConfigError, MalformedEngineRequest
from urbansolarcarver.load_config import build_config_from_mode_starting_values
from urbansolarcarver.session import CarverSession


class _CountingSession:
    """Stands in for a CarverSession: counts the release_memory calls."""

    def __init__(self):
        self.release_calls = 0

    def release_memory(self):
        self.release_calls += 1


def _write_daylight_yaml(tmp_path, vol_path, srf_path):
    cfg_path = tmp_path / "cfg.yaml"
    cfg_path.write_text(yaml.safe_dump({
        "max_volume_path": str(vol_path), "test_surface_path": str(srf_path),
        "out_dir": str(tmp_path / "out"), "mode": "daylight",
        "voxel_size": 2.0, "grid_step": 2.0, "ray_length": 50.0, "device": "cpu",
    }))
    return cfg_path


# ---- build_config_from_mode_starting_values ----------------------------------

def test_starting_values_fill_what_the_values_leave_out(tmp_path):
    config = build_config_from_mode_starting_values({
        "mode": "tilted-plane", "max_volume_path": "v.ply", "test_surface_path": "s.ply",
        "out_dir": str(tmp_path)})
    assert config.mode == "tilted_plane"
    assert config.tilted_plane_angle_deg == 45.0


def test_given_values_win_over_starting_values(tmp_path):
    config = build_config_from_mode_starting_values({
        "mode": "tilted_plane", "max_volume_path": "v.ply", "test_surface_path": "s.ply",
        "out_dir": str(tmp_path), "tilted_plane_angle_deg": 30.0})
    assert config.tilted_plane_angle_deg == 30.0


def test_an_analysis_period_value_wins_over_the_starting_period(tmp_path):
    config = build_config_from_mode_starting_values({
        "mode": "time-based", "epw_path": "w.epw", "out_dir": str(tmp_path),
        "max_volume_path": "v.ply", "test_surface_path": "s.ply",
        "analysis_period": {"st_month": 6, "st_day": 1, "st_hour": 9,
                            "end_month": 6, "end_day": 30, "end_hour": 15}})
    assert (config.start_month, config.start_day, config.start_hour) == (6, 1, 9)
    assert (config.end_month, config.end_day, config.end_hour) == (6, 30, 15)


def test_relative_paths_resolve_against_the_base_folder(tmp_path):
    config = build_config_from_mode_starting_values(
        {"mode": "daylight", "max_volume_path": "inputs/v.ply",
         "test_surface_path": "inputs/s.ply", "out_dir": "run"},
        base_folder=tmp_path)
    assert Path(config.max_volume_path) == tmp_path / "inputs" / "v.ply"
    assert Path(config.out_dir) == tmp_path / "run"


def test_a_missing_mode_is_a_config_error_on_mode():
    with pytest.raises(ConfigError) as caught:
        build_config_from_mode_starting_values({"max_volume_path": "v.ply"})
    assert [e.field for e in caught.value.errors] == ["mode"]


def test_an_unknown_mode_is_a_config_error_from_the_schema(tmp_path):
    with pytest.raises(ConfigError) as caught:
        build_config_from_mode_starting_values({
            "mode": "moonlight", "max_volume_path": "v.ply", "test_surface_path": "s.ply",
            "out_dir": str(tmp_path)})
    assert [e.field for e in caught.value.errors] == ["mode"]


# ---- parse_engine_request -----------------------------------------------------

@pytest.mark.parametrize("message, fragment", [
    ({"cmd": "nope"}, "Unknown command"),
    ({"cmd": "thresholding", "config": "x.yaml"}, "Missing required keys for 'thresholding': ['from']"),
    ({"cmd": "run", "produce": ["exporting"]}, "Missing required keys for 'run': ['run_folder']"),
    (["not", "a", "dict"], "Expected a dict"),
])
def test_malformed_messages_are_rejected_with_a_reason(message, fragment):
    with pytest.raises(MalformedEngineRequest, match=fragment.replace("[", r"\[").replace("]", r"\]")):
        parse_engine_request(message)


def test_the_from_key_becomes_the_upstream_output():
    request = parse_engine_request({"cmd": "massing", "config": "c.yaml", "from": "thr/manifest.json"})
    assert isinstance(request, StageRequest)
    assert request.upstream_output == "thr/manifest.json"


def test_a_run_request_starts_from_preprocessing_unless_told_otherwise():
    request = parse_engine_request({"cmd": "run", "produce": ["exporting"], "run_folder": "r"})
    assert isinstance(request, RunRequest)
    assert request.start_from == "preprocessing"


# ---- config_for_engine_request ------------------------------------------------

def test_without_a_yaml_the_config_comes_from_the_mode_starting_values(tmp_path):
    request = parse_engine_request({"cmd": "run", "produce": ["preprocessing"], "run_folder": "r",
                                    "overrides": ["mode=tilted-plane", "max_volume_path=v.ply",
                                                  "test_surface_path=s.ply", f"out_dir={tmp_path}"]})
    assert config_for_engine_request(request).tilted_plane_angle_deg == 45.0


@pytest.mark.parametrize("overrides", [
    ["mode"],
    {"mode": "daylight", "analysis_period": "not a mapping"},
])
def test_malformed_overrides_are_a_config_error(overrides):
    request = parse_engine_request({"cmd": "run", "produce": ["preprocessing"], "run_folder": "r",
                                    "overrides": overrides})
    with pytest.raises(ConfigError) as caught:
        config_for_engine_request(request)
    assert caught.value.errors[0].field is None


# ---- error_reply_for and answer_engine_message --------------------------------

def test_an_error_reply_keeps_the_text_and_adds_the_type():
    assert error_reply_for(FileNotFoundError("gone")).model_dump(exclude_none=True) == {
        "status": "error", "error": "FileNotFoundError: gone", "error_type": "FileNotFoundError"}


def test_a_config_error_reply_lists_the_invalid_fields(tmp_path):
    reply = answer_engine_message({"cmd": "run", "produce": ["preprocessing"],
                                   "run_folder": str(tmp_path)}, _CountingSession())
    assert reply["status"] == "error" and reply["error_type"] == "ConfigError"
    assert [e["field"] for e in reply["config_errors"]] == ["mode"]


def test_a_malformed_message_gets_an_error_reply_naming_the_problem():
    reply = answer_engine_message({"cmd": "nope"}, _CountingSession())
    assert reply["status"] == "error"
    assert reply["error_type"] == "MalformedEngineRequest"
    assert "Unknown command" in reply["error"]


def test_ping_answers_with_the_process_id():
    import os
    assert answer_engine_message({"cmd": "ping"}, _CountingSession()) == {"status": "ok", "pid": os.getpid()}


def test_memory_is_released_when_a_stage_command_fails(tmp_path):
    session = _CountingSession()
    reply = answer_engine_message({"cmd": "preprocessing", "config": str(tmp_path / "missing.yaml")},
                                  session)
    assert reply["error_type"] == "FileNotFoundError"
    assert session.release_calls == 1


# ---- handle_engine_request on real runs (CPU, tiny scene) ---------------------

def test_a_run_without_a_yaml_runs_the_needed_stages(tmp_path, tmp_mesh_files):
    vol_path, srf_path = tmp_mesh_files
    overrides = ["mode=daylight", f"max_volume_path={vol_path}", f"test_surface_path={srf_path}",
                 f"out_dir={tmp_path / 'run'}", "device=cpu", "voxel_size=2.0", "grid_step=2.0",
                 "ray_length=50.0"]
    with CarverSession(device="cpu") as session:
        reply = answer_engine_message({"cmd": "run", "produce": ["thresholding"],
                                       "run_folder": str(tmp_path / "run"), "overrides": overrides},
                                      session)
    assert reply["status"] == "ok", reply
    assert set(reply["stage_folders"]) == {"preprocessing", "thresholding"}
    assert reply["manifest"].endswith("manifest.json")
    assert (tmp_path / "run" / "thresholding" / "manifest.json").is_file()
    assert reply["issues"] == []


def test_a_run_reply_carries_the_produced_paths(tmp_path, tmp_mesh_files):
    cfg_path = _write_daylight_yaml(tmp_path, *tmp_mesh_files)
    with CarverSession(device="cpu") as session:
        reply = answer_engine_message({"cmd": "run", "produce": ["exporting", "massing"],
                                       "config": str(cfg_path), "run_folder": str(tmp_path / "run")},
                                      session)
    assert reply["status"] == "ok", reply
    assert set(reply["stage_folders"]) == {"preprocessing", "thresholding", "exporting", "massing"}
    assert Path(reply["export_path"]).is_file()
    assert reply["plates_path"].endswith("plates.json")
    assert Path(reply["mesh_path"]).name == "plates.obj"
    assert Path(reply["export_mesh_path"]).name == "plates.ply"        # final_mesh_format's default


def test_a_stage_reply_carries_the_issues_of_that_stage(tmp_path, tmp_mesh_files):
    cfg_path = _write_daylight_yaml(tmp_path, *tmp_mesh_files)
    with CarverSession(device="cpu") as session:
        pre = answer_engine_message({"cmd": "preprocessing", "config": str(cfg_path)}, session)
        assert pre["issues"] == []
        reply = answer_engine_message({"cmd": "thresholding", "config": str(cfg_path),
                                       "from": pre["manifest"], "overrides": ["threshold=1e9"]},
                                      session)
    assert [i["code"] for i in reply["issues"]] == ["nothing_carved"]
    assert reply["issues"][0]["stage"] == "thresholding"
    assert set(reply["issues"][0]) == {"stage", "code", "message"}


def test_massing_runs_after_thresholding_by_stage_commands(tmp_path, tmp_mesh_files):
    cfg_path = _write_daylight_yaml(tmp_path, *tmp_mesh_files)
    with CarverSession(device="cpu") as session:
        pre = answer_engine_message({"cmd": "preprocessing", "config": str(cfg_path)}, session)
        thr = answer_engine_message({"cmd": "thresholding", "config": str(cfg_path),
                                     "from": pre["manifest"]}, session)
        reply = answer_engine_message({"cmd": "massing", "config": str(cfg_path),
                                       "from": thr["manifest"], "overrides": ["final_mesh_format=stl"]}, session)
    assert reply["status"] == "ok", reply
    assert (tmp_path / "out" / "massing" / "plates.json").is_file()
    assert reply["plates_path"].endswith("plates.json")
    assert Path(reply["export_mesh_path"]).name == "plates.stl" and Path(reply["export_mesh_path"]).is_file()


def test_the_voxel_grid_cache_survives_between_requests(tmp_path, tmp_mesh_files):
    cfg_path = _write_daylight_yaml(tmp_path, *tmp_mesh_files)
    with CarverSession(device="cpu") as session:
        first = answer_engine_message({"cmd": "preprocessing", "config": str(cfg_path),
                                       "out_dir": str(tmp_path / "a")}, session)
        cached = [k for k in session.tensors if k.startswith("voxelize_mesh:")]
        assert first["status"] == "ok" and len(cached) == 1
        grid = session.tensors[cached[0]]
        second = answer_engine_message({"cmd": "preprocessing", "config": str(cfg_path),
                                        "out_dir": str(tmp_path / "b")}, session)
        assert session.tensors[cached[0]] is grid  # reused, not rebuilt
    assert second["status"] == "ok"
    np.testing.assert_array_equal(np.load(tmp_path / "a" / "scores.npy"),
                                  np.load(tmp_path / "b" / "scores.npy"))


def test_a_later_run_without_a_yaml_starts_from_thresholding(tmp_path, tmp_mesh_files):
    """Grasshopper's stage-by-stage workflow without a YAML: later stages send the
    mode, the run folder and the incoming paths; the geometry is not read again."""
    vol_path, srf_path = tmp_mesh_files
    run_folder = tmp_path / "run"
    common = ["mode=daylight", f"out_dir={run_folder}", "device=cpu", "voxel_size=2.0",
              "grid_step=2.0", "ray_length=50.0"]
    with CarverSession(device="cpu") as session:
        first = answer_engine_message({"cmd": "run", "produce": ["preprocessing"],
                                       "run_folder": str(run_folder),
                                       "overrides": common + [f"max_volume_path={vol_path}",
                                                              f"test_surface_path={srf_path}"]},
                                      session)
        assert first["status"] == "ok", first
        incoming = run_folder / "incoming"
        reply = answer_engine_message({"cmd": "run", "produce": ["thresholding"],
                                       "start_from": "thresholding", "run_folder": str(run_folder),
                                       "overrides": common + [
                                           f"max_volume_path={incoming / 'max_volume.ply'}",
                                           f"test_surface_path={incoming / 'test_surfaces.ply'}"]},
                                      session)
    assert reply["status"] == "ok", reply
    assert set(reply["stage_folders"]) == {"thresholding"}


def test_handle_reports_progress_through_a_given_run_context(tmp_path, tmp_mesh_files):
    from urbansolarcarver.run_context import RunContext
    cfg_path = _write_daylight_yaml(tmp_path, *tmp_mesh_files)
    seen = []
    context = RunContext(on_progress=lambda stage, done, total: seen.append((stage, done, total)))
    request = parse_engine_request({"cmd": "run", "produce": ["thresholding"],
                                    "config": str(cfg_path), "run_folder": str(tmp_path / "run")})
    with CarverSession(device="cpu") as session:
        reply = handle_engine_request(request, session, context=context)
    assert reply.status == "ok"
    assert ("preprocessing", 0, 1) in seen and ("thresholding", 1, 1) in seen
