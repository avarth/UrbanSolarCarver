"""The one rule for choosing the compute device.

Every place that turns a device choice into a ``torch.device`` (the stages,
the session, the daemon, the weight and voxelization helpers, the kernel
warmup) calls :func:`resolve_compute_device`, and every Warp launch names
its device with :func:`warp_device_name`.
"""
from __future__ import annotations

from typing import Union

import torch

DeviceChoice = Union[str, torch.device, None]


def resolve_compute_device(choice: DeviceChoice = "auto") -> torch.device:
    """Turn a device choice into a ``torch.device``.

    ``None`` or ``"auto"`` (any case) gives CUDA when torch sees a CUDA GPU,
    else the CPU.  ``"cpu"``, ``"cuda"``, ``"cuda:N"`` and a
    ``torch.device`` are taken as given.

    Raises
    ------
    RuntimeError
        If the choice names a CUDA device and torch sees no CUDA GPU.
    ValueError
        If a string names neither ``auto``, ``cpu`` nor a CUDA device.
    TypeError
        If the choice is not a string, a torch.device or None.
    """
    if choice is None or (isinstance(choice, str) and choice.lower() == "auto"):
        return torch.device("cuda" if cuda_is_usable() else "cpu")
    if isinstance(choice, str):
        name = choice.lower()
        if name != "cpu" and name != "cuda" and not name.startswith("cuda:"):
            raise ValueError(f"Unknown compute device {choice!r}: use 'auto', 'cpu' or 'cuda'")
        device = torch.device(name)
    elif isinstance(choice, torch.device):
        device = choice
    else:
        raise TypeError(f"device must be a str, a torch.device or None, not {type(choice).__name__}")
    if device.type == "cuda" and not torch.cuda.is_available():
        raise RuntimeError(f"Device {str(device)!r} was requested but CUDA is not available")
    if device.type == "cuda" and not cuda_device_supported(device.index or 0):
        raise RuntimeError(f"Device {str(device)!r} was requested but {unsupported_gpu_message(device.index or 0)}")
    return device


def cuda_device_supported(index: int = 0, capability=None, arch_list=None) -> bool:
    """Whether this torch build has GPU code for CUDA device *index*.

    torch reports a GPU as available even when its build has no kernels for that GPU's generation: torch 2.14.1 for CUDA
    12.6 stops at sm_90, so an RTX 50-series card (sm_120) failed at its first GPU operation. A build runs on a GPU when it
    has machine code of the same major version and an equal or lower minor (sm_80 runs on sm_86), or PTX of an equal or
    lower version, which the driver compiles for newer GPUs. *capability* and *arch_list* stand in for the device's and the
    build's in tests.
    """
    major, minor = capability if capability is not None else torch.cuda.get_device_capability(index)
    for arch in (arch_list if arch_list is not None else torch.cuda.get_arch_list()):
        kind, _, digits = arch.partition("_")
        if len(digits) < 2 or not digits.isdigit():
            continue                       # sm_90a and other variants run only on their own GPU
        version = (int(digits[:-1]), int(digits[-1]))
        if kind == "sm" and version[0] == major and version[1] <= minor:
            return True
        if kind == "compute" and version <= (major, minor):
            return True
    return False


def unsupported_gpu_message(index: int = 0) -> str:
    """Why the GPU at *index* cannot be used, and what to do."""
    major, minor = torch.cuda.get_device_capability(index)
    return (f"this PyTorch build ({torch.__version__}) has no GPU code for {torch.cuda.get_device_name(index)} "
            f"(compute capability {major}.{minor}); UrbanSolarCarver uses the CPU. Run the setup of the latest release "
            "again: it installs the PyTorch build for this GPU.")


_warned_unsupported = False


def cuda_is_usable() -> bool:
    """Whether torch sees a CUDA GPU and has code for it; logs once why a GPU it sees cannot be used."""
    global _warned_unsupported
    if not torch.cuda.is_available():
        return False
    if cuda_device_supported(0):
        return True
    if not _warned_unsupported:
        _warned_unsupported = True
        import logging
        logging.getLogger(__name__).warning("The GPU is not used: %s", unsupported_gpu_message(0))
    return False


def warp_device_name(device: torch.device) -> str:
    """The Warp name of a torch device: ``"cuda:N"`` (N defaults to 0) or ``"cpu"``."""
    return f"cuda:{device.index or 0}" if device.type == "cuda" else "cpu"
