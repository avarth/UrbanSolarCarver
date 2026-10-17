"""The score layer blob of the local web service."""
import json
import struct
from pathlib import Path

import numpy as np
import pytest

from urbansolarcarver.local_web_service.score_points import build_score_points
from urbansolarcarver.pydantic_schemas import PreprocessingManifest, ThresholdSpec, ThresholdingManifest, schema_to_json


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
        sample_point_count=5, footprint_path="footprint.json")), encoding="utf-8")
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


def decode(blob):
    header_length = struct.unpack("<I", blob[:4])[0]
    header = json.loads(blob[4:4 + header_length])
    body = blob[4 + header_length:]
    count = header["point_count"]
    indices = np.frombuffer(body[:4 * count], "<u4")
    scores = np.frombuffer(body[4 * count:8 * count], "<f4")
    kept = np.frombuffer(body[8 * count:9 * count], "u1") if header["has_mask"] else None
    compared_start = 9 * count if header["has_mask"] else 8 * count
    compared = np.frombuffer(body[compared_start:compared_start + 4 * count], "<f4") if header["has_compared_scores"] else None
    return header, indices, scores, kept, compared


def test_arrays_match_the_header_and_the_occupied_voxels(tmp_path):
    run = write_fake_run(tmp_path)
    header, indices, scores, kept, _ = decode(build_score_points(run))
    assert header["occupied_count"] == header["point_count"] == 18 and header["thinning_step"] == 1
    assert len(indices) == len(scores) == len(kept) == 18 and (np.diff(indices) > 0).all()
    assert header["shape"] == [4, 3, 2] and header["origin"] == [10.0, 20.0, 30.0] and header["voxel_size"] == 2.0
    assert header["scores_kind"] == "violation_count" and header["weight_unit"].startswith("m²·h")
    assert (header["score_min"], header["score_max"]) == (0.0, 17.0)
    assert (scores == indices).all()                          # the fake scores are the flat indices
    assert (kept == (indices % 2 == 0)).all()


def test_the_header_is_padded_so_the_arrays_start_on_a_four_byte_boundary(tmp_path):
    blob = build_score_points(write_fake_run(tmp_path))
    header_length = struct.unpack("<I", blob[:4])[0]
    assert header_length % 4 == 0


def test_above_the_cap_every_kth_voxel_is_kept(tmp_path):
    run = write_fake_run(tmp_path)
    header, indices, _, _, _ = decode(build_score_points(run, cap=5))
    assert header["thinning_step"] == 4 and header["point_count"] == 5      # ceil(18 / 5) = 4, ceil(18 / 4) = 5
    assert header["occupied_count"] == 18
    occupied = np.flatnonzero(np.load(run / "preprocessing" / "voxel_grid.npy").ravel())
    assert (indices == occupied[::4]).all()


def test_without_thresholding_the_kept_array_is_absent(tmp_path):
    header, _, _, kept, compared = decode(build_score_points(write_fake_run(tmp_path, with_mask=False)))
    assert header["has_mask"] is False and kept is None
    assert header["has_compared_scores"] is False and compared is None


def test_without_preprocessing_there_is_no_data(tmp_path):
    assert build_score_points(tmp_path / "run") is None


def test_compared_scores_follow_the_same_indices(tmp_path):
    run = write_fake_run(tmp_path, with_compared_scores=True)   # compared = raw scores + 100
    header, _, scores, _, compared = decode(build_score_points(run, cap=5))
    assert header["has_compared_scores"] is True and np.allclose(compared, scores + 100)


def test_a_thresholding_run_that_was_built_on_an_earlier_preprocessing_run_is_left_out(tmp_path):
    run = write_fake_run(tmp_path, with_compared_scores=True, thresholding_upstream_run_id="an-earlier-run")
    header, _, _, kept, compared = decode(build_score_points(run))
    assert header["has_mask"] is False and header["has_compared_scores"] is False and kept is None and compared is None


def test_a_grid_without_occupied_voxels_gives_no_points(tmp_path):
    run = write_fake_run(tmp_path, with_mask=False)
    np.save(run / "preprocessing" / "voxel_grid.npy", np.zeros((4, 3, 2), dtype=bool))
    header, indices, _, _, _ = decode(build_score_points(run))
    assert header["point_count"] == 0 and header["thinning_step"] == 1 and len(indices) == 0
    assert header["score_min"] is None and header["score_max"] is None


def test_nan_scores_leave_the_header_valid_json_with_the_finite_range(tmp_path):
    run = write_fake_run(tmp_path, with_mask=False)
    scores = np.load(run / "preprocessing" / "scores.npy")
    scores.ravel()[[0, 5]] = (np.nan, np.inf)
    np.save(run / "preprocessing" / "scores.npy", scores)
    blob = build_score_points(run)
    header_length = struct.unpack("<I", blob[:4])[0]
    header_text = blob[4:4 + header_length].decode("utf-8")
    header = json.loads(header_text, parse_constant=lambda constant: pytest.fail(f"{constant} in the header"))
    assert (header["score_min"], header["score_max"]) == (1.0, 17.0)


def test_scores_that_are_all_nan_give_no_range(tmp_path):
    run = write_fake_run(tmp_path, with_mask=False)
    np.save(run / "preprocessing" / "scores.npy", np.full((4, 3, 2), np.nan, dtype=np.float32))
    header = decode(build_score_points(run))[0]
    assert header["score_min"] is None and header["score_max"] is None
