"""Draw the import maps of the Python package and of the app, as SVG files to open in a browser.

    python tools/draw_maps.py              # the two maps below
    python tools/draw_maps.py --modules    # also every Python module and its imports (pydeps; dense)

Writes into build/maps/ (ignored by git, so the pictures never go stale in the repository):

- ``python_layers.svg``: the layers written in pyproject.toml ([tool.importlinter]), each box naming its modules, and
  how many imports go from one layer down to another. An import that goes up a layer (a listed exception) is red.
- ``app_folders.svg``: the app's folders (and its top-level files), and how many imports go from one to another,
  test files left out. Two folders that import each other are joined in red: neither can be read or changed alone.
- ``python_modules.svg`` (with ``--modules``): every module of the package and which imports which, grouped by
  sub-package.

The rules are in pyproject.toml and app/.dependency-cruiser.cjs; docs/project-map.md explains them. Needs Graphviz
(``winget install Graphviz.Graphviz``), the dev extra (grimp, pydeps) and the app's node modules (``npm install`` in
app/).
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "build" / "maps"
APP = ROOT / "app"
PACKAGE = "urbansolarcarver"
# Where winget puts Graphviz; used when dot is not on PATH (a new install reaches PATH only in new terminals).
GRAPHVIZ_BIN = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Graphviz" / "bin"
# App files the folder map leaves out: tests, their helpers, styles and data.
APP_LEFT_OUT = re.compile(r"[.]test[.]|_for_test|[.]css$|[.]json$")
RED = "#c0392b"


def _dot() -> str:
    found = shutil.which("dot") or shutil.which("dot", path=str(GRAPHVIZ_BIN))
    if found is None:
        sys.exit("Graphviz's dot was not found: install it with `winget install Graphviz.Graphviz`.")
    os.environ["PATH"] = str(Path(found).parent) + os.pathsep + os.environ["PATH"]   # pydeps calls dot by name
    return found


def _render(dot: str, source: str, target: Path) -> Path:
    subprocess.run([dot, "-Tsvg", "-o", str(target)], input=source, check=True, text=True)
    return target


def _count_graph(name: str, boxes: dict, counts: Counter, red: set) -> str:
    """A dot graph: a box per key of *boxes* (its value the label), an edge per pair of *counts* labelled with the
    number of imports; the pairs in *red* are drawn red and do not shape the layout."""
    lines = [f"digraph {name} {{", '  rankdir=TB; node [shape=box, style="rounded,filled", fillcolor="#f4f4f0",'
             ' fontname="Helvetica", fontsize=11]; edge [color="#888888", fontname="Helvetica", fontsize=10];']
    keys = {key: f"n{index}" for index, key in enumerate(boxes)}
    lines += [f'  {keys[key]} [label="{label}"];' for key, label in boxes.items()]
    for (source, target), number in sorted(counts.items()):
        style = f', color="{RED}", fontcolor="{RED}", constraint=false' if (source, target) in red else ""
        lines.append(f'  {keys[source]} -> {keys[target]} [label="{number}"{style}];')
    lines.append("}")
    return "\n".join(lines)


def _layers() -> tuple[list[list[str]], list[str]]:
    """The layers of the layers contract in pyproject.toml (top first, each a list of module tails) and its ignored
    imports."""
    try:
        import tomllib
    except ModuleNotFoundError:          # Python 3.10
        import tomli as tomllib
    config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["tool"]["importlinter"]
    contract = next(c for c in config["contracts"] if c["type"] == "layers")
    layers = [[tail.strip() for tail in layer.replace("|", ":").split(":")] for layer in contract["layers"]]
    return layers, list(contract.get("ignore_imports", []))


def _layer_source() -> str:
    """The Python layer map (see the module docstring)."""
    import grimp
    sys.path.insert(0, str(ROOT / "src"))
    graph = grimp.build_graph(PACKAGE)
    layers, ignored = _layers()
    layer_of = {}
    for index, layer in enumerate(layers):
        for tail in layer:
            for module in graph.find_descendants(f"{PACKAGE}.{tail}") | {f"{PACKAGE}.{tail}"}:
                layer_of[module] = index
    counts = Counter()
    for importer, index in layer_of.items():
        for imported in graph.find_modules_directly_imported_by(importer):
            target = layer_of.get(imported)
            if target is not None and target != index:
                counts[index, target] += 1
    boxes = {index: f"layer {index + 1}\\n\\n" + "\\n".join(sorted(layer)) for index, layer in enumerate(layers)}
    if ignored:
        print("listed exceptions:", ", ".join(ignored))
    return _count_graph("python_layers", boxes, counts, {pair for pair in counts if pair[1] < pair[0]})


def _app_source() -> str:
    """The app folder map (see the module docstring), from dependency-cruiser's list of imports."""
    node, cruiser = shutil.which("node"), APP / "node_modules" / "dependency-cruiser" / "bin" / "dependency-cruiser.mjs"
    if node is None or not cruiser.exists():
        sys.exit("node or dependency-cruiser was not found: install Node.js and run `npm install` in app/.")
    # node itself, not npx: on Windows npx is a .cmd file, and cmd.exe would read the | and ^ of patterns.
    found = json.loads(subprocess.run([node, str(cruiser), "src", "--config", ".dependency-cruiser.cjs", "--output-type",
                                       "json"], cwd=APP, capture_output=True, text=True, encoding="utf-8").stdout)

    def box(path: str):
        if not path.startswith("src/") or APP_LEFT_OUT.search(path):
            return None
        parts = path.split("/")
        return parts[1] + "/" if len(parts) > 2 else parts[1]

    counts = Counter()
    for module in found["modules"]:
        source = box(module["source"])
        for dependency in module["dependencies"] if source else ():
            target = box(dependency["resolved"])
            if target and target != source:
                counts[source, target] += 1
    names = sorted({name for pair in counts for name in pair}, key=lambda n: (not n.endswith("/"), n))
    two_way = {(a, b) for a, b in counts if (b, a) in counts}
    return _count_graph("app_folders", {name: name for name in names}, counts, two_way)


def _python_modules() -> Path:
    target = OUT / "python_modules.svg"
    subprocess.run([sys.executable, "-m", "pydeps", str(ROOT / "src" / PACKAGE), "--only", PACKAGE, "--cluster",
                    "--rankdir", "BT", "--noshow", "-T", "svg", "-o", str(target)], check=True, cwd=ROOT)
    return target


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--modules", action="store_true", help="also draw every Python module (pydeps)")
    arguments = parser.parse_args()
    dot = _dot()
    OUT.mkdir(parents=True, exist_ok=True)
    written = [_render(dot, _layer_source(), OUT / "python_layers.svg"),
               _render(dot, _app_source(), OUT / "app_folders.svg")]
    if arguments.modules:
        written.append(_python_modules())
    for path in written:
        print(path)


if __name__ == "__main__":
    main()
