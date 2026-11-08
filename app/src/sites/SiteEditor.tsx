// Drawing and editing sites in the 3D view (design/site-input.md). An overlay over the view: the outlines, the line to the pointer,
// the vertex handles and labels are SVG, projected from the scene on every camera change; the bar with the steps and the elevation
// field are HTML. The overlay takes the pointer only on the bar, the handles and the edges, so the view still orbits.
// Drawing: each click on the view adds a point on the drawing level (snapped to the first point, to the vertices and edges of the
// other sites, or with Shift to 15 degree steps); the first point or Enter closes the outline, Backspace removes the last point,
// Escape cancels. Editing: a handle dragged moves its vertex in plan, a handle clicked selects it and shows its elevation field,
// a double click on an edge adds a vertex, Delete removes the selected one. Every change goes to *onChangeSite*; a change that would
// make the site refused is not sent and its reason is shown. Points are in the input files' coordinates; the scene works in local
// ones (*origin* subtracted).
import { useEffect, useEffectEvent, useRef, useState, type PointerEvent as ReactPointerEvent } from "react";
import { formattedNumber } from "../format_numbers";
import { messages } from "../messages";
import type { Point3 } from "../viewer/local_origin";
import type { ViewerScene } from "../viewer/scene";
import { nearestOnSegment, placePoint, type PlacedPoint, type ScreenPoint } from "./site_drawing";
import { containsPoint, elevationRange, pointAlong, siteProblems, type Heights, type Site, type SitePoint } from "./site_geometry";
import "./sites.css";

export type SiteTool = { kind: "draw" } | { kind: "edit"; index: number };

type SceneForSites = Pick<ViewerScene, "onCameraChange" | "onViewClick" | "toScreen" | "pointOnLevel" | "viewTop">;

export interface SiteEditorProps {
  scene: SceneForSites;
  origin: Point3;
  sites: Site[];
  tool: SiteTool;
  /** The drawing level in the files' coordinates. */
  level: number;
  /** The name the site being drawn will get. */
  newSiteName: string;
  onFinishDrawing: (points: SitePoint[]) => void;
  onChangeSite: (index: number, site: Site) => void;
  onClose: () => void;
  onUndo: () => void;
  onRedo: () => void;
  canUndo: boolean;
  canRedo: boolean;
  /** The service's reason the last change was refused, if any. */
  refusal: string | null;
  /** The max and base heights the sites are checked with. */
  heights?: Heights;
}

const DRAG_START_PIXELS = 3;

/** Keeps the pointer's moves on the handle while it is dragged; a pointer the browser no longer tracks is left alone. */
function capturePointer(element: Element, pointerId: number, capture: boolean): void {
  try {
    if (capture) element.setPointerCapture?.(pointerId);
    else if (element.hasPointerCapture?.(pointerId)) element.releasePointerCapture(pointerId);
  } catch {
    // A pointer that has already gone (a synthetic one, or released by the browser) cannot be captured
  }
}

/** Points are kept to the millimetre: finer is noise from the pointer. */
function toMillimetre(value: number): number {
  return Math.round(value * 1000) / 1000;
}

function isTyping(target: EventTarget | null): boolean {
  return target instanceof HTMLElement && (target.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName));
}

