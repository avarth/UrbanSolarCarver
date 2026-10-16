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
        return torch.device("cuda" if torch.cuda.is_available() else "cpu")
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
    return device


def warp_device_name(device: torch.device) -> str:
    """The Warp name of a torch device: ``"cuda:N"`` (N defaults to 0) or ``"cpu"``."""
    return f"cuda:{device.index or 0}" if device.type == "cuda" else "cpu"
