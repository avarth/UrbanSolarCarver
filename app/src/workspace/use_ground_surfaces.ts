// Test surfaces drawn on the ground (design/test-surfaces-on-ground.md): the tool of the site editor that draws them, and the drawn set
// it edits. Draw saves the closed outline at once as a new set ("Ground n") and turns to editing it; Edit outline reads a set's outline
// and edits it; every change (a vertex moved, a hole drawn) is shown at once and saved over the set, the saves sent one after another so
// quick changes build on each other. Undo and Redo step through this editing session's outlines, each saved again; closing the editor
// ends the session. A refused change puts the outline back as it was and shows the reason.
import { useRef, useState } from "react";
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
  const [tool, setToolState] = useState<GroundTool | null>(null);
  // The tool as last set, and the number of the last outline read asked for: a reply that comes after the user moved on is dropped
  const toolNow = useRef<GroundTool | null>(null);
  const outlineAsked = useRef(0);
  const setTool = (next: GroundTool | null) => {
    toolNow.current = next;
    if (next === null || next.kind === "draw") outlineAsked.current += 1;
    setToolState(next);
  };
  const [session, setSessionState] = useState<Session | null>(null);
  // The session as last set, read by changes made before React renders again; and the saves still on their way, in order
  const sessionNow = useRef<Session | null>(null);
  const saves = useRef<Promise<unknown>>(Promise.resolve());
  const setSession = (next: Session | null) => {
    sessionNow.current = next;
    setSessionState(next);
  };
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
  /** Shows *after* at once and saves its outline after the saves still on their way; puts *before* back when it is refused. */
  const showAndStore = async (before: Session, after: Session): Promise<boolean> => {
    setSession(after);
    const stored = saves.current.then(() => store(after.file, after.outlines[after.at]));
    saves.current = stored;
    const ok = await stored;
    if (!ok && sessionNow.current === after) setSession(before);
    return ok;
  };
  const save = (next: GroundOutline): Promise<boolean> => {
    const now = sessionNow.current;
    if (!now) return Promise.resolve(false);
    return showAndStore(now, { ...now, outlines: [...now.outlines.slice(0, now.at + 1), next], at: now.at + 1 });
  };
  const stepBy = (step: number) => {
    const now = sessionNow.current;
    if (!now || now.at + step < 0 || now.at + step >= now.outlines.length) return;
    void showAndStore(now, { ...now, at: now.at + step });
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
    const asked = ++outlineAsked.current;
    getGroundOutline(token, project, next.file)
      .then((read) => {
        if (asked === outlineAsked.current) setSession({ file: next.file, outlines: [{ points: read.points, holes: read.holes ?? [] }], at: 0 });
      })
      .catch((error: unknown) => {
        if (asked !== outlineAsked.current) return;
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
        .then((stored) => { if (stored) setTool({ kind: "edit", file }); });
      return;
    }
    if (tool?.kind !== "draw") return;
    const drawn: GroundOutline = { points, holes: [] };
    drawSurfaceSet(token, project, { outline: drawn })
      .then(async (stored) => {
        // The set is listed first, then edited, unless the editor was closed or another tool started meanwhile
        await onSaved();
        if (toolNow.current?.kind !== "draw") return;
        setRefusal(null);
        setSession({ file: stored.name, outlines: [drawn], at: 0 });
        setTool({ kind: "edit", file: stored.name });
      })
      .catch(failed);
  };

  // The editor's view of the session: the edited set as a one-site list (its height is not used), and its tool
  const site: Site | null = outline ? { name: shownName, points: outline.points as SitePoint[], height: 1, holes: (outline.holes ?? []) as SitePoint[][] } : null;
  const editorTool: SiteTool | null = tool === null ? null : tool.kind === "draw" ? { kind: "draw" }
    : site === null ? null : tool.kind === "edit" ? { kind: "edit", index: 0 } : { kind: "draw_hole", index: 0 };
  return {
    tool, editorTool, site, refusal, newName: nextGroundName(sets), start, close, finishDrawing,
    /** The stored file of the set being edited (or read for editing); null while drawing a new one or with no tool. */
    editedFile: tool === null || tool.kind === "draw" ? null : tool.file,
    /** Ends the tool and the session, whatever it was doing (another tool started, the step closed). */
    end: () => {
      setTool(null);
      setSession(null);
      setRefusal(null);
    },
    change: (changed: Site) => { void save({ points: changed.points, holes: changed.holes ?? [] }); },
    startHole: () => { if (session) start({ kind: "draw_hole", file: session.file }); },
    undo: () => stepBy(-1),
    redo: () => stepBy(1),
    canUndo: session !== null && session.at > 0,
    canRedo: session !== null && session.at < session.outlines.length - 1,
  };
}
