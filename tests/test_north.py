"""Tests for the north_deg convention: USC = degrees CLOCKWISE from +Y.

Ladybug uses the opposite (counterclockwise) convention, so the boundary
code must negate the angle.  These tests pin that conversion for all three
places north matters: sun vectors (time-based), sky matrices
(irradiance/benefit), and the tilted-plane octant lookup.
"""
import numpy as np
import pytest
import torch


def test_sun_vectors_rotate_clockwise_with_north_deg(example_epw_path):
    """north_deg=90 (model north = +X) rotates sun vectors 90° CW in plan."""
    from ladybug.analysisperiod import AnalysisPeriod
    from urbansolarcarver.sun import get_sun_vectors

    ap = AnalysisPeriod(st_month=6, st_day=21, st_hour=12,
                        end_month=6, end_day=21, end_hour=12, timestep=1)
    v0 = get_sun_vectors(str(example_epw_path), ap.datetimes, min_altitude=5.0, north_deg=0.0).numpy()[0]
    v90 = get_sun_vectors(str(example_epw_path), ap.datetimes, min_altitude=5.0, north_deg=90.0).numpy()[0]

    # 90° clockwise in the XY plane: (x, y) -> (y, -x); altitude unchanged.
    np.testing.assert_allclose(v90, [v0[1], -v0[0], v0[2]], atol=1e-5)


@pytest.mark.parametrize("north_deg", [0.0, 90.0, 200.0])
def test_the_brightest_sky_patch_of_a_clear_hour_is_where_the_sun_is(example_epw_path, north_deg):
    """The sky weights turn with north_deg as the sun vectors do: on a clear winter noon (28 Jan 12:00 in the bundled
    Denver file, sun altitude 32°) the patch with the most irradiance is the one the sun lies in. Measured: 4° at
    north 0 and 90, 12° at 200 (a patch spans up to 20° of azimuth). Weights left unturned put the sun 74° away at
    north 90."""
    from ladybug.dt import DateTime
    from urbansolarcarver.sky_patches import compute_EPW_based_weights, fetch_tregenza_patch_directions
    from urbansolarcarver.sun import get_sun_vectors

    hoy = 660
    cpu = torch.device("cpu")
    weights = compute_EPW_based_weights("irradiance", str(example_epw_path), [hoy], cpu, north=north_deg).numpy()
    sun = get_sun_vectors(str(example_epw_path), [DateTime.from_hoy(hoy)], min_altitude=1.0, north_deg=north_deg)
    sun = sun.numpy()[0] / np.linalg.norm(sun.numpy()[0])
    brightest = fetch_tregenza_patch_directions(cpu).numpy()[weights.argmax()]
    assert np.degrees(np.arccos(np.clip(brightest @ sun, -1.0, 1.0))) < 15.0


class TestTiltedPlaneOctantNorth:
    """The per-octant angle table is indexed by COMPASS direction."""

    def _octant_angle(self, normal_xy, north_deg):
        """Run carve_with_planes with a distinct angle per octant and
        recover the applied angle from the emitted ray direction."""
        from urbansolarcarver.load_config import user_config
        from urbansolarcarver.carving import carve_with_planes
        from urbansolarcarver.stage_settings import PreprocessingSettings

        cfg = user_config(
            max_volume_path="d", test_surface_path="d", out_dir="o",
            mode="tilted_plane",
            tilted_plane_angle_deg=[10, 20, 30, 40, 50, 60, 70, 80],  # N..NW
            voxel_size=1.0, grid_step=1.0, device="cpu", north_deg=north_deg,
        )
        settings = PreprocessingSettings.from_config(cfg)
        grid = torch.ones((4, 4, 4), dtype=torch.uint8)
        pts = np.array([[2.0, 2.0, 2.0]], dtype=np.float32)
        nrm = np.array([list(normal_xy) + [0.0]], dtype=np.float32)
        _, _, dirs = carve_with_planes(
            grid, np.zeros(3), 4.0, 4, pts, nrm, settings, ray_batch_size=cfg.ray_batch_size)
        return float(np.degrees(np.arcsin(dirs[0, 2])))

    def test_north_zero_uses_model_axes(self):
        assert self._octant_angle((0.0, 1.0), 0.0) == pytest.approx(10, abs=0.1)  # +Y = N
        assert self._octant_angle((1.0, 0.0), 0.0) == pytest.approx(30, abs=0.1)  # +X = E

    def test_rotated_north_shifts_octants(self):
        # north_deg=90: model north points along +X.
        assert self._octant_angle((1.0, 0.0), 90.0) == pytest.approx(10, abs=0.1)  # +X = N
        assert self._octant_angle((0.0, 1.0), 90.0) == pytest.approx(70, abs=0.1)  # +Y = W
