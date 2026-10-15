"""Grasshopper component sources stay buildable into .ghuser files.

Runs the source-reading half of grasshopper/build_ghuser.py (no Rhino or
pythonnet needed): every component's GH UI block must agree with its
numpydoc ports, every docstring type must map to a Grasshopper type hint,
and components.json must cover exactly the component sources.
"""

import importlib.util
import json
from pathlib import Path

import pytest

GH_DIR = Path(__file__).resolve().parents[1] / "grasshopper"
_spec = importlib.util.spec_from_file_location("build_ghuser", GH_DIR / "build_ghuser.py")
build_ghuser = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(build_ghuser)

MANIFEST = json.loads((GH_DIR / "components.json").read_text(encoding="utf-8"))
SOURCES = sorted(p.name for p in (GH_DIR / "components").glob("USC_*.py"))


def test_manifest_covers_sources():
    assert sorted(MANIFEST["components"]) == SOURCES


def test_manifest_guids_unique():
    guids = [e["guid"] for e in MANIFEST["components"].values()]
    assert len(set(guids)) == len(guids)


@pytest.mark.parametrize("fname", SOURCES)
def test_component_describes(fname):
    comp = build_ghuser.describe(GH_DIR / "components" / fname, MANIFEST["components"][fname])
    assert comp["inputs"] and comp["outputs"]
    assert (GH_DIR / "icons" / MANIFEST["components"][fname].get("icon", fname.replace(".py", ".png"))).is_file()


@pytest.mark.parametrize("fname", SOURCES)
def test_packaged_ghuser_exists(fname):
    comp = build_ghuser.describe(GH_DIR / "components" / fname, MANIFEST["components"][fname])
    assert (GH_DIR / "USC_GHplugin" / f"{comp['name']}.ghuser").is_file()


@pytest.mark.parametrize("fname", ["USC_Preprocess.py", "USC_RunPipeline.py"])
def test_geometry_inputs_reach_the_script_as_geometry(fname):
    # The "ghdoc Object" hint (1c282eeb...) hands geometry over as document
    # Guids, so referenced Breps would arrive as ids, not geometry.
    comp = build_ghuser.describe(GH_DIR / "components" / fname, MANIFEST["components"][fname])
    ports = {p["name"]: p for p in comp["inputs"]}
    for name in ("max_volume", "test_surfaces"):
        assert ports[name]["hint"] == "geometrybase" and ports[name]["is_list"]
    assert build_ghuser.TYPE_HINTS["geometrybase"][2] == "Rhino.Geometry.GeometryBase"
