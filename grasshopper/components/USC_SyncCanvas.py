"""USC Sync Canvas — Update the USC components on this canvas.

Compares every USC component on the canvas with the installed USC user
objects (.ghuser) and brings outdated ones up to date. With update
unset or False it only reports; nothing on the canvas changes.

A component whose inputs and outputs are unchanged is replaced in place:
same position, every wire, internalised input values ("Set One String"),
data mappings (graft/flatten), preview/enabled state and group membership
carry over. A component whose inputs or outputs changed cannot be rewired
safely, so the new version is placed beside the old one and both are
wrapped in a red group: rewire the new one, then delete the old one.
The whole update is one undo step (Ctrl+Z).

Components with edited code count as outdated and are overwritten:
run with update=False first and read the report.

Inputs
------
update : bool, optional
    True = apply the update (use a Button). Default False: report only.
folder : str, optional
    Folder holding the USC .ghuser files to sync to. Default: the
    Grasshopper User Objects folders, where the installed versions live.

Outputs
-------
report : str
    What is up to date, what was (or would be) replaced, and what needs
    manual rewiring.
"""

import base64
import os

try:
    ghenv.Component.Name = "USC Sync Canvas"
    ghenv.Component.NickName = "USC_Sync"
    ghenv.Component.Description = "Updates the USC components on this canvas to the installed versions. Unchanged inputs/outputs: replaced in place, keeping wires and internalised values. Changed inputs/outputs: new version placed beside the old one inside a red group for manual rewiring. Report only unless update=True; one undo step."
    ii = ghenv.Component.Params.Input
    oo = ghenv.Component.Params.Output
    for i, (n, d) in enumerate([
        ("update", "True = apply the update (connect a Button). False or unconnected = only report what is out of date; nothing changes."),
        ("folder", "Optional folder containing the USC .ghuser files to update to. Default: the Grasshopper User Objects folders (File > Special Folders > User Object Folder), where the installed versions live."),
    ]):
        if i < len(ii):
            ii[i].Name, ii[i].Description = n, d
    oo[0].Name, oo[0].Description = "report", "Per component: up to date, replaced in place, or placed beside the old one for manual rewiring (with the changed inputs/outputs)."
except Exception:
    pass

import traceback

import System
import Grasshopper
import scriptcontext as sc
from Grasshopper.Kernel import GH_Document, GH_RuntimeMessageLevel, GH_UserObject
from Grasshopper.Kernel.Special import GH_Group, GH_GroupBorder
from Grasshopper.Kernel.Undo import GH_UndoRecord
from GH_IO.Serialization import GH_LooseChunk

GROUP_TAG = "USC sync:"
GROUP_COLOUR = System.Drawing.Color.FromArgb(150, 205, 92, 92)
_ERROR_KEY = "usc_sync_error_{}".format(ghenv.Component.InstanceGuid)


def _installed(folder):
    """{component name: GH_UserObject} for the USC .ghuser files found."""
    roots = [folder] if folder else list(Grasshopper.Folders.UserObjectFolders)
    found, dupes = {}, []
    for root in roots:
        for dirpath, _dirs, files in os.walk(str(root)):
            for fn in files:
                if not (fn.startswith("USC ") and fn.lower().endswith(".ghuser")):
                    continue
                uo = GH_UserObject(os.path.join(dirpath, fn))
                name = uo.Description.Name
                if name in found:
                    dupes.append(os.path.join(dirpath, fn))
                else:
                    found[name] = uo
    return found, dupes


def _signature(obj):
    """(code, inputs, outputs) as stored in the component's serialized form."""
    chunk = GH_LooseChunk("sig")
    obj.Write(chunk)
    script = chunk.FindChunk("Script")
    code = None
    if script is not None and script.ItemExists("Text"):
        code = base64.b64decode(script.GetString("Text")).decode("utf-8").replace("\r\n", "\n")
    params = chunk.FindChunk("ParameterData")

    def ports(kind, count_key):
        out = []
        for i in range(params.GetInt32(count_key) if params else 0):
            p = params.FindChunk(kind, i)
            hint = str(p.GetGuid("TypeHintID")) if p.ItemExists("TypeHintID") else ""
            access = p.GetInt32("ScriptParamAccess") if p.ItemExists("ScriptParamAccess") else 0
            out.append((p.GetString("Name"), access, hint))
        return out

    return code, ports("InputParam", "InputCount"), ports("OutputParam", "OutputCount")


