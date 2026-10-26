"""The score layer blob of the local web service."""
import json
import shutil
import struct

import numpy as np
import pytest

from local_web_test_support import write_fake_run
from urbansolarcarver.local_web_service.project_names import ProjectError
from urbansolarcarver.local_web_service.score_points import build_carved_by_criterion, build_score_points


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


def test_arrays_match_the_header_and_the_occupied_voxels(project_with_inputs):
    store, name = project_with_inputs
    write_fake_run(store.open(name))
    header, indices, scores, kept, _ = decode(build_score_points(store, name))
    assert header["occupied_count"] == header["point_count"] == 18 and header["thinning_step"] == 1
    assert len(indices) == len(scores) == len(kept) == 18 and (np.diff(indices) > 0).all()
    assert header["shape"] == [4, 3, 2] and header["origin"] == [10.0, 20.0, 30.0] and header["voxel_size"] == 2.0
    assert header["scores_kind"] == "violation_count" and header["score_unit"] == "m²·h"
    assert header["mode"] == "time-based"
    assert (header["score_min"], header["score_max"]) == (0.0, 17.0)
    assert (scores == indices).all()                          # the fake scores are the flat indices
    assert (kept == (indices % 2 == 0)).all()


def test_the_header_is_padded_so_the_arrays_start_on_a_four_byte_boundary(project_with_inputs):
    store, name = project_with_inputs
    write_fake_run(store.open(name))
    blob = build_score_points(store, name)
    header_length = struct.unpack("<I", blob[:4])[0]
    assert header_length % 4 == 0


def test_above_the_cap_every_kth_voxel_is_kept(project_with_inputs):
    store, name = project_with_inputs
    run = write_fake_run(store.open(name))
    header, indices, _, _, _ = decode(build_score_points(store, name, cap=5))
    assert header["thinning_step"] == 4 and header["point_count"] == 5      # ceil(18 / 5) = 4, ceil(18 / 4) = 5
    assert header["occupied_count"] == 18
    occupied = np.flatnonzero(np.load(run / "criteria" / "1" / "preprocessing" / "voxel_grid.npy").ravel())
    assert (indices == occupied[::4]).all()


def test_without_thresholding_the_kept_array_is_absent(project_with_inputs):
    store, name = project_with_inputs
    write_fake_run(store.open(name), with_mask=False)
    header, _, _, kept, compared = decode(build_score_points(store, name))
    assert header["has_mask"] is False and kept is None
    assert header["has_compared_scores"] is False and compared is None


def test_without_preprocessing_there_is_no_data(project_with_inputs):
    store, name = project_with_inputs
    with pytest.raises(ProjectError) as error:
        build_score_points(store, name)
    assert error.value.status_code == 404


def test_compared_scores_follow_the_same_indices(project_with_inputs):
    store, name = project_with_inputs
    write_fake_run(store.open(name), with_compared_scores=True)   # compared = raw scores + 100
    header, _, scores, _, compared = decode(build_score_points(store, name, cap=5))
    assert header["has_compared_scores"] is True and np.allclose(compared, scores + 100)


def test_the_highest_compared_score_is_that_of_all_occupied_voxels_not_only_the_points(project_with_inputs):
    store, name = project_with_inputs
    write_fake_run(store.open(name), with_compared_scores=True)   # compared = raw scores + 100
    header, _, _, _, compared = decode(build_score_points(store, name, cap=5))
    assert header["compared_score_max"] == header["score_max"] + 100 == 117.0
    assert compared.max() < 117.0                               # the thinned points miss the highest voxel


def test_without_compared_scores_there_is_no_highest_compared_score(project_with_inputs):
    store, name = project_with_inputs
    write_fake_run(store.open(name))
    header = decode(build_score_points(store, name))[0]
    assert header["has_compared_scores"] is False and header["compared_score_max"] is None


def test_a_thresholding_run_that_was_built_on_an_earlier_preprocessing_run_is_left_out(project_with_inputs):
    store, name = project_with_inputs
    write_fake_run(store.open(name), with_compared_scores=True, thresholding_upstream_run_id="an-earlier-run")
    header, _, _, kept, compared = decode(build_score_points(store, name))
    assert header["has_mask"] is False and header["has_compared_scores"] is False and kept is None and compared is None
    assert header["compared_score_max"] is None


def test_a_grid_without_occupied_voxels_gives_no_points(project_with_inputs):
    store, name = project_with_inputs
    run = write_fake_run(store.open(name), with_mask=False)
    np.save(run / "criteria" / "1" / "preprocessing" / "voxel_grid.npy", np.zeros((4, 3, 2), dtype=bool))
    header, indices, _, _, _ = decode(build_score_points(store, name))
    assert header["point_count"] == 0 and header["thinning_step"] == 1 and len(indices) == 0
    assert header["score_min"] is None and header["score_max"] is None


def test_nan_scores_leave_the_header_valid_json_with_the_finite_range(project_with_inputs):
    store, name = project_with_inputs
    run = write_fake_run(store.open(name), with_mask=False)
    scores = np.load(run / "criteria" / "1" / "preprocessing" / "scores.npy")
    scores.ravel()[[0, 5]] = (np.nan, np.inf)
    np.save(run / "criteria" / "1" / "preprocessing" / "scores.npy", scores)
    blob = build_score_points(store, name)
    header_length = struct.unpack("<I", blob[:4])[0]
    header_text = blob[4:4 + header_length].decode("utf-8")
    header = json.loads(header_text, parse_constant=lambda constant: pytest.fail(f"{constant} in the header"))
    assert (header["score_min"], header["score_max"]) == (1.0, 17.0)