export function SiteEditor(props: SiteEditorProps) {
  const { scene, origin, sites, tool, level } = props;
  const overlay = useRef<HTMLDivElement>(null);
  const [, setCameraTick] = useState(0);
  useEffect(() => scene.onCameraChange(() => setCameraTick((tick) => tick + 1)), [scene]);

  const toLocal = (point: SitePoint): Point3 => [point[0] - origin[0], point[1] - origin[1], point[2] - origin[2]];
  const toScreen = (point: SitePoint): ScreenPoint | null => scene.toScreen(toLocal(point));
  const groundAt = (x: number, y: number, z: number): SitePoint | null => {
    const local = scene.pointOnLevel(x, y, z - origin[2]);
    return local ? [toMillimetre(local[0] + origin[0]), toMillimetre(local[1] + origin[1]), z] : null;
  };

  // Drawing starts from the top view, north up
  const startsDrawing = tool.kind === "draw";
  useEffect(() => {
    if (startsDrawing) scene.viewTop();
  }, [scene, startsDrawing]);

  // ---- Drawing
  const [drawn, setDrawn] = useState<SitePoint[]>([]);
  const [hover, setHover] = useState<PlacedPoint | null>(null);
  const editedIndex = tool.kind === "edit" ? tool.index : null;
  const otherOutlines = sites.filter((_, index) => index !== editedIndex).map((site) => site.points);
  const placeAt = (x: number, y: number, shift: boolean): PlacedPoint | null => {
    const ground = groundAt(x, y, level);
    return ground ? placePoint(drawn, ground, [x, y], otherOutlines, toScreen, shift) : null;
  };
  const finishDrawing = () => {
    if (drawn.length < 3) return;
    props.onFinishDrawing(drawn);
    setDrawn([]);
    setHover(null);
  };
  const viewClicked = useEffectEvent((x: number, y: number, shift: boolean) => {
    if (tool.kind !== "draw") return;
    const placed = placeAt(x, y, shift);
    if (!placed) return;
    if (placed.snap === "first_point") finishDrawing();
    else setDrawn((points) => [...points, placed.point]);
  });
  useEffect(() => scene.onViewClick(({ x, y, shift }) => viewClicked(x, y, shift)), [scene]);
  const pointerMoved = useEffectEvent((event: PointerEvent) => {
    if (tool.kind !== "draw" || !overlay.current) return;
    const bounds = overlay.current.getBoundingClientRect();
    const x = event.clientX - bounds.left, y = event.clientY - bounds.top;
    setHover(x < 0 || y < 0 || x > bounds.width || y > bounds.height ? null : placeAt(x, y, event.shiftKey));
  });
  useEffect(() => {
    const listener = (event: PointerEvent) => pointerMoved(event);
    window.addEventListener("pointermove", listener);
    return () => window.removeEventListener("pointermove", listener);
  }, []);

  // ---- Editing
  const [selected, setSelected] = useState<number | null>(null);
  const [dragged, setDragged] = useState<{ vertex: number; points: SitePoint[] } | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const press = useRef<{ vertex: number; x: number; y: number; moved: boolean } | null>(null);
  const edited = editedIndex === null ? null : sites[editedIndex] ?? null;
  const shownPoints = dragged?.points ?? edited?.points ?? [];
  const changeEdited = (points: SitePoint[]) => {
    if (editedIndex === null || !edited) return false;
    const candidate = { ...edited, points };
    const problems = siteProblems(candidate, props.heights);
    if (problems.length) {
      setProblem(messages.siteNotSaved(problems.join("; ")));
      return false;
    }
    setProblem(null);
    props.onChangeSite(editedIndex, candidate);
    return true;
  };
  const handleDown = (vertex: number) => (event: ReactPointerEvent<SVGCircleElement>) => {
    if (event.button !== 0) return;
    event.stopPropagation();
    capturePointer(event.currentTarget, event.pointerId, true);
    press.current = { vertex, x: event.clientX, y: event.clientY, moved: false };
  };
  const handleMove = (event: ReactPointerEvent<SVGCircleElement>) => {
    const start = press.current;
    if (!start || !edited || !overlay.current) return;
    if (!start.moved && Math.hypot(event.clientX - start.x, event.clientY - start.y) < DRAG_START_PIXELS) return;
    start.moved = true;
    const bounds = overlay.current.getBoundingClientRect();
    const z = edited.points[start.vertex][2];
    const ground = groundAt(event.clientX - bounds.left, event.clientY - bounds.top, z);
    if (!ground) return;
    const points = edited.points.map((point, index) => (index === start.vertex ? ground : point));
    setDragged({ vertex: start.vertex, points });
    const problems = siteProblems({ ...edited, points }, props.heights);
    setProblem(problems.length ? messages.siteNotSaved(problems.join("; ")) : null);
  };
  const handleUp = (event: ReactPointerEvent<SVGCircleElement>) => {
    const start = press.current;
    press.current = null;
    capturePointer(event.currentTarget, event.pointerId, false);
    if (!start) return;
    if (start.moved && dragged) {
      changeEdited(dragged.points);
      setDragged(null);
    } else {
      setSelected(start.vertex);
    }
  };
  const edgeDoubleClicked = (edge: number) => (event: React.MouseEvent<SVGLineElement>) => {
    if (!edited || !overlay.current) return;
    const a = edited.points[edge], b = edited.points[(edge + 1) % edited.points.length];
    const aScreen = toScreen(a), bScreen = toScreen(b);
    if (!aScreen || !bScreen) return;
    const bounds = overlay.current.getBoundingClientRect();
    const { t } = nearestOnSegment(aScreen, bScreen, [event.clientX - bounds.left, event.clientY - bounds.top]);
    const points = [...edited.points];
    points.splice(edge + 1, 0, pointAlong(a, b, t));
    if (changeEdited(points)) setSelected(edge + 1);
  };
  const removeSelected = () => {
    if (!edited || selected === null || edited.points.length <= 3) return;
    if (changeEdited(edited.points.filter((_, index) => index !== selected))) setSelected(null);
  };
  const setElevation = (vertex: number, z: number) => {
    if (!edited) return;
    changeEdited(edited.points.map((point, index) => (index === vertex ? [point[0], point[1], z] : point)));
  };

  // A new tool, or another site to edit: nothing drawn, nothing selected
  const toolKey = tool.kind === "edit" ? `edit-${tool.index}` : "draw";
  const [shownToolKey, setShownToolKey] = useState(toolKey);
  if (shownToolKey !== toolKey) {
    setShownToolKey(toolKey);
    setDrawn([]);
    setHover(null);
    setSelected(null);
    setDragged(null);
    setProblem(null);
  }

  const keyPressed = useEffectEvent((event: KeyboardEvent) => {
    if (isTyping(event.target)) return;
    const control = event.ctrlKey || event.metaKey;
    if (control && event.key.toLowerCase() === "z") {
      event.preventDefault();
      if (event.shiftKey) props.onRedo();
      else props.onUndo();
      return;
    }
    if (control && event.key.toLowerCase() === "y") {
      event.preventDefault();
      props.onRedo();
      return;
    }
    if (tool.kind === "draw") {
      if (event.key === "Enter") finishDrawing();
      else if (event.key === "Backspace") setDrawn((points) => points.slice(0, -1));
      else if (event.key === "Escape") props.onClose();
      else return;
      event.preventDefault();
    } else {
      if (event.key === "Delete" || event.key === "Backspace") removeSelected();
      else if (event.key === "Escape") {
        if (selected !== null) setSelected(null);
        else props.onClose();
      } else return;
      event.preventDefault();
    }
  });
  useEffect(() => {
    const listener = (event: KeyboardEvent) => keyPressed(event);
    window.addEventListener("keydown", listener);
    return () => window.removeEventListener("keydown", listener);
  }, []);

  // ---- Drawing on the screen
  const screenPath = (points: SitePoint[], closed: boolean) => {
    const projected = points.map(toScreen);
    if (projected.some((point) => point === null)) return null;
    const text = (projected as ScreenPoint[]).map(([x, y]) => `${x.toFixed(1)},${y.toFixed(1)}`).join(" ");
    return closed ? <polygon points={text} /> : <polyline points={text} />;
  };
  const lowest = shownPoints.length ? elevationRange(shownPoints)[0] : 0;
  const lastDrawn = drawn[drawn.length - 1];
  const hoverScreen = hover ? toScreen(hover.point) : null;
  const lastScreen = lastDrawn ? toScreen(lastDrawn) : null;
  const firstScreen = drawn.length ? toScreen(drawn[0]) : null;
  const selectedScreen = selected !== null && shownPoints[selected] ? toScreen(shownPoints[selected]) : null;
  const shownProblem = problem ?? props.refusal;

  return (
    <div ref={overlay} className="site-editor">
      <div className="site-editor-bar" role="toolbar" aria-label={tool.kind === "draw" ? messages.drawingSite(props.newSiteName) : messages.editingSite(edited?.name ?? "")}>
        <strong>{tool.kind === "draw" ? messages.drawingSite(props.newSiteName) : messages.editingSite(edited?.name ?? "")}</strong>
        <span className="site-editor-steps">{tool.kind === "draw" ? messages.drawingSteps : messages.editingSteps}</span>
        <span className="site-editor-buttons">
          <button type="button" className="secondary-button" onClick={props.onUndo} disabled={!props.canUndo}>{messages.undoSiteChange}</button>
          <button type="button" className="secondary-button" onClick={props.onRedo} disabled={!props.canRedo}>{messages.redoSiteChange}</button>
          {tool.kind === "draw" && <button type="button" className="secondary-button" onClick={props.onClose}>{messages.cancelDrawing}</button>}
          <button type="button" className="primary-button" onClick={tool.kind === "draw" && drawn.length >= 3 ? finishDrawing : props.onClose}>
            {messages.doneDrawing}
          </button>
        </span>
        {shownProblem && <span className="site-editor-problem" role="alert">{shownProblem}</span>}
      </div>
      <svg className="site-editor-drawing" aria-hidden="true">
        <g className="site-editor-others">
          {otherOutlines.map((points, index) => <g key={index}>{screenPath(points, true)}</g>)}
        </g>
        {tool.kind === "draw" && (
          <g className="site-editor-drawn">
            {screenPath(drawn, false)}
            {lastScreen && hoverScreen && <line className="site-editor-rubber" x1={lastScreen[0]} y1={lastScreen[1]} x2={hoverScreen[0]} y2={hoverScreen[1]} />}
            {firstScreen && <circle className={`site-editor-first${hover?.snap === "first_point" ? " site-editor-snapped" : ""}`} cx={firstScreen[0]} cy={firstScreen[1]} r={6} />}
            {drawn.slice(1).map((point, index) => {
              const at = toScreen(point);
              return at && <circle key={index} className="site-editor-vertex" cx={at[0]} cy={at[1]} r={3.5} />;
            })}
            {hoverScreen && hover?.snap && hover.snap !== "first_point" && <circle className="site-editor-snap" cx={hoverScreen[0]} cy={hoverScreen[1]} r={7} />}
            {lastScreen && hoverScreen && lastDrawn && hover && (
              <text className="site-editor-label" x={(lastScreen[0] + hoverScreen[0]) / 2 + 8} y={(lastScreen[1] + hoverScreen[1]) / 2 - 8}>
                {messages.segmentLength(Math.hypot(hover.point[0] - lastDrawn[0], hover.point[1] - lastDrawn[1]))}
              </text>
            )}
          </g>
        )}
        {tool.kind === "edit" && edited && (
          <g className={`site-editor-edited${problem ? " site-editor-refused" : ""}`}>
            {screenPath(shownPoints, true)}
            {shownPoints.map((point, index) => {
              const a = toScreen(point), b = toScreen(shownPoints[(index + 1) % shownPoints.length]);
              return a && b && <line key={`edge-${index}`} className="site-editor-edge" x1={a[0]} y1={a[1]} x2={b[0]} y2={b[1]} onDoubleClick={edgeDoubleClicked(index)} />;
            })}
            {shownPoints.map((point, index) => {
              const at = toScreen(point);
              if (!at) return null;
              return (
                <g key={`vertex-${index}`}>
                  <circle className={`site-editor-handle${selected === index ? " site-editor-selected" : ""}`} cx={at[0]} cy={at[1]} r={7}
                          aria-label={messages.vertexHandle(index + 1)} onPointerDown={handleDown(index)} onPointerMove={handleMove} onPointerUp={handleUp} />
                  <text className="site-editor-label" x={at[0] + 10} y={at[1] - 10}>{`${point[2] - lowest >= 0 ? "+" : ""}${formattedNumber(point[2] - lowest)}`}</text>
                </g>
              );
            })}
          </g>
        )}
      </svg>
      {tool.kind === "edit" && edited && selected !== null && selectedScreen && shownPoints[selected] && (
        <ElevationField key={`${selected}-${shownPoints[selected][2]}`} at={selectedScreen} value={shownPoints[selected][2]}
                        othersLowest={Math.min(...shownPoints.filter((_, index) => index !== selected).map((point) => point[2]))}
                        vertexNumber={selected + 1} onCommit={(z) => setElevation(selected, z)} onCancel={() => setSelected(null)} />
      )}
    </div>
  );
}

