"""Grasshopper smoke test: solve examples/USC_components_for_grasshopper.gh in
a running Rhino 8 and compare two runs (for example main against a branch).

    python tools/grasshopper_example_smoke_test.py run main D:\\path\\to\\urbanSolarCarver
    python tools/grasshopper_example_smoke_test.py run branch D:\\path\\to\\worktree
    python tools/grasshopper_example_smoke_test.py compare main branch

``run`` solves the definition of the given carver root with that root's
grasshopper/usc_gh.py and daemon, and writes ``<runs>/<label>.json`` (messages
and outputs of every USC component) and the pipelines' output folders
``<runs>/<label>/pipeline_N``.  ``<runs>`` is ~/.urbansolarcarver/gh_runs,
short enough for Windows' 260-character path limit.  ``compare`` matches
components by nickname and occurrence (instance ids change on every open),
compares meshes and integer arrays (masks) exactly and float arrays (scores)
with a relative tolerance, because GPU atomic adds sum in a varying order.

Needs Rhino 8 open and the USC environment's python; not part of pytest.
"""
import argparse
import json
import re
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

from urbansolarcarver.daemon_client import DEFAULT_DAEMON_PORT

RUNS = Path.home() / ".urbansolarcarver" / "gh_runs"
RHINOCODE = Path(r"C:\Program Files\Rhino 8\System\RhinoCode.exe")
SOLVE_SCRIPT = Path(__file__).with_name("grasshopper_example_solve_in_rhino.py")
MESH_SUFFIXES = {".ply", ".obj", ".stl", ".glb"}
FLOAT_RTOL = 1e-5


def daemon_listening():
    try:
        socket.create_connection(("localhost", DEFAULT_DAEMON_PORT), timeout=1).close()
        return True
    except OSError:
        return False


def stop_daemon():
    """Stop a running daemon, so that USC_Session starts one from the root under test."""
    if not daemon_listening():
        return
    subprocess.run([sys.executable, "-m", "urbansolarcarver.carver_cli", "daemon", "stop"], capture_output=True)
    for _ in range(30):
        if not daemon_listening():
            return
        time.sleep(1)
    sys.exit("the daemon still listens after 'daemon stop'")


def rhino_id(given):
    if given:
        return given
    listing = subprocess.run([str(RHINOCODE), "list"], capture_output=True, text=True).stdout
    ids = re.findall(r"rhinocode_remotepipe_\d+", listing)
    if len(ids) != 1:
        sys.exit(f"found {len(ids)} running Rhino instances; pass --rhino <ID from 'RhinoCode.exe list'>")
    return ids[0]


def run(args):
    root = Path(args.root).resolve()
    out_base, report = RUNS / args.label, RUNS / f"{args.label}.json"
    shutil.rmtree(out_base, ignore_errors=True)
    report.unlink(missing_ok=True)
    out_base.mkdir(parents=True)
    # USC_Session looks for <root>/.venv, <root>/venv or <root>/python_path.txt; a worktree has none.
    if not any((root / name).exists() for name in (".venv", "venv", "python_path.txt")):
        (root / "python_path.txt").write_text(sys.executable, encoding="utf-8")
        print(f"wrote {root / 'python_path.txt'} -> {sys.executable}")
    inputs = root / "examples" / "test_inputs" / "multiple_buildings"
    settings = {
        "label": args.label, "root": str(root), "out_base": str(out_base), "report": str(report),
        "definition": str(root / "examples" / "USC_components_for_grasshopper.gh"),
        "epw": str(root / "examples" / "weather" / "USA_CO_Golden-NREL.724666_TMY3.epw"),
        "max_volume_ply": str(inputs / "max_volume.ply"),
        "test_surfaces_ply": str(inputs / "test_surfaces.ply"),
    }
    # RhinoCode runs a script file without arguments, so a launcher carries the settings.
    launcher = out_base / "launch.py"
    launcher.write_text(f"#! python3\nimport runpy\nrunpy.run_path({str(SOLVE_SCRIPT)!r}, "
                        f"init_globals={{'SETTINGS': {settings!r}}})\n", encoding="utf-8")

    stop_daemon()
    subprocess.run([str(RHINOCODE), "--rhino", rhino_id(args.rhino), "script", str(launcher)])
    deadline = time.time() + args.timeout
    while not report.exists():
        if time.time() > deadline:
            sys.exit(f"no report after {args.timeout} s: {report}")
        time.sleep(2)
    stop_daemon()

    result = json.loads(report.read_text(encoding="utf-8"))
    if result["error"]:
        sys.exit(f"the solve failed:\n{result['error']}")
    red = [c["nick"] for c in result["components"] if "Error" in c["messages"]]
    print(f"{args.label}: {len(result['components'])} USC components solved in {result['solve_seconds']} s, "
          f"{len(red)} with errors {red}; report {report}")


