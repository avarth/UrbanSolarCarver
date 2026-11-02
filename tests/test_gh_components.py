"""Grasshopper component sources stay buildable into .ghuser files.

Runs the source-reading half of grasshopper/build_ghuser.py (no Rhino or
pythonnet needed): every component's GH UI block must agree with its
numpydoc ports, every docstring type must map to a Grasshopper type hint,
and components.json must cover exactly the component sources.  The packaged
.ghuser files are read back (a small reader of GH_IO's binary chunks, below)
and compared with what the sources describe.
"""

import base64
import importlib.util
import json
import struct
import uuid
import zlib
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


def _read_chunk(data: bytes, pos: int) -> tuple[dict, int]:
    """One GH_IO chunk serialized by GH_LooseChunk.Serialize_Binary: name, index, item and chunk counts, the items
    (name, index, type code, value), then the child chunks.  Only the item types build_ghuser writes are read."""
    def string(pos):                                   # .NET BinaryWriter: 7-bit length prefix, UTF-8
        n = shift = 0
        while True:
            byte = data[pos]
            pos += 1
            n |= (byte & 0x7F) << shift
            shift += 7
            if byte < 0x80:
                return data[pos:pos + n].decode("utf-8"), pos + n

    def int32(pos):
        return struct.unpack_from("<i", data, pos)[0], pos + 4

    name, pos = string(pos)
    index, pos = int32(pos)
    n_items, pos = int32(pos)
    n_chunks, pos = int32(pos)
    items = {}
    for _ in range(n_items):
        key, pos = string(pos)
        item_index, pos = int32(pos)
        kind, pos = int32(pos)
        if kind == 1:                                  # bool
            value, pos = bool(data[pos]), pos + 1
        elif kind == 3:                                # int32
            value, pos = int32(pos)
        elif kind == 9:                                # Guid, in .NET byte order
            value, pos = str(uuid.UUID(bytes_le=data[pos:pos + 16])), pos + 16
        elif kind == 10:                               # string
            value, pos = string(pos)
        elif kind in (20, 37):                         # byte array, bitmap (PNG bytes)
            n, pos = int32(pos)
            value, pos = data[pos:pos + n], pos + n
        else:
            raise ValueError(f"item {key!r} has type {kind}, which build_ghuser does not write")
        items[key if item_index == -1 else (key, item_index)] = value
    chunks = []
    for _ in range(n_chunks):
        chunk, pos = _read_chunk(data, pos)
        chunks.append(chunk)
    return {"name": name, "index": index, "items": items, "chunks": chunks}, pos


def _read_ghuser(path: Path) -> tuple[dict, dict]:
    """The outer user object chunk and the component chunk stored in its "Object" item (both deflate-compressed)."""
    root, _ = _read_chunk(zlib.decompress(path.read_bytes(), -15), 0)
    component, _ = _read_chunk(zlib.decompress(root["items"]["Object"], -15), 0)
    return root, component


@pytest.mark.parametrize("fname", SOURCES)
def test_packaged_ghuser_matches_its_source(fname):
    """A .ghuser left stale after a change of the source (code, ports, type hints) or of components.json fails here;
    rebuild with ``python grasshopper/build_ghuser.py``."""
    entry = MANIFEST["components"][fname]
    comp = build_ghuser.describe(GH_DIR / "components" / fname, entry)
    path = GH_DIR / "USC_GHplugin" / f"{comp['name']}.ghuser"
    assert path.is_file()
    root, component = _read_ghuser(path)
    assert root["items"]["InstanceGuid"] == entry["guid"]
    assert root["items"]["SubCategory"] == entry["subcategory"]
    assert component["items"]["Name"] == comp["name"] and component["items"]["NickName"] == comp["nickname"]
    script = next(c for c in component["chunks"] if c["name"] == "Script")
    assert base64.b64decode(script["items"]["Text"]).decode("utf-8") == comp["code"]
    params = next(c for c in component["chunks"] if c["name"] == "ParameterData")["chunks"]
    inputs = [(c["items"]["Name"], c["items"]["TypeHintID"], c["items"]["ScriptParamAccess"] == 1)
              for c in params if c["name"] == "InputParam"]
    assert inputs == [(p["name"], build_ghuser.TYPE_HINTS[p["hint"]][0], p["is_list"]) for p in comp["inputs"]]
    assert [c["items"]["Name"] for c in params if c["name"] == "OutputParam"] == [p["name"] for p in comp["outputs"]]


@pytest.mark.parametrize("fname", ["USC_Preprocess.py", "USC_RunPipeline.py"])
def test_geometry_inputs_reach_the_script_as_geometry(fname):
    # The "ghdoc Object" hint (1c282eeb...) hands geometry over as document
    # Guids, so referenced Breps would arrive as ids, not geometry.
    comp = build_ghuser.describe(GH_DIR / "components" / fname, MANIFEST["components"][fname])
    ports = {p["name"]: p for p in comp["inputs"]}
    for name in ("max_volume", "test_surfaces"):
        assert ports[name]["hint"] == "geometrybase" and ports[name]["is_list"]
    assert build_ghuser.TYPE_HINTS["geometrybase"][2] == "Rhino.Geometry.GeometryBase"


@pytest.mark.parametrize("fname", ["USC_Preprocess.py", "USC_RunPipeline.py"])
def test_context_and_terrain_inputs_follow_the_test_surfaces(fname):
    comp = build_ghuser.describe(GH_DIR / "components" / fname, MANIFEST["components"][fname])
    names = [p["name"] for p in comp["inputs"]]
    assert names.index("context") == names.index("test_surfaces") + 1
    assert names.index("terrain") == names.index("context") + 1
    ports = {p["name"]: p for p in comp["inputs"]}
    for name in ("context", "terrain"):
        assert ports[name]["hint"] == "geometrybase" and ports[name]["is_list"]


def test_ray_settings_take_the_context_blocking_switch():
    comp = build_ghuser.describe(GH_DIR / "components" / "USC_RaySettings.py", MANIFEST["components"]["USC_RaySettings.py"])
    ports = {p["name"]: p for p in comp["inputs"]}
    assert ports["context_blocks_rays"]["hint"] == "bool" and not ports["context_blocks_rays"]["is_list"]
