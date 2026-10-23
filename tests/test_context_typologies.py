"""End to end on typology scenes with the neighbours as context masses: the neighbour facades are faces of their own
context buildings, and dropping the rays they block can only keep more of the plot."""
import json

import numpy as np
import pytest

import cases
from typologies import SceneSpec, build, neighbour_masses

pytestmark = pytest.mark.slow

TYPOLOGIES = ("courtyard", "rows", "lshape")


def _threshold_value(run):
    return json.loads((run.thr / "diagnostics" / "diagnostic.json").read_text())["threshold_value"]


def _runs(tmp_path, typology, example_epw_path):
    scene = build(SceneSpec(typology=typology, seed=0))
    plain = cases.run(scene, tmp_path / "plain", str(example_epw_path), "daylight", carve_fraction=0.7)
    context_path = scene.write_context(tmp_path / "context")
    with_context = cases.run(scene, tmp_path / "context", str(example_epw_path), "daylight",
                             context_path=str(context_path), threshold=_threshold_value(plain))
    return scene, plain, with_context


def test_neighbour_masses_are_closed_boxes_behind_the_facades():
    spec = SceneSpec(typology="courtyard", seed=0)
    masses = neighbour_masses(spec)
    assert len(masses) == 4
    for mass in masses:
        assert mass.is_watertight and mass.is_volume
        assert mass.bounds[1][2] == pytest.approx(spec.neigh_h)
    scene = build(spec)
    assert scene.context is not None and scene.context.is_watertight
    assert build(SceneSpec(typology="courtyard", neighbours=False)).context is None


@pytest.mark.parametrize("typology", TYPOLOGIES)
def test_context_carving_keeps_at_least_as_much(tmp_path, typology, example_epw_path):
    """At the same numeric cutoff, every voxel kept without context (and not removed by it) is kept with context."""
    _scene, plain, with_context = _runs(tmp_path, typology, example_epw_path)
    assert with_context.diag("pre")["context"]["rays_dropped"] > 0
    still_buildable = plain.mask.astype(bool) & with_context.occ
    assert not (still_buildable & ~with_context.mask.astype(bool)).any()
    assert with_context.mask.sum() >= plain.mask.sum()


@pytest.mark.parametrize("typology", TYPOLOGIES)
def test_neighbour_facades_are_not_blocked_by_their_own_mass(tmp_path, typology, example_epw_path):
    _scene, _plain, with_context = _runs(tmp_path, typology, example_epw_path)
    assert with_context.diag("pre")["context"]["test_points_fully_blocked"] == 0
