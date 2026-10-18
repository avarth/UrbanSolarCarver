"""Background preparation of the compute device, started when ``usc ui`` starts.

Warp compiles its kernels on first use, which takes seconds. ``GpuWarmUp`` does that on a daemon thread
while the person opens a project and adds files, and reports how far it has come. Nothing in the service
waits for it: a run started before it ends only pays the compile time itself.
Importing this module does not import torch or Warp; the warm-up thread does.
"""
from __future__ import annotations

import logging
import threading
from typing import Callable

from .api_models import WarmUpState

_log = logging.getLogger(__name__)

# Takes the device choice ("auto", "cpu", "cuda"); returns the name of the CUDA device it prepared,
# or None when it prepared the CPU. Raises when the device cannot be prepared.
WarmUpFunction = Callable[[str], str | None]
# Tells whether torch sees a CUDA device, whatever device was chosen.
CudaAvailableFunction = Callable[[], bool]


def prepare_compute_device(device: str) -> str | None:
    """Compile the Warp kernels on the device a run would use; the CUDA device name, or None for the CPU."""
    import torch

    from ..compute_device import resolve_compute_device
    from ..warp_kernels import require_dda_backend, warmup_kernels

    resolved_device = resolve_compute_device(device)
    require_dda_backend(resolved_device)    # raises WarpBackendUnavailableError with the reason and the repair
    if not warmup_kernels(resolved_device):
        raise RuntimeError(f"The Warp kernels could not be compiled for device '{resolved_device}' ahead of time; "
                           "they will compile when the first run needs them.")
    return torch.cuda.get_device_name(resolved_device) if resolved_device.type == "cuda" else None


def cuda_is_available() -> bool:
    """Whether torch sees a CUDA device, also when the CPU was chosen."""
    import torch

    return torch.cuda.is_available()


class GpuWarmUp:
    """Runs the device preparation once on a daemon thread and reports its state."""

    def __init__(self, device: str, warm_up_function: WarmUpFunction | None = None,
                 cuda_available_function: CudaAvailableFunction | None = None):
        self._device = device
        self._warm_up_function = warm_up_function or prepare_compute_device
        self._cuda_available_function = cuda_available_function or cuda_is_available
        self._state = WarmUpState(state="not_started")
        self._lock = threading.Lock()

    def start(self) -> None:
        """Start the preparation; a second call does nothing."""
        with self._lock:
            if self._state.state != "not_started":
                return
            self._state = WarmUpState(state="running")
        threading.Thread(target=self._run, name="gpu-warm-up", daemon=True).start()

    def _cuda_available_after_cpu_warm_up(self) -> bool | None:
        """Whether a CUDA device exists, for a CPU that is prepared; None when torch cannot tell (the CPU still runs)."""
        try:
            return self._cuda_available_function()
        except Exception as error:
            _log.warning("Could not tell whether a CUDA device exists: %s", error)
            return None

    def state(self) -> WarmUpState:
        with self._lock:
            return self._state

    def _run(self) -> None:
        try:
            device_name = self._warm_up_function(self._device)
        except Exception as error:      # whatever went wrong is shown to the person; runs are not blocked by it
            _log.warning("The compute device warm-up failed: %s", error)
            finished = WarmUpState(state="failed", problem=str(error))
        else:
            if device_name is None:
                finished = WarmUpState(state="cpu", cuda_available=self._cuda_available_after_cpu_warm_up())
            else:
                finished = WarmUpState(state="ready", device_name=device_name, cuda_available=True)
        with self._lock:
            self._state = finished
