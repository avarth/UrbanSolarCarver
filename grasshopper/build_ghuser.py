"""Build the Grasshopper user objects (.ghuser) from the component sources.

    python grasshopper/build_ghuser.py            # rebuild all into USC_GHplugin/
    python grasshopper/build_ghuser.py --check    # fail if any .ghuser is stale

Each component is described by its own source file:

- port names and descriptions: the "GH UI" block (executed against a mock
  ghenv, so what the canvas shows at runtime is exactly what is packaged)
- port order and types: the numpydoc ``Inputs`` / ``Outputs`` docstring
  sections (types mapped to Grasshopper type hints by ``_TYPE_RULES``)
- the code itself: embedded verbatim

``components.json`` holds the rest: ribbon subcategory, the stable user
object GUID (keeps the ribbon slot and canvas identity across rebuilds),
and the preview flag.

Writes Rhino 8 "Python 3 Script" components, field-for-field like the ones
the Rhino 8 script editor saves. Needs ``pythonnet`` and Grasshopper's
``GH_IO.dll`` (found in the Rhino 8 install, or pass --ghio); Rhino itself
does not need to be running. Serialization adapted from the MIT-licensed
GHPython Componentizer (github.com/compas-dev/compas-actions.ghpython_components).
"""

from __future__ import annotations

import argparse
import ast
import base64
import json
import re
import sys
import types
import uuid
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
COMPONENTS_DIR = HERE / "components"
ICONS_DIR = HERE / "icons"
OUT_DIR = HERE / "USC_GHplugin"
MANIFEST = HERE / "components.json"

DEFAULT_GHIO_DIRS = [
    Path(r"C:\Program Files\Rhino 8\Plug-ins\Grasshopper"),
    Path("/Applications/Rhino 8.app/Contents/Frameworks/RhCore.framework/Versions/A/Resources/ManagedPlugIns/GrasshopperPlugin.rhp"),
]

PYTHON3_SCRIPT_COMPONENT = "719467e6-7cf5-4848-99b0-c5dd57e5442c"
SCRIPT_PARAM_ID = "08908df5-fa14-4982-9ab2-1aa0927566aa"
GUID_NAMESPACE = uuid.UUID("5b0f3c1e-6d2a-4f3e-9a51-0c4b7d1e2a90")

# hint name -> (TypeHintID, converter assembly, converter type)
TYPE_HINTS = {
    "object": ("1c282eeb-dd16-439f-94e4-7d92b542fe8b", "System.Private.CoreLib", "System.Object"),
    "float": ("9d51e32e-c038-4352-9554-f4137ca91b9a", "System.Private.CoreLib", "System.Double"),
    "int": ("48d01794-d3d8-4aef-990e-127168822244", "System.Private.CoreLib", "System.Int32"),
    "str": ("3aceb454-6dbd-4c5b-9b6b-e71f8c1cdf88", "System.Private.CoreLib", "System.String"),
    "bool": ("d60527f5-b5af-4ef6-8970-5f96fe412559", "System.Private.CoreLib", "System.Boolean"),
    "mesh": ("794a1f9d-21d5-4379-b987-9e8bbf433912", "RhinoCommon", "Rhino.Geometry.Mesh"),
}

# Docstring type (lower-cased, ", optional" stripped) -> (hint, is_list).
# First matching pattern wins; anything unmatched is an error, not a guess.
_TYPE_RULES = [
    (r"^list of (\d+ )?floats?$", ("float", True)),
    (r"^list of str$", ("str", True)),
    (r"^list of point3d$", ("object", True)),
    # Breps must reach the script unconverted: a mesh hint makes Grasshopper
    # mesh them with its coarse default settings first.
    (r"^mesh or brep \(list\)$", ("object", True)),
    (r"^mesh or brep$", ("object", False)),
    (r"^(rhino\.geometry\.)?mesh$", ("mesh", False)),
    (r"^str or list$", ("object", True)),
    (r"^float$", ("float", False)),
    (r"^int( \(\d+-\d+\))?$", ("int", False)),
    (r"^str$", ("str", False)),
    (r"^bool$", ("bool", False)),
    (r"^dict$", ("object", False)),
    (r"^usc\w+( or str)?$", ("object", False)),
]


