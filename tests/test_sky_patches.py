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
