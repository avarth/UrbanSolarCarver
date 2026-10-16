"""Tests for warp_kernels.py: Warp availability and kernel warmup."""
import pytest
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


def test_requiring_the_dda_backend_names_why_warp_cannot_run(monkeypatch):
    from urbansolarcarver import warp_kernels
    from urbansolarcarver.errors import WarpBackendUnavailableError
    monkeypatch.setattr(warp_kernels, "_warp_available", False)
    monkeypatch.setattr(warp_kernels, "_warp_unavailable_reason",
                        "Warp failed to initialise (driver too old)")
    with pytest.raises(WarpBackendUnavailableError, match="driver too old") as caught:
        warp_kernels.require_dda_backend(torch.device("cpu"))
    assert "setup_env.py" in str(caught.value)


@pytest.mark.parametrize("mode_settings", [
    {"mode": "daylight"},                                      # sky-patch scoring
    {"mode": "tilted_plane", "tilted_plane_angle_deg": 45.0},  # ray counting
])
def test_preprocessing_stops_when_warp_cannot_run_instead_of_tracing_approximately(
        tmp_path, monkeypatch, mode_settings):
    from _stage_scene import daylight_cube_config
    from urbansolarcarver import api, warp_kernels
    from urbansolarcarver.errors import WarpBackendUnavailableError
    monkeypatch.setattr(warp_kernels, "_warp_available", False)
    monkeypatch.setattr(warp_kernels, "_warp_unavailable_reason", "Warp is not installed")
    config = daylight_cube_config(tmp_path, **mode_settings)
    with pytest.raises(WarpBackendUnavailableError, match="Warp is not installed"):
        api.preprocessing(config, tmp_path / "run" / "preprocessing")