# -- reading a component source ------------------------------------------------

class _Param:
    def __init__(self):
        self.Name = None
        self.Description = None
        self.Access = None


class _Component:
    def __init__(self, n=64):
        self.Name = self.NickName = self.Description = None
        self.Params = types.SimpleNamespace(
            Input=[_Param() for _ in range(n)],
            Output=[_Param() for _ in range(n)],
        )


def _gh_ui_block(tree: ast.Module, src: str) -> list[ast.stmt]:
    for node in tree.body:
        if isinstance(node, ast.Try) and "ghenv.Component.Name" in ast.get_source_segment(src, node):
            return node.body
    raise ValueError("no top-level `try:` block setting ghenv.Component.Name")


def read_ui(src: str, filename: str) -> dict:
    """Execute the GH UI block against a mock ghenv; return what it sets."""
    tree = ast.parse(src, filename)
    body = ast.Module(body=_gh_ui_block(tree, src), type_ignores=[])
    comp = _Component()
    fakes = {m: mock.MagicMock(name=m) for m in ("Grasshopper", "Grasshopper.Kernel", "Rhino", "System")}
    with mock.patch.dict(sys.modules, fakes):
        exec(compile(body, filename, "exec"), {"ghenv": types.SimpleNamespace(Component=comp)})

    def ports(params):
        out = []
        for p in params:
            if p.Name is None:
                break
            out.append({"name": p.Name, "description": p.Description or "",
                        "list_access": p.Access is not None and "list" in repr(p.Access)})
        return out

    if not (comp.Name and comp.NickName):
        raise ValueError("GH UI block must set ghenv.Component.Name and NickName")
    return {"name": comp.Name, "nickname": comp.NickName, "description": comp.Description or "",
            "inputs": ports(comp.Params.Input), "outputs": ports(comp.Params.Output)}


def read_doc_ports(src: str) -> dict[str, list[tuple[str, str]]]:
    """numpydoc Inputs/Outputs sections -> {section: [(name, type), ...]}."""
    doc = ast.get_docstring(ast.parse(src)) or ""
    sections, current = {"Inputs": [], "Outputs": []}, None
    lines = doc.splitlines()
    for i, line in enumerate(lines):
        nxt = lines[i + 1] if i + 1 < len(lines) else ""
        if line.strip() in sections and set(nxt.strip()) == {"-"}:
            current = line.strip()
            continue
        if current and re.fullmatch(r"[A-Z][A-Za-z ]+", line.strip() or "x") and set(nxt.strip()) == {"-"}:
            current = None  # some other numpydoc section
            continue
        m = re.match(r"^(\w+(?:, \w+)*) : (.+)$", line)  # numpydoc allows "a, b : type"
        if current and m:
            for name in m.group(1).split(", "):
                sections[current].append((name, m.group(2).strip()))
    return sections


def map_type(doc_type: str) -> tuple[str, bool]:
    t = re.sub(r",\s*optional$", "", doc_type.strip().lower())
    for pattern, result in _TYPE_RULES:
        if re.match(pattern, t):
            return result
    raise ValueError(f"unmapped docstring type {doc_type!r}: add a rule to _TYPE_RULES "
                     "or a per-port 'types' override in components.json")


def describe(src_path: Path, entry: dict) -> dict:
    src = src_path.read_text(encoding="utf-8")
    ui = read_ui(src, str(src_path))
    doc = read_doc_ports(src)
    overrides = entry.get("types", {})
    for side, key in (("inputs", "Inputs"), ("outputs", "Outputs")):
        ui_names = [p["name"] for p in ui[side]]
        doc_names = [n for n, _ in doc[key]]
        if ui_names != doc_names:
            raise ValueError(f"{side}: GH UI block names {ui_names} != docstring {doc_names}")
        for port, (_, doc_type) in zip(ui[side], doc[key]):
            if side == "outputs":
                # Script-component outputs pass values through untyped.
                port["hint"], port["is_list"] = "object", False
                continue
            if port["name"] in overrides:
                hint, _, access = overrides[port["name"]].partition(" ")
                port["hint"], port["is_list"] = hint, access == "list"
            else:
                port["hint"], port["is_list"] = map_type(doc_type)
            port["is_list"] = port["is_list"] or port["list_access"]
            if port["hint"] not in TYPE_HINTS:
                raise ValueError(f"unknown type hint {port['hint']!r} for {port['name']}")
    ui["code"] = src
    return ui