interface ElevationFieldProps {
  at: ScreenPoint;
  value: number;
  /** The lowest elevation of the site's other vertices. */
  othersLowest: number;
  vertexNumber: number;
  onCommit: (z: number) => void;
  onCancel: () => void;
}

/** The elevation of the selected vertex, in the files' coordinates, with its height above the site's lowest vertex beside it. */
function ElevationField({ at, value, othersLowest, vertexNumber, onCommit, onCancel }: ElevationFieldProps) {
  const [text, setText] = useState(String(Math.round(value * 1000) / 1000));
  const typed = Number(text.replace(",", "."));
  const valid = text.trim() !== "" && Number.isFinite(typed);
  return (
    <div className="site-editor-field" style={{ left: at[0] + 14, top: at[1] + 10 }}>
      <label>
        <span>{messages.vertexElevation}</span>
        <input type="text" inputMode="decimal" value={text} aria-invalid={!valid} aria-label={`${messages.vertexHandle(vertexNumber)}: ${messages.vertexElevation}`}
               title={messages.vertexElevationHelp} autoFocus onChange={(event) => setText(event.target.value)}
               onKeyDown={(event) => {
                 if (event.key === "Enter" && valid) onCommit(typed);
                 else if (event.key === "Escape") onCancel();
                 else return;
                 event.preventDefault();
               }} />
        <span className="site-editor-unit">m</span>
      </label>
      <span className="site-editor-relative">{messages.relativeElevation((valid ? typed : value) - Math.min(othersLowest, valid ? typed : value))}</span>
    </div>
  );
}

interface SitePickerProps {
  scene: Pick<ViewerScene, "onViewClick" | "pointOnLevel">;
  origin: Point3;
  sites: Site[];
  onPick: (index: number) => void;
}

/** While the Site card is open and no site is drawn or edited: a click on the view inside a site's outline edits that site. */
export function SitePicker({ scene, origin, sites, onPick }: SitePickerProps) {
  const clicked = useEffectEvent((x: number, y: number) => {
    const index = sites.findIndex((site) => {
      const local = scene.pointOnLevel(x, y, elevationRange(site.points)[0] - origin[2]);
      return local !== null && containsPoint(site.points, local[0] + origin[0], local[1] + origin[1]);
    });
    if (index >= 0) onPick(index);
  });
  useEffect(() => scene.onViewClick(({ x, y }) => clicked(x, y)), [scene]);
  return null;
}
