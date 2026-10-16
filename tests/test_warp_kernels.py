"""Tests for warp_kernels.py: Warp availability and kernel warmup."""
import torch


class TestWarmupKernels:
    def test_warmup_matches_backend_availability(self):
        """warmup_kernels succeeds exactly when the Warp backend exists on
        the device, and must never raise."""
        from urbansolarcarver.warp_kernels import warmup_kernels, dda_backend_available
        expected = dda_backend_available(torch.device("cpu"))
        assert warmup_kernels("cpu") == expected

    def test_warmup_auto_device(self):
        from urbansolarcarver.warp_kernels import warmup_kernels
        assert isinstance(warmup_kernels(), bool)  # must not raise
