"""The one rule for choosing the compute device (compute_device.py)."""
import pytest
import torch

from urbansolarcarver.compute_device import resolve_compute_device, warp_device_name


@pytest.mark.parametrize("choice", [None, "auto", "AUTO"])
def test_auto_picks_cuda_when_it_is_available(monkeypatch, choice):
    monkeypatch.setattr(torch.cuda, "is_available", lambda: True)
    assert resolve_compute_device(choice) == torch.device("cuda")


@pytest.mark.parametrize("choice", [None, "auto"])
def test_auto_picks_the_cpu_without_cuda(monkeypatch, choice):
    monkeypatch.setattr(torch.cuda, "is_available", lambda: False)
    assert resolve_compute_device(choice) == torch.device("cpu")


def test_an_explicit_cpu_stays_on_the_cpu_when_cuda_is_available(monkeypatch):
    monkeypatch.setattr(torch.cuda, "is_available", lambda: True)
    assert resolve_compute_device("cpu") == torch.device("cpu")


@pytest.mark.parametrize("choice", ["cuda", "cuda:1", torch.device("cuda")])
def test_asking_for_cuda_without_cuda_fails_at_once(monkeypatch, choice):
    monkeypatch.setattr(torch.cuda, "is_available", lambda: False)
    with pytest.raises(RuntimeError, match="CUDA is not available"):
        resolve_compute_device(choice)


def test_a_numbered_cuda_device_is_kept(monkeypatch):
    monkeypatch.setattr(torch.cuda, "is_available", lambda: True)
    assert resolve_compute_device("cuda:1") == torch.device("cuda:1")


def test_an_unknown_device_name_is_rejected():
    with pytest.raises(ValueError, match="gpu"):
        resolve_compute_device("gpu")


def test_a_device_of_another_type_is_rejected():
    with pytest.raises(TypeError):
        resolve_compute_device(0)


@pytest.mark.parametrize("device, expected", [
    (torch.device("cpu"), "cpu"),
    (torch.device("cuda"), "cuda:0"),
    (torch.device("cuda:1"), "cuda:1"),
])
def test_warp_device_names(device, expected):
    assert warp_device_name(device) == expected


def test_a_session_resolves_its_device_with_the_same_rule(monkeypatch):
    from urbansolarcarver.session import CarverSession
    monkeypatch.setattr(torch.cuda, "is_available", lambda: False)
    with pytest.raises(RuntimeError, match="CUDA is not available"):
        CarverSession("cuda")
