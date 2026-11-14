// Drawing and editing sites in the 3D view (design/site-input.md). An overlay over the view: the outlines, the line to the pointer,
// the vertex handles and labels are SVG, projected from the scene on every camera change; the bar with the steps and the elevation
// field are HTML. The overlay takes the pointer only on the bar, the handles and the edges, so the view still orbits.
// Drawing: each click on the view adds a point on the drawing level (snapped to the first point, to the vertices and edges of the
// other sites, or with Shift to 15 degree steps); the first point or Enter closes the outline, Backspace removes the last point,
// Escape cancels. The bar's shapes draw a rectangle instead: two opposite corners (Rectangle), or a first side and its width (Tilted
// rectangle); the last click finishes it. Editing: a handle dragged moves its vertex in plan, a handle clicked selects it and shows its elevation field,
// a double click on an edge adds a vertex, Delete removes the selected one. A site's holes (design/site-holes.md) are drawn and edited
// as its outline is, in the same history. Every change goes to *onChangeSite*; a change that would make the site refused is not sent
// and its reason is shown. Points are in the input files' coordinates; the scene works in local ones (*origin* subtracted).
import { useEffect, useEffectEvent, useRef, useState, type PointerEvent as ReactPointerEvent } from "react";
import { formattedNumber } from "../format_numbers";
import { messages } from "../messages";
import type { Point3 } from "../viewer/local_origin";
import type { ViewerScene } from "../viewer/scene";
import {
  CLICKS_TO_FINISH, nearestOnSegment, placeShapePoint, shapeOutline, type DrawShape, type PlacedPoint, type ScreenPoint,
} from "./site_drawing";
import {
  containsPoint, elevationRange, outlinePoints, planArea, pointAlong, ringsOf, siteAreaContains, siteProblems, withRings, type Heights, type Site,
  type SitePoint,
} from "./site_geometry";
import "./sites.css";

/** Drawing a new site, drawing a hole in a site (Draw hole in its editor, design/site-holes.md), or editing a site. */
export type SiteTool = { kind: "draw" } | { kind: "draw_hole"; index: number } | { kind: "edit"; index: number };

/** A vertex of the edited site: its ring (0 the outline, then the holes from 1) and its place in the ring. */
interface VertexAt {
  ring: number;
  vertex: number;
}

/** The name of a vertex's handle: "Vertex 2" on the outline, "Hole 1 vertex 2" on a hole. */
function vertexName({ ring, vertex }: VertexAt): string {
  return ring === 0 ? messages.vertexHandle(vertex + 1) : messages.holeVertexHandle(ring, vertex + 1);
}

/** *rings* with ring *ring* replaced by *points*. */
function replacedRing(rings: SitePoint[][], ring: number, points: SitePoint[]): SitePoint[][] {
  return rings.map((other, index) => (index === ring ? points : other));
}

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
  /** Starts drawing a hole in the edited site (Draw hole); absent: no button. */
  onDrawHole?: (index: number) => void;
  onUndo: () => void;
  onRedo: () => void;
  canUndo: boolean;
  canRedo: boolean;
  /** The service's reason the last change was refused, if any. */
  refusal: string | null;
  /** The max and base heights the sites are checked with. */
  heights?: Heights;
  /** Outlines snapped to besides the other entries of *sites*: the sites while blocks are drawn, the blocks while sites are. */
  snapSites?: Site[];
  /** A vertex's elevation sets every vertex's, so the outline stays on one level (a test surface drawn on the ground). */
  flatElevation?: boolean;
}

const DRAG_START_PIXELS = 3;

