"""The GPU check of compute_device: a GPU torch sees but has no code for (an RTX 50-series card with the cu126 build) is not
used, and the CPU is chosen with a message, instead of failing at the first GPU operation."""
import pytest
import torch

from urbansolarcarver import compute_device

CU126 = ["sm_50", "sm_60", "sm_61", "sm_70", "sm_75", "sm_80", "sm_86", "sm_90"]   # torch 2.14.1+cu126, read 2026-11-16


@pytest.mark.parametrize("capability, supported", [
    ((8, 6), True),     # RTX 3060: sm_86
    ((8, 9), True),     # RTX 40-series: sm_80 code runs on 8.9
    ((9, 0), True),     # H100
    ((7, 5), True),
    ((12, 0), False),   # RTX 50-series
    ((10, 0), False),   # B200
    ((3, 7), False),
])
def test_a_build_runs_on_its_own_generation_and_newer_minors_only(capability, supported):
    assert compute_device.cuda_device_supported(capability=capability, arch_list=CU126) is supported


def test_ptx_code_runs_on_newer_gpus():
    assert compute_device.cuda_device_supported(capability=(12, 0), arch_list=CU126 + ["compute_90"])
    assert not compute_device.cuda_device_supported(capability=(12, 0), arch_list=CU126 + ["sm_90a"])


@pytest.fixture
def unsupported_gpu(monkeypatch):
    monkeypatch.setattr(torch.cuda, "is_available", lambda: True)
    monkeypatch.setattr(torch.cuda, "get_device_capability", lambda index=0: (12, 0))
    monkeypatch.setattr(torch.cuda, "get_arch_list", lambda: list(CU126))
    monkeypatch.setattr(torch.cuda, "get_device_name", lambda index=0: "NVIDIA GeForce RTX 5090")
    monkeypatch.setattr(compute_device, "_warned_unsupported", False)


def test_auto_chooses_the_cpu_for_a_gpu_the_build_has_no_code_for(unsupported_gpu, caplog):
    assert compute_device.resolve_compute_device("auto") == torch.device("cpu")
    assert "RTX 5090" in caplog.text and "compute capability 12.0" in caplog.text


def test_asking_for_cuda_on_such_a_gpu_says_why(unsupported_gpu):
    with pytest.raises(RuntimeError, match="no GPU code for NVIDIA GeForce RTX 5090"):
        compute_device.resolve_compute_device("cuda")


# torch's CUDA 13.0 wheels: TORCH_CUDA_ARCH_LIST="7.5;8.0;8.6;9.0;10.0;12.0+PTX" in PyTorch's build script (pytorch/pytorch
# pull 163585, read 2026-11-18). The setup gives this build to compute capability 10 and up (setup_env.NEW_GPU_CAPABILITY).
CU130 = ["sm_75", "sm_80", "sm_86", "sm_90", "sm_100", "sm_120", "compute_120"]


@pytest.mark.parametrize("capability, supported", [
    ((12, 0), True),    # RTX 50-series
    ((12, 1), True),    # GB10: compute_120 PTX, compiled by the driver
    ((10, 0), True),    # B200
    ((10, 3), True),    # B300: sm_100 code runs on 10.3
    ((8, 6), True),
    ((6, 1), False),    # Pascal: the reason the setup keeps cu126 for GPUs below 10.0
])
def test_the_cuda_13_build_covers_the_gpus_the_setup_gives_it_to(capability, supported):
    assert compute_device.cuda_device_supported(capability=capability, arch_list=CU130) is supported
