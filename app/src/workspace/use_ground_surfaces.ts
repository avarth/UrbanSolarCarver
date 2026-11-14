// Test surfaces drawn on the ground (design/test-surfaces-on-ground.md): the tool of the site editor that draws them, and the drawn set
// it edits. Draw saves the closed outline at once as a new set ("Ground n") and turns to editing it; Edit outline reads a set's outline
// and edits it; every change (a vertex moved, a hole drawn) is saved over the set. Undo and Redo step through this editing session's
// outlines, each saved again; closing the editor ends the session. A refused change keeps the set as it was and shows the reason.
import { useState } from "react";
import { drawSurfaceSet, failureTextOf, getGroundOutline, reportServiceProblem, type GroundOutline, type InputFileInfo } from "../api_client/client";
import type { SiteTool } from "../sites/SiteEditor";
import type { Site, SitePoint } from "../sites/site_geometry";

/** Drawing a new set, editing the drawn set stored as *file*, or drawing a hole in it. */
export type GroundTool = { kind: "draw" } | { kind: "edit"; file: string } | { kind: "draw_hole"; file: string };

interface Session {
  file: string;
  outlines: GroundOutline[];
  at: number;
}

interface GroundSurfacesOptions {
  token: string;
  project: string;
  /** The project's surface sets, for the names shown and the next "Ground n". */
  sets: InputFileInfo[];
  /** After a set is saved: the stored files are read again. */
  onSaved: () => Promise<void> | void;
  onServiceProblem: (error: unknown) => void;
}

/** "Ground n" with the lowest n no set is shown by, as the service names a new set. */
export function nextGroundName(sets: readonly InputFileInfo[]): string {
  const shown = new Set(sets.map((set) => (set.shown_name ?? set.name.replace(/\.[^.]*$/, "")).toLowerCase()));
  let number = 1;
  while (shown.has(`ground ${number}`)) number += 1;
  return `Ground ${number}`;
}

export function useGroundSurfaces({ token, project, sets, onSaved, onServiceProblem }: GroundSurfacesOptions) {
  const [tool, setTool] = useState<GroundTool | null>(null);
  const [session, setSession] = useState<Session | null>(null);
  const [refusal, setRefusal] = useState<string | null>(null);
  const outline = session ? session.outlines[session.at] : null;
  const shownName = session ? sets.find((set) => set.name === session.file)?.shown_name ?? session.file : "";

  const failed = (error: unknown) => {
    if (!reportServiceProblem(error, onServiceProblem)) setRefusal(failureTextOf(error));
  };
  /** Saves *next* over the edited set; true when it was stored. */
  const store = async (file: string, next: GroundOutline): Promise<boolean> => {
    try {
      await drawSurfaceSet(token, project, { outline: next, replace: file });
      setRefusal(null);
      await onSaved();
      return true;
    } catch (error) {
      failed(error);
      return false;
    }
  };
  const save = async (next: GroundOutline) => {
    if (!session) return;
    if (await store(session.file, next)) {
      setSession((now) => now && { ...now, outlines: [...now.outlines.slice(0, now.at + 1), next], at: now.at + 1 });
    }
  };
  const stepTo = async (at: number) => {
    if (!session || at < 0 || at >= session.outlines.length) return;
    if (await store(session.file, session.outlines[at])) setSession((now) => now && { ...now, at });
  };

  const start = (next: GroundTool) => {
    setRefusal(null);
    if (next.kind === "draw") {
      setSession(null);
      setTool(next);
      return;
    }
    if (next.kind === "draw_hole" && session?.file === next.file) {
      setTool(next);
      return;
    }
    setSession(null);
    setTool(next);
    getGroundOutline(token, project, next.file)
      .then((read) => setSession({ file: next.file, outlines: [{ points: read.points, holes: read.holes ?? [] }], at: 0 }))
      .catch((error: unknown) => {
        failed(error);
        setTool(null);
      });
  };
  const close = () => {
    setRefusal(null);
    if (tool?.kind === "draw_hole") {
      setTool({ kind: "edit", file: tool.file });
      return;
    }
    setTool(null);
    setSession(null);
  };
  const finishDrawing = (points: SitePoint[]) => {
    if (tool?.kind === "draw_hole" && outline) {
      const z = outline.points[0][2];
      const file = tool.file;
      void save({ ...outline, holes: [...(outline.holes ?? []), points.map((point): number[] => [point[0], point[1], z])] })
        .then(() => setTool({ kind: "edit", file }));
      return;
    }
    if (tool?.kind !== "draw") return;
    const drawn: GroundOutline = { points, holes: [] };
    drawSurfaceSet(token, project, { outline: drawn })
      .then(async (stored) => {
        setRefusal(null);
        setSession({ file: stored.name, outlines: [drawn], at: 0 });
        setTool({ kind: "edit", file: stored.name });
        await onSaved();
      })
      .catch(failed);
  };

  // The editor's view of the session: the edited set as a one-site list (its height is not used), and its tool
  const site: Site | null = outline ? { name: shownName, points: outline.points as SitePoint[], height: 1, holes: (outline.holes ?? []) as SitePoint[][] } : null;
  const editorTool: SiteTool | null = tool === null ? null : tool.kind === "draw" ? { kind: "draw" }
    : site === null ? null : tool.kind === "edit" ? { kind: "edit", index: 0 } : { kind: "draw_hole", index: 0 };
  return {
    tool, editorTool, site, refusal, newName: nextGroundName(sets), start, close, finishDrawing,
    /** Ends the tool and the session, whatever it was doing (another tool started, the step closed). */
    end: () => {
      setTool(null);
      setSession(null);
      setRefusal(null);
    },
    change: (changed: Site) => { void save({ points: changed.points, holes: changed.holes ?? [] }); },
    startHole: () => { if (session) start({ kind: "draw_hole", file: session.file }); },
    undo: () => { if (session) void stepTo(session.at - 1); },
    redo: () => { if (session) void stepTo(session.at + 1); },
    canUndo: session !== null && session.at > 0,
    canRedo: session !== null && session.at < session.outlines.length - 1,
  };
}