def normalise(text):
    """Drop run-specific parts (paths, run ids, timings) of a message."""
    text = re.sub(r"[A-Za-z]:\\[^\s'\"]+", "<path>", text)
    text = re.sub(r"\b[0-9a-f]{8,}\b", "<id>", text)
    return re.sub(r"\d+\.\d+ ?s\b", "<t>", text)


def by_occurrence(report):
    seen, keyed = {}, {}
    for comp in report["components"]:
        seen[comp["nick"]] = seen.get(comp["nick"], 0) + 1
        keyed[f"{comp['nick']} #{seen[comp['nick']]}"] = comp
    return keyed


def compare_components(before, after):
    problems = []
    a, b = by_occurrence(before), by_occurrence(after)
    for key in sorted(a.keys() ^ b.keys()):
        problems.append(f"{key}: only in {'before' if key in a else 'after'}")
    for key in sorted(a.keys() & b.keys()):
        for level in ("Error", "Warning", "Remark"):
            old = sorted(normalise(m) for m in a[key]["messages"].get(level, []))
            new = sorted(normalise(m) for m in b[key]["messages"].get(level, []))
            if old != new:
                problems.append(f"{key} {level}: {old} -> {new}")
        for name in sorted(a[key]["outputs"].keys() | b[key]["outputs"].keys()):
            old = a[key]["outputs"].get(name, {}).get("count")
            new = b[key]["outputs"].get(name, {}).get("count")
            if old != new:
                problems.append(f"{key} output {name}: {old} -> {new} items")
    return problems, len(a.keys() & b.keys())


def compare_files(before, after):
    """Compare the .npy arrays and exported meshes of two output folders."""
    def listing(base):
        return {p.relative_to(base) for p in base.rglob("*") if p.suffix in MESH_SUFFIXES | {".npy"}}

    a, b = listing(before), listing(after)
    problems = [f"{p}: only in {'before' if p in a else 'after'}" for p in sorted(a ^ b)]
    largest = 0.0
    for p in sorted(a & b):
        if p.suffix != ".npy":
            if (before / p).read_bytes() != (after / p).read_bytes():
                problems.append(f"{p}: mesh files differ")
            continue
        x, y = np.load(before / p), np.load(after / p)
        if x.shape != y.shape or x.dtype != y.dtype:
            problems.append(f"{p}: {x.dtype}{x.shape} -> {y.dtype}{y.shape}")
        elif np.issubdtype(x.dtype, np.floating):
            scale = float(np.abs(x).max()) if x.size else 0.0
            diff = float(np.abs(x - y).max()) / scale if scale else float(np.abs(y).max(initial=0.0))
            largest = max(largest, diff)
            if diff > FLOAT_RTOL:
                problems.append(f"{p}: largest difference {diff:.2e} of the largest value")
        elif not np.array_equal(x, y):
            problems.append(f"{p}: {int((x != y).sum())} of {x.size} values differ")
    return problems, len(a & b), largest


def compare(args):
    before, after = (json.loads((RUNS / f"{label}.json").read_text(encoding="utf-8"))
                     for label in (args.before, args.after))
    for report in (before, after):
        if report["error"]:
            sys.exit(f"{report['label']} has no solve to compare:\n{report['error']}")
    comp_problems, comps = compare_components(before, after)
    file_problems, files, largest = compare_files(Path(before["out_base"]), Path(after["out_base"]))
    for problem in comp_problems + file_problems:
        print("DIFF " + problem[:600])
    print(f"{comps} components, {files} arrays and meshes compared; {len(comp_problems)} component and "
          f"{len(file_problems)} file differences; largest float difference {largest:.1e} "
          f"(tolerance {FLOAT_RTOL:.0e})")
    sys.exit(1 if comp_problems or file_problems else 0)


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(required=True)
    p = sub.add_parser("run", help="solve the example definition of a carver root in Rhino")
    p.add_argument("label", help="name of this run, e.g. main or my-branch")
    p.add_argument("root", help="carver root whose code runs (main checkout or a worktree)")
    p.add_argument("--rhino", help="Rhino ID from 'RhinoCode.exe list' (needed when several Rhinos run)")
    p.add_argument("--timeout", type=int, default=900, help="seconds to wait for the report")
    p.set_defaults(func=run)
    p = sub.add_parser("compare", help="compare two runs by label")
    p.add_argument("before")
    p.add_argument("after")
    p.set_defaults(func=compare)
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
