"""Each sky-matrix computation writes its Wea file in a temporary folder of its own (sky_patches.py).

Ladybug's default folder, ``<Ladybug weather folder>/sky_matrices/<city>.wea``, is one file for every process on the
machine; two computations for the same city at once could read each other's input.
"""
import tempfile
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pytest
import torch

from urbansolarcarver.sky_patches import compute_EPW_based_weights

WINTER_HOURS = list(range(0, 1416))         # January and February
SUMMER_HOURS = list(range(4344, 5088))      # July


@pytest.fixture
def watched_folders(tmp_path, monkeypatch):
    """Ladybug's weather folder and Python's temporary folder, both moved under tmp_path for the test."""
    from ladybug.config import folders
    shared_weather_folder = tmp_path / "ladybug_weather"
    temporary_folder = tmp_path / "temporary"
    shared_weather_folder.mkdir()
    temporary_folder.mkdir()
    monkeypatch.setattr(folders, "default_epw_folder", str(shared_weather_folder))
    monkeypatch.setattr(tempfile, "tempdir", str(temporary_folder))
    return shared_weather_folder, temporary_folder


def irradiance_weights(epw_path, hours) -> np.ndarray:
    return compute_EPW_based_weights("irradiance", str(epw_path), hours, torch.device("cpu")).numpy()


@pytest.mark.slow
def test_two_computations_at_once_give_the_weights_of_each_alone(example_epw_path, watched_folders):
    shared_weather_folder, temporary_folder = watched_folders
    winter_alone = irradiance_weights(example_epw_path, WINTER_HOURS)
    summer_alone = irradiance_weights(example_epw_path, SUMMER_HOURS)
    # gendaymtx runs as a separate process, so the two threads compute at the same time. With one shared folder,
    # 9 rounds in 10 gave a thread the other's weights; three rounds make a pass by chance unlikely.
    for _ in range(3):
        with ThreadPoolExecutor(max_workers=2) as pool:
            winter_at_once = pool.submit(irradiance_weights, example_epw_path, WINTER_HOURS)
            summer_at_once = pool.submit(irradiance_weights, example_epw_path, SUMMER_HOURS)
            np.testing.assert_array_equal(winter_at_once.result(), winter_alone)
            np.testing.assert_array_equal(summer_at_once.result(), summer_alone)
    assert not np.array_equal(winter_alone, summer_alone)
    assert list(shared_weather_folder.iterdir()) == []
    assert list(temporary_folder.iterdir()) == []


def test_benefit_mode_leaves_nothing_behind(example_epw_path, watched_folders):
    shared_weather_folder, temporary_folder = watched_folders
    weights = compute_EPW_based_weights("benefit", str(example_epw_path), WINTER_HOURS + SUMMER_HOURS,
                                        torch.device("cpu"), include_harm=True)
    assert weights.shape == (145,)
    assert list(shared_weather_folder.iterdir()) == []
    assert list(temporary_folder.iterdir()) == []
