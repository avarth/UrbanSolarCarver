"""Tests for the north_deg convention: USC = degrees CLOCKWISE from +Y.

Ladybug uses the opposite (counterclockwise) convention, so the boundary
code must negate the angle.  These tests pin that conversion for all three
places north matters: sun vectors (time-based), sky matrices
(irradiance/benefit), and the tilted-plane octant lookup.
"""
import os
from pathlib import Path

import numpy as np
import pytest
import torch


_EPW = os.environ.get("USC_EPW_PATH", "")
_SKIP_EPW = pytest.mark.skipif(
    not (_EPW and Path(_EPW).is_file()),
    reason="EPW file not available — set USC_EPW_PATH env var to enable",
)


@_SKIP_EPW
def test_sun_vectors_rotate_clockwise_with_north_deg():
    """north_deg=90 (model north = +X) rotates sun vectors 90° CW in plan."""
    from ladybug.analysisperiod import AnalysisPeriod
    from urbansolarcarver.sun import get_sun_vectors

    ap = AnalysisPeriod(st_month=6, st_day=21, st_hour=12,
                        end_month=6, end_day=21, end_hour=12, timestep=1)
    v0 = get_sun_vectors(_EPW, ap.datetimes, min_altitude=5.0, north_deg=0.0).numpy()[0]
    v90 = get_sun_vectors(_EPW, ap.datetimes, min_altitude=5.0, north_deg=90.0).numpy()[0]

    # 90° clockwise in the XY plane: (x, y) -> (y, -x); altitude unchanged.
    np.testing.assert_allclose(v90, [v0[1], -v0[0], v0[2]], atol=1e-5)


def test_sky_matrix_receives_negated_north(monkeypatch):
    """USC north (CW) must be negated before reaching Ladybug SkyMatrix (CCW)."""
    import urbansolarcarver.sky_patches as sp

    captured = {}

    class FakeSky:
        direct_values = np.ones(145, dtype=np.float32)
        diffuse_values = np.ones(145, dtype=np.float32)

    class FakeSkyMatrix:
        @classmethod
        def from_epw(cls, epw_path, hoys=None, north=0, high_density=False,
                     ground_reflectance=0.2):
            captured["north"] = north
            return FakeSky()

    monkeypatch.setattr(sp, "_sky_matrix_cls", FakeSkyMatrix)
    monkeypatch.setattr(os.path, "isfile", lambda p: True)
    weights = sp.compute_EPW_based_weights(
        "irradiance", "dummy.epw", [12], torch.device("cpu"), north=90.0,
    )
    assert captured["north"] == -90.0
    assert weights.shape[0] == 145


class TestTiltedPlaneOctantNorth:
    """The per-octant angle table is indexed by COMPASS direction."""

    def _octant_angle(self, normal_xy, north_deg):
        """Run carve_with_planes with a distinct angle per octant and
        recover the applied angle from the emitted ray direction."""
        from urbansolarcarver.load_config import user_config
        from urbansolarcarver.carving import carve_with_planes

        cfg = user_config(
            max_volume_path="d", test_surface_path="d", out_dir="o",
            mode="tilted_plane",
            tilted_plane_angle_deg=[10, 20, 30, 40, 50, 60, 70, 80],  # N..NW
            voxel_size=1.0, grid_step=1.0, device="cpu", north_deg=north_deg,
        )
        grid = torch.ones((4, 4, 4), dtype=torch.uint8)
        pts = np.array([[2.0, 2.0, 2.0]], dtype=np.float32)
        nrm = np.array([list(normal_xy) + [0.0]], dtype=np.float32)
        _, _, dirs = carve_with_planes(grid, np.zeros(3), 4.0, 4, pts, nrm, cfg)
        return float(np.degrees(np.arcsin(dirs[0, 2])))

    def test_north_zero_uses_model_axes(self):
        assert self._octant_angle((0.0, 1.0), 0.0) == pytest.approx(10, abs=0.1)  # +Y = N
        assert self._octant_angle((1.0, 0.0), 0.0) == pytest.approx(30, abs=0.1)  # +X = E

    def test_rotated_north_shifts_octants(self):
        # north_deg=90: model north points along +X.
        assert self._octant_angle((1.0, 0.0), 90.0) == pytest.approx(10, abs=0.1)  # +X = N
        assert self._octant_angle((0.0, 1.0), 90.0) == pytest.approx(70, abs=0.1)  # +Y = W