def test_scores_that_are_all_nan_give_no_range(project_with_inputs):
    store, name = project_with_inputs
    run = write_fake_run(store.open(name), with_mask=False)
    np.save(run / "criteria" / "1" / "preprocessing" / "scores.npy", np.full((4, 3, 2), np.nan, dtype=np.float32))
    header = decode(build_score_points(store, name))[0]
    assert header["score_min"] is None and header["score_max"] is None


# ---- Criteria: the score layer of one criterion, and who removed each voxel ----

@pytest.fixture
def chain_of_two(project_with_inputs):
    """Criteria "1" and "2" after a fake run: criterion 1 kept the occupied voxels with an even flat index, criterion 2 those of
    them with an index divisible by 4; the store and the name."""
    store, name = project_with_inputs
    store.add_criterion(name, "daylight")
    flat = np.arange(24).reshape(4, 3, 2)
    kept_by_first = (flat < 18) & (flat % 2 == 0)
    write_fake_run(store.open(name), mask=kept_by_first)
    write_fake_run(store.open(name), criterion_id="2", mask=kept_by_first & (flat % 4 == 0), after_criterion_id="1")
    return store, name


def test_score_points_default_to_the_last_active_criterion(chain_of_two):
    store, name = chain_of_two
    _, indices, _, kept, _ = decode(build_score_points(store, name))
    assert (kept == (indices % 4 == 0)).all()
    store.update_criterion(name, "2", bypassed=True)
    _, indices, _, kept, _ = decode(build_score_points(store, name))
    assert (kept == (indices % 2 == 0)).all()


def test_score_points_of_a_chosen_criterion(chain_of_two):
    store, name = chain_of_two
    _, indices, _, kept, _ = decode(build_score_points(store, name, "1"))
    assert (kept == (indices % 2 == 0)).all()
    with pytest.raises(ProjectError) as error:
        build_score_points(store, name, "7")
    assert error.value.status_code == 404 and "'7'" in str(error.value)


def decode_carved_by_criterion(blob):
    header_length = struct.unpack("<I", blob[:4])[0]
    header = json.loads(blob[4:4 + header_length])
    return header, np.frombuffer(blob[4 + header_length:], "u1").reshape(header["shape"])


def test_carved_by_criterion_names_who_removed_each_voxel(chain_of_two):
    store, name = chain_of_two
    blob = build_carved_by_criterion(store, name)
    header, carved = decode_carved_by_criterion(blob)
    assert header["shape"] == [4, 3, 2] and header["criterion_ids"] == ["1", "2"]
    assert header["origin"] == [10.0, 20.0, 30.0] and header["voxel_size"] == 2.0
    assert struct.unpack("<I", blob[:4])[0] % 4 == 0 and len(carved.ravel()) == 24
    flat = np.arange(24).reshape(4, 3, 2)
    expected = np.zeros((4, 3, 2), dtype="u1")
    expected[(flat < 18) & (flat % 2 == 1)] = 1                # occupied, not kept by criterion 1
    expected[(flat < 18) & (flat % 2 == 0) & (flat % 4 != 0)] = 2   # kept by criterion 1, not by criterion 2
    assert (carved == expected).all()                           # kept by both, or empty: 0


def test_carved_by_criterion_leaves_out_a_bypassed_criterion(chain_of_two):
    store, name = chain_of_two
    store.update_criterion(name, "1", bypassed=True)
    header, carved = decode_carved_by_criterion(build_carved_by_criterion(store, name))
    flat = np.arange(24).reshape(4, 3, 2)
    assert header["criterion_ids"] == ["2"]
    assert (carved[(flat < 18) & (flat % 4 != 0)] == 1).all() and (carved[(flat < 18) & (flat % 4 == 0)] == 0).all()


def test_carved_by_criterion_is_not_available_without_the_masks_of_every_criterion(chain_of_two):
    store, name = chain_of_two
    store.update_criterion(name, "2", name="East facade")
    shutil.rmtree(store.open(name) / "run" / "criteria" / "2" / "thresholding")
    with pytest.raises(ProjectError) as error:
        build_carved_by_criterion(store, name)
    assert error.value.status_code == 404
    assert str(error.value) == "The criterion 'East facade' has no results yet: run the analysis first."


def test_carved_by_criterion_is_not_available_when_the_criteria_have_other_grids(chain_of_two):
    store, name = chain_of_two
    run = store.open(name) / "run"
    np.save(run / "criteria" / "2" / "thresholding" / "mask.npy", np.zeros((5, 3, 2), dtype=bool))
    with pytest.raises(ProjectError) as error:
        build_carved_by_criterion(store, name)
    assert error.value.status_code == 404


def test_a_mask_that_cannot_be_read_is_not_available_like_a_missing_one(chain_of_two):
    store, name = chain_of_two
    (store.open(name) / "run" / "criteria" / "2" / "thresholding" / "mask.npy").write_bytes(b"not an array")
    for build in (build_carved_by_criterion, build_score_points):
        with pytest.raises(ProjectError) as error:
            build(store, name)
        assert error.value.status_code == 404