# -- writing a .ghuser -----------------------------------------------------------

def _guid(seed: str):
    import System
    return System.Guid(str(uuid.uuid5(GUID_NAMESPACE, seed)))


def _write_param(chunk, port, seed, is_input, hidden):
    import System
    hint_id, asm, tname = TYPE_HINTS[port["hint"]]
    if port["is_list"]:
        chunk.SetInt32("Access", 1)
    chunk.SetBoolean("AllowTreeAccess", is_input)
    chunk.SetString("Description", port["description"])
    if hidden:
        chunk.SetBoolean("Hidden", True)
    chunk.SetGuid("InstanceGuid", _guid(seed))
    chunk.SetString("Name", port["name"])
    chunk.SetString("NickName", port["name"])
    chunk.SetBoolean("Optional", is_input)
    chunk.SetInt32("ScriptParamAccess", 1 if port["is_list"] else 0)
    chunk.SetInt32("ScriptParameterVersion", 2)
    chunk.SetBoolean("ShowTypeHints", True)
    chunk.SetInt32("SourceCount", 0)
    chunk.SetString("ToolTip", "")
    chunk.SetGuid("TypeHintID", System.Guid(hint_id))
    conv = chunk.CreateChunk("ConverterData")
    conv.SetString("AssemblyName", asm)
    conv.SetString("TypeName", tname)


def build_bytes(comp: dict, entry: dict, category: str, icon_png: bytes) -> bytes:
    import System
    from GH_IO.Serialization import GH_LooseChunk

    uo_guid = entry["guid"]
    hidden_outputs = set(entry.get("hidden_outputs", []))

    inner = GH_LooseChunk("UserObject")
    inner.SetString("Description", comp["description"])
    inner.SetBoolean("GraftStandardOutputLines", True)
    if entry.get("preview_off", True):
        inner.SetBoolean("Hidden", True)
    inner.SetDrawingBitmap("IconOverride", System.Drawing.Bitmap(System.IO.MemoryStream(icon_png)))
    inner.SetGuid("InstanceGuid", _guid(uo_guid + "/component"))
    for k in ("MarshGuids", "MarshInputs", "MarshOutputs"):
        inner.SetBoolean(k, True)
    inner.SetString("Name", comp["name"])
    inner.SetString("NickName", comp["nickname"])
    inner.SetInt32("ScriptComponentVersion", 3)
    inner.SetString("Tooltip", "")
    for k in ("UsingLibraryInputParam", "UsingScriptInputParam",
              "UsingScriptOutputParam", "UsingStandardOutputParam"):
        inner.SetBoolean(k, False)

    pd = inner.CreateChunk("ParameterData")
    pd.SetInt32("InputCount", len(comp["inputs"]))
    for i in range(len(comp["inputs"])):
        pd.SetGuid("InputId", i, System.Guid(SCRIPT_PARAM_ID))
    pd.SetInt32("OutputCount", len(comp["outputs"]))
    for i in range(len(comp["outputs"])):
        pd.SetGuid("OutputId", i, System.Guid(SCRIPT_PARAM_ID))
    for i, p in enumerate(comp["inputs"]):
        _write_param(pd.CreateChunk("InputParam", i), p, f"{uo_guid}/in/{p['name']}", True, False)
    for i, p in enumerate(comp["outputs"]):
        _write_param(pd.CreateChunk("OutputParam", i), p, f"{uo_guid}/out/{p['name']}", False,
                     p["name"] in hidden_outputs)

    script = inner.CreateChunk("Script")
    for k in ("MarshGuids", "MarshInputs", "MarshOutputs"):
        script.SetBoolean(k, True)
    script.SetString("Text", base64.b64encode(comp["code"].encode("utf-8")).decode("ascii"))
    script.SetString("Title", comp["nickname"])
    lang = script.CreateChunk("LanguageSpec")
    lang.SetString("Taxon", "*.*.python")
    lang.SetString("Version", "3.*")

    root = GH_LooseChunk("UserObject")
    root.SetGuid("BaseID", System.Guid(PYTHON3_SCRIPT_COMPONENT))
    root.SetString("Category", category)
    root.SetString("Description", comp["description"])
    root.SetInt32("Exposure", entry.get("exposure", 2))
    root.SetByteArray("Icon", icon_png)
    root.SetGuid("InstanceGuid", System.Guid(uo_guid))
    root.SetString("Name", comp["name"])
    root.SetString("NickName", comp["nickname"])
    root.SetByteArray("Object", inner.Serialize_Binary())
    root.SetString("SubCategory", entry["subcategory"])
    return bytes(root.Serialize_Binary())