const SHAPES: [DrawShape, string][] = [
  ["polygon", messages.shapePolygon], ["rectangle", messages.shapeRectangle], ["tilted_rectangle", messages.shapeTiltedRectangle],
];
const SHAPE_STEPS: Record<DrawShape, string> = {
  polygon: messages.drawingSteps, rectangle: messages.rectangleSteps, tilted_rectangle: messages.tiltedRectangleSteps,
};

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
  const drawing = tool.kind !== "edit";
  const startsDrawing = drawing;
  useEffect(() => {
    if (startsDrawing) scene.viewTop();
  }, [scene, startsDrawing]);

  // ---- Drawing
  const [drawn, setDrawn] = useState<SitePoint[]>([]);
  const [hover, setHover] = useState<PlacedPoint | null>(null);
  const [shape, setShape] = useState<DrawShape>("polygon");
  const chooseShape = (chosen: DrawShape) => {
    setShape(chosen);
    setDrawn([]);
    setHover(null);
  };
  const editedIndex = tool.kind === "edit" ? tool.index : null;
  const otherOutlines = [...sites.filter((_, index) => index !== editedIndex), ...(props.snapSites ?? [])].flatMap((site) => ringsOf(site));
  const placeAt = (x: number, y: number, shift: boolean): PlacedPoint | null => {
    const ground = groundAt(x, y, level);
    return ground ? placeShapePoint(shape, drawn, ground, [x, y], otherOutlines, toScreen, shift) : null;
  };
  const finishDrawing = () => {
    if (drawn.length < 3) return;
    props.onFinishDrawing(drawn);
    setDrawn([]);
    setHover(null);
  };
  const viewClicked = useEffectEvent((x: number, y: number, shift: boolean) => {
    if (!drawing) return;
    const placed = placeAt(x, y, shift);
    if (!placed) return;
    if (shape !== "polygon") {
      const clicks = [...drawn, placed.point];
      if (clicks.length < CLICKS_TO_FINISH[shape]) {
        const [a, b] = clicks;
        if (!b || Math.hypot(b[0] - a[0], b[1] - a[1]) > 0) setDrawn(clicks);
        return;
      }
      const outline = shapeOutline(shape, clicks);
      if (!outline) return;
      props.onFinishDrawing(outline);
      setDrawn([]);
      setHover(null);
    } else if (placed.snap === "first_point") finishDrawing();
    else setDrawn((points) => [...points, placed.point]);
  });
  useEffect(() => scene.onViewClick(({ x, y, shift }) => viewClicked(x, y, shift)), [scene]);
  const pointerMoved = useEffectEvent((event: PointerEvent) => {
    if (!drawing || !overlay.current) return;
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
  const [selected, setSelected] = useState<VertexAt | null>(null);
  const [dragged, setDragged] = useState<SitePoint[][] | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const press = useRef<VertexAt & { x: number; y: number; moved: boolean } | null>(null);
  const edited = editedIndex === null ? null : sites[editedIndex] ?? null;
  const editedRings = edited ? ringsOf(edited) : [];
  const shownRings = dragged ?? editedRings;
  const shownPoints = shownRings.flat();
  const changeEdited = (rings: SitePoint[][]) => {
    if (editedIndex === null || !edited) return false;
    const candidate = withRings(edited, rings);
    const problems = siteProblems(candidate, props.heights);
    if (problems.length) {
      setProblem(messages.siteNotSaved(problems.join("; ")));
      return false;
    }
    setProblem(null);
    props.onChangeSite(editedIndex, candidate);
    return true;
  };
  const handleDown = (at: VertexAt) => (event: ReactPointerEvent<SVGCircleElement>) => {
    if (event.button !== 0) return;
    event.stopPropagation();
    capturePointer(event.currentTarget, event.pointerId, true);
    press.current = { ...at, x: event.clientX, y: event.clientY, moved: false };
  };
  const handleMove = (event: ReactPointerEvent<SVGCircleElement>) => {
    const start = press.current;
    if (!start || !edited || !overlay.current) return;
    if (!start.moved && Math.hypot(event.clientX - start.x, event.clientY - start.y) < DRAG_START_PIXELS) return;
    start.moved = true;
    const bounds = overlay.current.getBoundingClientRect();
    const ring = editedRings[start.ring];
    if (!ring?.[start.vertex]) return;
    const ground = groundAt(event.clientX - bounds.left, event.clientY - bounds.top, ring[start.vertex][2]);
    if (!ground) return;
    const rings = replacedRing(editedRings, start.ring, ring.map((point, index) => (index === start.vertex ? ground : point)));
    setDragged(rings);
    const problems = siteProblems(withRings(edited, rings), props.heights);
    setProblem(problems.length ? messages.siteNotSaved(problems.join("; ")) : null);
  };
  const handleUp = (event: ReactPointerEvent<SVGCircleElement>) => {
    const start = press.current;
    press.current = null;
    capturePointer(event.currentTarget, event.pointerId, false);
    if (!start) return;
    if (start.moved && dragged) {
      changeEdited(dragged);
      setDragged(null);
    } else {
      setSelected({ ring: start.ring, vertex: start.vertex });
    }
  };
  const edgeDoubleClicked = (ringIndex: number, edge: number) => (event: React.MouseEvent<SVGLineElement>) => {
    const ring = editedRings[ringIndex];
    if (!edited || !ring || !overlay.current) return;
    const a = ring[edge], b = ring[(edge + 1) % ring.length];
    const aScreen = toScreen(a), bScreen = toScreen(b);
    if (!aScreen || !bScreen) return;
    const bounds = overlay.current.getBoundingClientRect();
    const { t } = nearestOnSegment(aScreen, bScreen, [event.clientX - bounds.left, event.clientY - bounds.top]);
    const points = [...ring];
    points.splice(edge + 1, 0, pointAlong(a, b, t));
    if (changeEdited(replacedRing(editedRings, ringIndex, points))) setSelected({ ring: ringIndex, vertex: edge + 1 });
  };
  const removeSelected = () => {
    const ring = selected === null ? undefined : editedRings[selected.ring];
    if (!edited || selected === null || !ring || ring.length <= 3) return;
    if (changeEdited(replacedRing(editedRings, selected.ring, ring.filter((_, index) => index !== selected.vertex)))) setSelected(null);
  };
  const setElevation = (at: VertexAt, z: number) => {
    const ring = editedRings[at.ring];
    if (!edited || !ring) return;
    if (props.flatElevation) changeEdited(editedRings.map((points) => points.map((point): SitePoint => [point[0], point[1], z])));
    else changeEdited(replacedRing(editedRings, at.ring, ring.map((point, index): SitePoint => (index === at.vertex ? [point[0], point[1], z] : point))));
  };

  // A new tool, or another site to edit: nothing drawn, nothing selected
  const toolKey = tool.kind === "draw" ? "draw" : `${tool.kind}-${tool.index}`;
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
    if (drawing) {
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
  // A site with its holes as one path, filled between the outline and the holes
  const areaPath = (rings: SitePoint[][]) => {
    const parts: string[] = [];
    for (const ring of rings) {
      const projected = ring.map(toScreen);
      if (projected.some((point) => point === null)) return null;
      parts.push(`M${(projected as ScreenPoint[]).map(([x, y]) => `${x.toFixed(1)},${y.toFixed(1)}`).join(" L")} Z`);
    }
    return <path d={parts.join(" ")} fillRule="evenodd" />;
  };
  const lowest = shownPoints.length ? elevationRange(shownPoints)[0] : 0;
  const lastDrawn = drawn[drawn.length - 1];
  const hoverScreen = hover ? toScreen(hover.point) : null;
  const lastScreen = lastDrawn ? toScreen(lastDrawn) : null;
  const firstScreen = drawn.length ? toScreen(drawn[0]) : null;
  // A rectangle shape's outline with the pointer as its last click, while one is drawn
  const preview = drawing && hover ? shapeOutline(shape, [...drawn, hover.point]) : null;
  const previewScreen = preview?.map(toScreen);
  const previewPath = previewScreen && previewScreen.every((point) => point !== null)
    ? (previewScreen as ScreenPoint[]).map(([x, y]) => `${x.toFixed(1)},${y.toFixed(1)}`).join(" ") : null;
  const selectedPoint = selected === null ? undefined : shownRings[selected.ring]?.[selected.vertex];
  const selectedScreen = selectedPoint ? toScreen(selectedPoint) : null;
  const shownProblem = problem ?? props.refusal;
  const holeOf = tool.kind === "draw_hole" ? sites[tool.index] : undefined;
  const barTitle = tool.kind === "draw" ? messages.drawingSite(props.newSiteName)
    : tool.kind === "draw_hole" ? messages.drawingHole(holeOf?.name ?? "") : messages.editingSite(edited?.name ?? "");

  return (
    <div ref={overlay} className="site-editor">
      <div className="site-editor-bar" role="toolbar" aria-label={barTitle}>
        <strong>{barTitle}</strong>
        {drawing && (
          <span className="segmented-switch site-editor-shapes" role="group" aria-label={messages.drawShapes}>
            {SHAPES.map(([value, label]) => (
              <button key={value} type="button" aria-pressed={shape === value} onClick={() => chooseShape(value)}>
                {label}
              </button>
            ))}
          </span>
        )}
        <span className="site-editor-steps">{drawing ? SHAPE_STEPS[shape] : messages.editingSteps}</span>
        <span className="site-editor-buttons">
          {tool.kind === "edit" && edited && props.onDrawHole && (
            <button type="button" className="secondary-button" onClick={() => props.onDrawHole?.(tool.index)}>{messages.drawHole}</button>
          )}
          <button type="button" className="secondary-button" onClick={props.onUndo} disabled={!props.canUndo}>{messages.undoSiteChange}</button>
          <button type="button" className="secondary-button" onClick={props.onRedo} disabled={!props.canRedo}>{messages.redoSiteChange}</button>
          {drawing && <button type="button" className="secondary-button" onClick={props.onClose}>{messages.cancelDrawing}</button>}
          <button type="button" className="primary-button" onClick={drawing && drawn.length >= 3 ? finishDrawing : props.onClose}>
            {messages.doneDrawing}
          </button>
        </span>
        {shownProblem && <span className="site-editor-problem" role="alert">{shownProblem}</span>}
      </div>
      <svg className="site-editor-drawing" aria-hidden="true">
        <g className="site-editor-others">
          {otherOutlines.map((points, index) => <g key={index}>{screenPath(points, true)}</g>)}
        </g>
        {drawing && shape !== "polygon" && (
          <g className="site-editor-drawn">
            {preview && previewPath && <polygon className="site-editor-preview" points={previewPath} />}
            {!preview && lastScreen && hoverScreen && <line className="site-editor-rubber" x1={lastScreen[0]} y1={lastScreen[1]} x2={hoverScreen[0]} y2={hoverScreen[1]} />}
            {[...drawn, ...(hover ? [hover.point] : [])].map((point, index) => {
              const at = toScreen(point);
              return at && <circle key={index} className="site-editor-vertex" cx={at[0]} cy={at[1]} r={3.5} />;
            })}
            {hoverScreen && hover?.snap && <circle className="site-editor-snap" cx={hoverScreen[0]} cy={hoverScreen[1]} r={7} />}
            {preview && hoverScreen && (
              <text className="site-editor-label" x={hoverScreen[0] + 10} y={hoverScreen[1] - 10}>
                {messages.rectangleSize(Math.hypot(preview[1][0] - preview[0][0], preview[1][1] - preview[0][1]),
                  Math.hypot(preview[2][0] - preview[1][0], preview[2][1] - preview[1][1]))}
              </text>
            )}
            {!preview && lastScreen && hoverScreen && lastDrawn && hover && (
              <text className="site-editor-label" x={(lastScreen[0] + hoverScreen[0]) / 2 + 8} y={(lastScreen[1] + hoverScreen[1]) / 2 - 8}>
                {messages.segmentLength(Math.hypot(hover.point[0] - lastDrawn[0], hover.point[1] - lastDrawn[1]))}
              </text>
            )}
          </g>
        )}
        {drawing && shape === "polygon" && (
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
            {areaPath(shownRings)}
            {shownRings.map((ring, ringIndex) => ring.map((point, index) => {
              const a = toScreen(point), b = toScreen(ring[(index + 1) % ring.length]);
              return a && b && <line key={`edge-${ringIndex}-${index}`} className="site-editor-edge" x1={a[0]} y1={a[1]} x2={b[0]} y2={b[1]}
                                     onDoubleClick={edgeDoubleClicked(ringIndex, index)} />;
            }))}
            {shownRings.map((ring, ringIndex) => ring.map((point, index) => {
              const at = toScreen(point);
              if (!at) return null;
              const isSelected = selected !== null && selected.ring === ringIndex && selected.vertex === index;
              return (
                <g key={`vertex-${ringIndex}-${index}`}>
                  <circle className={`site-editor-handle${isSelected ? " site-editor-selected" : ""}`} cx={at[0]} cy={at[1]} r={7}
                          aria-label={vertexName({ ring: ringIndex, vertex: index })} onPointerDown={handleDown({ ring: ringIndex, vertex: index })}
                          onPointerMove={handleMove} onPointerUp={handleUp} />
                  <text className="site-editor-label" x={at[0] + 10} y={at[1] - 10}>{`${point[2] - lowest >= 0 ? "+" : ""}${formattedNumber(point[2] - lowest)}`}</text>
                </g>
              );
            }))}
          </g>
        )}
      </svg>
      {tool.kind === "edit" && edited && selected !== null && selectedScreen && selectedPoint && (
        <ElevationField key={`${selected.ring}-${selected.vertex}-${selectedPoint[2]}`} at={selectedScreen} value={selectedPoint[2]}
                        othersLowest={Math.min(...shownRings.flatMap((ring, ringIndex) => ring.filter((_, index) => ringIndex !== selected.ring || index !== selected.vertex))
                          .map((point) => point[2]))}
                        vertexName={vertexName(selected)} onCommit={(z) => setElevation(selected, z)} onCancel={() => setSelected(null)} />
      )}
    </div>
  );
}

interface ElevationFieldProps {
  at: ScreenPoint;
  value: number;
  /** The lowest elevation of the site's other vertices. */
  othersLowest: number;
  /** "Vertex 2", or "Hole 1 vertex 2". */
  vertexName: string;
  onCommit: (z: number) => void;
  onCancel: () => void;
}

/** The elevation of the selected vertex, in the files' coordinates, with its height above the site's lowest vertex beside it. */
function ElevationField({ at, value, othersLowest, vertexName: name, onCommit, onCancel }: ElevationFieldProps) {
  const [text, setText] = useState(String(Math.round(value * 1000) / 1000));
  const typed = Number(text.replace(",", "."));
  const valid = text.trim() !== "" && Number.isFinite(typed);
  return (
    <div className="site-editor-field" style={{ left: at[0] + 14, top: at[1] + 10 }}>
      <label>
        <span>{messages.vertexElevation}</span>
        <input type="text" inputMode="decimal" value={text} aria-invalid={!valid} aria-label={`${name}: ${messages.vertexElevation}`}
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
  /** The drawn context blocks, picked the same way (design/context-blocks.md). */
  blocks?: Site[];
  onPickBlock?: (index: number) => void;
}

/** While the Site step is open and no site or block is drawn or edited: a click on the view inside a site's or a block's area edits
 * it; a click in a hole with nothing there edits the outline the hole belongs to. A click inside several outlines (a block on a large
 * site) edits the smallest, so an outline inside another can still be picked. */
export function SitePicker({ scene, origin, sites, onPick, blocks = [], onPickBlock = () => {} }: SitePickerProps) {
  const clicked = useEffectEvent((x: number, y: number) => {
    const at = (site: Site) => {
      const local = scene.pointOnLevel(x, y, elevationRange(site.points)[0] - origin[2]);
      return local === null ? null : [local[0] + origin[0], local[1] + origin[1]] as const;
    };
    const outlines = [...sites.map((site, index) => ({ site, pick: () => onPick(index) })),
      ...blocks.map((site, index) => ({ site, pick: () => onPickBlock(index) }))];
    const smallestWhere = (inside: (site: Site, x: number, y: number) => boolean) => {
      const hits = outlines.filter(({ site }) => {
        const point = at(site);
        return point !== null && inside(site, point[0], point[1]);
      });
      return hits.reduce<(typeof hits)[number] | null>((best, hit) => (
        best === null || planArea(outlinePoints(hit.site.points)) < planArea(outlinePoints(best.site.points)) ? hit : best), null);
    };
    (smallestWhere(siteAreaContains) ?? smallestWhere((site, px, py) => containsPoint(site.points, px, py)))?.pick();
  });
  useEffect(() => scene.onViewClick(({ x, y }) => clicked(x, y)), [scene]);
  return null;
}
