"""setup_env.py: choosing the PyTorch wheel index for the NVIDIA driver."""
import importlib.util
from pathlib import Path

import pytest

_spec = importlib.util.spec_from_file_location(
    "setup_env", Path(__file__).resolve().parents[1] / "setup_env.py")
setup_env = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(setup_env)

# What the indexes offered on 2026-10-16 (newest Windows torch per index).
OFFERS = {"cu118": (2, 7, 1), "cu121": (2, 5, 1), "cu124": (2, 6, 0), "cu126": (2, 14, 1),
          "cu128": (2, 11, 0), "cu129": (2, 9, 0), "cu130": (2, 14, 1), "cu132": (2, 14, 1)}


def offered(index_url):
    return OFFERS.get(index_url.rstrip("/").rsplit("/", 1)[-1])


def unreachable(index_url):
    return None


@pytest.mark.parametrize("driver, expected_index", [
    ("12.8", "cu126"),   # cu128 stopped at torch 2.11; cu126 has 2.14.1
    ("12.9", "cu126"),   # cu129 stopped at torch 2.9
    ("12.6", "cu126"),
    ("12.4", "cu118"),   # cu118 (torch 2.7.1) is newer than cu124 (2.6.0)
    ("13.2", "cu132"),   # cu130 and cu132 both offer 2.14.1: the higher CUDA wins
    ("13.1", "cu130"),
])
def test_the_index_with_the_newest_torch_the_driver_can_run_is_chosen(driver, expected_index):
    url, description = setup_env.resolve_torch_index(driver, force_cpu=False, newest_torch_on=offered)
    assert url.endswith("/" + expected_index)
    assert "2." in description  # the description names the torch version found


def test_without_answers_the_highest_supported_index_is_used(capsys):
    url, description = setup_env.resolve_torch_index("12.8", force_cpu=False, newest_torch_on=unreachable)
    assert url.endswith("/cu128")
    assert "could not" in description


def test_a_driver_older_than_every_index_gets_cpu_wheels():
    url, description = setup_env.resolve_torch_index("11.4", force_cpu=False, newest_torch_on=offered)
    assert url.endswith("/cpu")


@pytest.mark.parametrize("driver, force_cpu", [(None, False), ("12.8", True)])
def test_no_driver_or_forced_cpu_gets_cpu_wheels(driver, force_cpu):
    url, _ = setup_env.resolve_torch_index(driver, force_cpu=force_cpu, newest_torch_on=offered)
    assert url.endswith("/cpu")


def test_pip_version_text_with_a_local_label_is_read():
    assert setup_env._version_tuple("2.14.1+cu126") == (2, 14, 1)