def _sync_group(doc, obj):
    for g in doc.Objects:
        if isinstance(g, GH_Group) and str(g.NickName).startswith(GROUP_TAG) \
                and obj.InstanceGuid in g.ObjectIDs:
            return g
    return None


def _plan(doc, installed, me):
    """Classify every USC component on the canvas."""
    plan = {"current": [], "replace": [], "beside": [], "pending": [], "unknown": []}
    for obj in list(doc.Objects):
        if not isinstance(obj, Grasshopper.Kernel.IGH_Component) or obj.InstanceGuid == me:
            continue
        name = str(obj.Name)
        if not name.startswith("USC "):
            continue
        uo = installed.get(name)
        if uo is None:
            plan["unknown"].append(name)
            continue
        new = uo.InstantiateObject()
        old_sig, new_sig = _signature(obj), _signature(new)
        if old_sig == new_sig:
            plan["current"].append(name)
            continue
        same_ports = [p[0] for p in old_sig[1]] == [p[0] for p in new_sig[1]] and \
            [p[0] for p in old_sig[2]] == [p[0] for p in new_sig[2]]
        if same_ports:
            plan["replace"].append((obj, new))
        elif _sync_group(doc, obj) is not None:
            plan["pending"].append(name)  # already placed beside, awaiting rewiring
        else:
            plan["beside"].append((obj, new, _port_diff(old_sig, new_sig)))
    return plan


def _port_diff(old_sig, new_sig):
    parts = []
    for label, o, n in (("inputs", old_sig[1], new_sig[1]), ("outputs", old_sig[2], new_sig[2])):
        on, nn = [p[0] for p in o], [p[0] for p in n]
        added = [x for x in nn if x not in on]
        removed = [x for x in on if x not in nn]
        if added:
            parts.append("new {}: {}".format(label, ", ".join(added)))
        if removed:
            parts.append("removed {}: {}".format(label, ", ".join(removed)))
        if on != nn and not added and not removed:
            parts.append("{} reordered".format(label))
    return "; ".join(parts)


def _copy_param_state(src, dst):
    dst.DataMapping = src.DataMapping
    dst.Reverse = src.Reverse
    dst.Simplify = src.Simplify
    data = getattr(src, "PersistentData", None)
    if data is not None and data.DataCount and getattr(dst, "PersistentData", None) is not None:
        dst.PersistentData.Clear()
        for path in data.Paths:
            for item in data.get_Branch(path):
                if item is not None:
                    dst.PersistentData.Append(item.Duplicate(), path)


def _replace(doc, old, new, records):
    new.CreateAttributes()
    new.Attributes.Pivot = old.Attributes.Pivot
    new.Attributes.ExpireLayout()
    doc.AddObject(new, False)
    records.append(doc.UndoUtil.CreateAddObjectEvent("USC sync", new))
    for o, n in zip(old.Params.Input, new.Params.Input):
        _copy_param_state(o, n)
        for src in list(o.Sources):
            n.AddSource(src)
    for o, n in zip(old.Params.Output, new.Params.Output):
        n.DataMapping = o.DataMapping
        for rec in list(o.Recipients):
            records.append(doc.UndoUtil.CreateWireEvent("USC sync", rec))
            rec.ReplaceSource(o, n)
    new.Locked = old.Locked
    if hasattr(old, "Hidden"):
        new.Hidden = old.Hidden
    for g in list(doc.Objects):
        if isinstance(g, GH_Group) and old.InstanceGuid in g.ObjectIDs:
            records.append(doc.UndoUtil.CreateGenericObjectEvent("USC sync", g))
            g.AddObject(new.InstanceGuid)
            g.RemoveObject(old.InstanceGuid)
    records.append(doc.UndoUtil.CreateRemoveObjectEvent("USC sync", old))
    doc.RemoveObject(old, False)