# -- driver ----------------------------------------------------------------------

def load_gh_io(ghio: str | None):
    import clr
    dirs = [Path(ghio)] if ghio else DEFAULT_GHIO_DIRS
    for d in dirs:
        dll = d / "GH_IO.dll"
        if dll.is_file():
            clr.AddReference(str(dll))
            import System  # noqa: F401
            clr.AddReference("System.Drawing")
            return dll
    sys.exit("GH_IO.dll not found; pass --ghio <folder containing GH_IO.dll>")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--ghio", help="folder containing GH_IO.dll (default: Rhino 8 install)")
    ap.add_argument("--check", action="store_true", help="exit 1 if any .ghuser is missing or stale")
    ap.add_argument("--dry-run", action="store_true", help="parse sources and print ports only")
    args = ap.parse_args(argv)

    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    entries = manifest["components"]
    sources = sorted(p.name for p in COMPONENTS_DIR.glob("USC_*.py"))
    missing = sorted(set(sources) - set(entries))
    unknown = sorted(set(entries) - set(sources))
    if missing or unknown:
        sys.exit(f"components.json out of sync: no entry for {missing}; no source for {unknown}")

    comps = {}
    for fname in sources:
        try:
            comps[fname] = describe(COMPONENTS_DIR / fname, entries[fname])
        except Exception as exc:
            sys.exit(f"{fname}: {exc}")
        if args.dry_run:
            c = comps[fname]
            fmt = lambda ps: ", ".join(f"{p['name']}:{p['hint']}{'[]' if p['is_list'] else ''}" for p in ps)
            print(f"{c['name']:24} in({fmt(c['inputs'])})  out({fmt(c['outputs'])})")
    if args.dry_run:
        return 0

    load_gh_io(args.ghio)
    OUT_DIR.mkdir(exist_ok=True)
    stale = []
    for fname, comp in comps.items():
        entry = entries[fname]
        icon = (ICONS_DIR / entry.get("icon", fname.replace(".py", ".png"))).read_bytes()
        data = build_bytes(comp, entry, manifest["category"], icon)
        target = OUT_DIR / f"{comp['name']}.ghuser"
        current = target.read_bytes() if target.is_file() else None
        if current == data:
            continue
        stale.append(target.name)
        if not args.check:
            target.write_bytes(data)
    expected = {f"{c['name']}.ghuser" for c in comps.values()}
    orphans = sorted(p.name for p in OUT_DIR.glob("*.ghuser") if p.name not in expected)

    if args.check:
        if stale or orphans:
            print("stale:", stale, "orphaned:", orphans)
            return 1
        print(f"all {len(comps)} .ghuser files up to date")
        return 0
    print(f"wrote {len(stale)} of {len(comps)} .ghuser files to {OUT_DIR}")
    for name in stale:
        print("  ", name)
    if orphans:
        print("orphaned (no source; delete if intended):", orphans)
    return 0


if __name__ == "__main__":
    sys.exit(main())
