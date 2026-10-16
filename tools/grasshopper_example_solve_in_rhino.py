#! python3
"""Solve examples/USC_components_for_grasshopper.gh inside Rhino 8 and record
what every USC component reports.

Runs in Rhino's own Python through RhinoCode; grasshopper_example_smoke_test.py
starts it with a ``SETTINGS`` dict (carver root, definition, EPW, input PLYs,
output folder, report path).  The definition is a template, so it is changed
in memory only: root panel, output folders, EPW panel, the toggles feeding
``start_daemon`` and ``run``, and pipeline 1's geometry, which references
objects of a Rhino model that is not open.  It is closed without saving.
"""
import importlib.util
import json
import os
import time
import traceback

settings = SETTINGS  # noqa: F821, given by the launcher
report = {"label": settings["label"], "root": settings["root"], "out_base": settings["out_base"],
          "changes": [], "components": [], "error": None}


def note(text):
    report["changes"].append(text)


try:
    import Rhino
    grasshopper = Rhino.RhinoApp.GetPlugInObject("Grasshopper")
    if not grasshopper.IsEditorLoaded():
        grasshopper.LoadEditor()
    from Grasshopper.Kernel import GH_DocumentIO, GH_RuntimeMessageLevel, GH_SolutionMode
    from Grasshopper.Kernel.Special import GH_BooleanToggle, GH_Panel
    from Grasshopper.Kernel.Types import GH_Mesh

    # The helper module of the root under test, loaded fresh under its own name.
    spec = importlib.util.spec_from_file_location(
        "usc_gh_smoke_test", os.path.join(settings["root"], "grasshopper", "usc_gh.py"))
    usc_gh = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(usc_gh)

    io = GH_DocumentIO()
    if not io.Open(settings["definition"]):
        raise RuntimeError("could not open " + settings["definition"])
    doc = io.Document

    pipelines = 0
    for obj in list(doc.Objects):
        if isinstance(obj, GH_Panel):
            if obj.NickName == "USC root folder path":
                obj.SetUserText(settings["root"])
                note("root panel -> " + settings["root"])
            elif obj.NickName == "output directory":
                pipelines += 1
                folder = os.path.join(settings["out_base"], "pipeline_%d" % pipelines)
                obj.SetUserText(folder)
                note("output directory -> " + folder)
            elif obj.NickName == "path to EPW (if required by mode)":
                obj.SetUserText(settings["epw"])
                note("EPW panel -> " + settings["epw"])
        elif isinstance(obj, GH_BooleanToggle):
            targets = [(r.Attributes.GetTopLevel.DocObject.NickName, r.Name) for r in obj.Recipients]
            if any(name in ("start_daemon", "run") for _, name in targets):
                obj.Value = True
                note("toggle on -> %s" % targets)
        elif obj.NickName in ("maximum volume to carve", "test surfaces to protect"):
            ply = settings["max_volume_ply"] if obj.NickName.startswith("maximum") else settings["test_surfaces_ply"]
            obj.PersistentData.Clear()
            obj.PersistentData.Append(GH_Mesh(usc_gh.load_ply_to_rhino(ply)))
            note("%s -> %s" % (obj.NickName, ply))

    doc.Enabled = True
    start = time.time()
    doc.NewSolution(True, GH_SolutionMode.Silent)
    report["solve_seconds"] = round(time.time() - start, 1)

    for obj in doc.Objects:
        if not obj.NickName.startswith("USC") or not hasattr(obj, "Params") or not hasattr(obj, "RuntimeMessages"):
            continue
        entry = {"nick": obj.NickName, "messages": {}, "outputs": {}}
        for level in ("Error", "Warning", "Remark"):
            messages = list(obj.RuntimeMessages(getattr(GH_RuntimeMessageLevel, level)))
            if messages:
                entry["messages"][level] = messages
        for param in obj.Params.Output:
            values = [str(goo) for goo in param.VolatileData.AllData(True)]
            if values:
                entry["outputs"][param.Name] = {"count": len(values), "first": values[0][:300]}
        report["components"].append(entry)
    doc.Enabled = False
    doc.Dispose()
except Exception:
    report["error"] = traceback.format_exc()

# Write then rename, so the waiting driver never reads half a file.
partial = settings["report"] + ".partial"
with open(partial, "w", encoding="utf-8") as f:
    json.dump(report, f, indent=1)
os.replace(partial, settings["report"])
