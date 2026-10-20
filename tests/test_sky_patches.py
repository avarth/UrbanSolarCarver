"""Tregenza patch geometry in sky_patches.py."""
import numpy as np


def test_solid_angles_cover_the_hemisphere_once():
    from urbansolarcarver.sky_patches import tregenza_solid_angles
    omega = tregenza_solid_angles()
    assert omega.shape == (145,)
    np.testing.assert_allclose(omega.sum(), 2 * np.pi, rtol=1e-6)


def test_solid_angles_unaffected_by_ladybug_reinhart_cache():
    # ladybug-core's ViewSphere.tregenza_solid_angles returns the Reinhart
    # list once reinhart_solid_angles has been read on the same object.
    from ladybug.viewsphere import view_sphere
    from urbansolarcarver.sky_patches import tregenza_solid_angles
    _ = view_sphere.reinhart_solid_angles
    assert tregenza_solid_angles().shape == (145,)


def test_daylight_weights_are_shares_of_the_overcast_sky():
    """CIE overcast brightness times solid angle, scaled to sum to 1: a sample point whose whole sky is hidden counts its whole
    area, so a daylight score is in m² of weighted sky (as Night cooling's weights, which also sum to 1)."""
    import torch
    from urbansolarcarver.sky_patches import (
        compute_EPW_based_weights, fetch_tregenza_patch_directions, tregenza_solid_angles)
    weights = compute_EPW_based_weights("daylight", "", [], device=torch.device("cpu")).numpy()
    np.testing.assert_allclose(weights.sum(), 1.0, rtol=1e-6)
    cos_zenith = fetch_tregenza_patch_directions(torch.device("cpu")).numpy()[:, 2]
    brightness = tregenza_solid_angles() * (1.0 + 2.0 * cos_zenith) / 3.0
    np.testing.assert_allclose(weights, brightness / brightness.sum(), rtol=1e-5)