def _place_beside(doc, old, new, note, records):
    new.CreateAttributes()
    bounds = old.Attributes.Bounds
    new.Attributes.Pivot = System.Drawing.PointF(
        old.Attributes.Pivot.X + bounds.Width + 60, old.Attributes.Pivot.Y)
    new.Attributes.ExpireLayout()
    doc.AddObject(new, False)
    records.append(doc.UndoUtil.CreateAddObjectEvent("USC sync", new))
    group = GH_Group()
    group.CreateAttributes()
    group.NickName = "{} {}. Rewire the new {} (right), then delete the old one (left).".format(
        GROUP_TAG, note, old.Name)
    group.Colour = GROUP_COLOUR
    group.Border = GH_GroupBorder.Blob
    group.AddObject(old.InstanceGuid)
    group.AddObject(new.InstanceGuid)
    doc.AddObject(group, False)
    records.append(doc.UndoUtil.CreateAddObjectEvent("USC sync", group))


def _merged(records):
    """One undo record holding every action, in the order they happened."""
    merged = GH_UndoRecord("USC Sync Canvas")
    for rec in records:
        for action in rec.Actions:
            merged.AddAction(action)
    return merged


def _apply(doc, plan, comp):
    """Runs between solutions. All or nothing: a failure rolls back."""
    records = []
    try:
        try:
            for old, new in plan["replace"]:
                _replace(doc, old, new, records)
            for old, new, note in plan["beside"]:
                _place_beside(doc, old, new, note, records)
        except Exception:
            sc.sticky[_ERROR_KEY] = traceback.format_exc()
            _merged(records).Undo(doc)
            records = []
        if records:
            doc.UndoServer.PushUndoRecord(_merged(records))
    except Exception:
        sc.sticky[_ERROR_KEY] = traceback.format_exc()
    finally:
        comp.ExpireSolution(False)  # re-run to report the post-update state


def _report(plan, applied, source, dupes, my_status):
    verb = ("replaced", "placed beside") if applied else ("would replace", "would place beside")
    lines = ["Source: {}".format(source)]
    if plan["replace"]:
        lines.append("{} in place ({}): {}".format(
            verb[0].capitalize(), len(plan["replace"]),
            ", ".join(sorted(str(o.Name) for o, _ in plan["replace"]))))
    for old, _new, note in plan["beside"]:
        lines.append("{} {} (I/O changed: {})".format(verb[1].capitalize(), old.Name, note))
    if plan["pending"]:
        lines.append("Awaiting manual rewiring (red groups): " + ", ".join(sorted(plan["pending"])))
    lines.append("Up to date ({}): {}".format(
        len(plan["current"]), ", ".join(sorted(plan["current"])) or "-"))
    if plan["unknown"]:
        lines.append("No installed .ghuser for: " + ", ".join(sorted(set(plan["unknown"]))))
    if dupes:
        lines.append("Duplicate .ghuser files ignored: " + "; ".join(dupes))
    if my_status:
        lines.append(my_status)
    if not applied and (plan["replace"] or plan["beside"]):
        lines.append("Set update=True to apply (one undo step).")
    return "\n".join(lines)


report = None
_doc = ghenv.Component.OnPingDocument()
_folder = str(folder).strip() if globals().get("folder") else None
if _folder and not os.path.isdir(_folder):
    report = "ERROR: folder not found: {}".format(_folder)
elif _doc is not None:
    _found, _dupes = _installed(_folder)
    if not _found:
        report = "ERROR: no USC .ghuser files found in {}".format(
            _folder or "the Grasshopper User Objects folders")
    else:
        _plan_now = _plan(_doc, _found, ghenv.Component.InstanceGuid)
        _mine = _found.get(str(ghenv.Component.Name))
        _my_status = None
        if _mine is not None and _signature(_mine.InstantiateObject())[0] != _signature(ghenv.Component)[0]:
            _my_status = "This USC Sync Canvas is itself outdated: drag a fresh one from the ribbon."
        _last_error = sc.sticky.pop(_ERROR_KEY, None)
        _apply_now = bool(globals().get("update")) and not _last_error and \
            bool(_plan_now["replace"] or _plan_now["beside"])
        if _apply_now:
            # The canvas cannot change mid-solution: apply right after it.
            _me = ghenv.Component
            _doc.ScheduleSolution(5, GH_Document.GH_ScheduleDelegate(
                lambda d: _apply(d, _plan_now, _me)))
        report = _report(_plan_now, _apply_now, _folder or "installed user objects", _dupes, _my_status)
        if _last_error:
            ghenv.Component.AddRuntimeMessage(
                GH_RuntimeMessageLevel.Error,
                "Update failed and was rolled back; the canvas is unchanged. See report.")
            report = "UPDATE FAILED, rolled back:\n{}\n{}".format(_last_error, report)
