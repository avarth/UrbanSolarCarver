// Picking test surfaces on the existing surroundings (design/test-surfaces-on-context.md, step 1): a scene tool, as the site editor
// is. A click on the surroundings picks the flat piece under the pointer (context_pieces.ts), drawn in the criterion's colour; a click
// on a picked piece drops it. The bar at the top of the view says what to do and holds the set the picks go to: a new set (its name,
// "Picked n" to start with) or a picked set to add them to; or, for Edit picks, the set being edited. Use sends each pick as the point
// clicked (in the input files' coordinates) and the direction of the click's ray: the service finds the same piece and turns it to
// face the side it was clicked from. Esc and Cancel send nothing.
import { useEffect, useEffectEvent, useId, useMemo, useState, type FormEvent } from "react";
import type * as THREE from "three";
import { messages } from "../messages";
import { faceAt, flatPieceFaces, trianglesOf } from "../viewer/context_pieces";
import type { ViewerScene } from "../viewer/scene";
import type { Point3 } from "../viewer/local_origin";
import "../sites/sites.css";

export interface SurfacePick {
  point: number[];
  ray: number[];
}

interface PickedPiece {
  pick: SurfacePick;
  faces: number[];
}

/** Where the picks go: a new set named *name*, or the picked set stored as *file*. */
export type PickTarget = { kind: "new"; name: string } | { kind: "add"; file: string };

interface ContextPickerProps {
  scene: ViewerScene;
  /** The local origin: added back to a local point to send it in the input files' coordinates. */
  origin: Point3;
  /** The surroundings as the view draws them, in local coordinates. */
  geometry: THREE.BufferGeometry;
  /** The colour picked pieces are drawn in (the criterion's or the study's). */
  colour: string;
  /** Edit picks: the set's picks to start from, and its name; absent for new picks. */
  editing?: { name: string; picks: SurfacePick[] };
  /** The picked sets the picks can be added to (file and name), for new picks. */
  pickedSets: { file: string; name: string }[];
  /** The name a new set starts with ("Picked 3"). */
  newSetName: string;
  busy: boolean;
  /** Why the last Use was refused; null for none. */
  problem: string | null;
  onUse: (picks: SurfacePick[], target: PickTarget) => void;
  onCancel: () => void;
}

const NEW_SET = "";

export function ContextPicker({ scene, origin, geometry, colour, editing, pickedSets, newSetName, busy, problem, onUse, onCancel }: ContextPickerProps) {
  const toFile = (point: Point3): number[] => [point[0] + origin[0], point[1] + origin[1], point[2] + origin[2]];
  const toLocal = (point: readonly number[]): Point3 => [point[0] - origin[0], point[1] - origin[1], point[2] - origin[2]];
  const [pieces, setPieces] = useState<PickedPiece[]>(() => (editing?.picks ?? []).flatMap((pick) => {
    const face = faceAt(geometry, toLocal(pick.point));
    return face === null ? [] : [{ pick, faces: flatPieceFaces(geometry, face) }];
  }));
  const [targetChoice, setTargetChoice] = useState(NEW_SET);
  const [name, setName] = useState(newSetName);
  const [cameraTick, setCameraTick] = useState(0);
  const nameId = useId();
  useEffect(() => scene.onCameraChange(() => setCameraTick((tick) => tick + 1)), [scene]);

  const clicked = useEffectEvent((intersection: THREE.Intersection) => {
    if (busy || intersection.faceIndex === undefined || intersection.faceIndex === null) return;
    const face = intersection.faceIndex;
    const holding = pieces.findIndex((piece) => piece.faces.includes(face));
    if (holding >= 0) {
      setPieces(pieces.filter((_, at) => at !== holding));
      return;
    }
    const point: Point3 = [intersection.point.x, intersection.point.y, intersection.point.z];
    const eye = scene.cameraPosition();
    const ray = [point[0] - eye[0], point[1] - eye[1], point[2] - eye[2]];
    const length = Math.hypot(ray[0], ray[1], ray[2]) || 1;
    setPieces([...pieces, { pick: { point: toFile(point), ray: ray.map((value) => value / length) }, faces: flatPieceFaces(geometry, face) }]);
  });
  useEffect(() => scene.onLayerClick("context", (intersection) => clicked(intersection)), [scene]);
  const escape = useEffectEvent((event: KeyboardEvent) => {
    if (event.key === "Escape" && !busy) onCancel();
  });
  useEffect(() => {
    const listener = (event: KeyboardEvent) => escape(event);
    window.addEventListener("keydown", listener);
    return () => window.removeEventListener("keydown", listener);
  }, []);

  const drawn = useMemo(() => {
    void cameraTick;      // drawn again as the camera moves
    return pieces.flatMap((piece) => trianglesOf(geometry, piece.faces)).map((triangle) => {
      const corners = triangle.map((point) => scene.toScreen(point));
      return corners.every((corner) => corner !== null) ? corners.map((corner) => corner!.join(",")).join(" ") : null;
    }).filter((points): points is string => points !== null);
  }, [pieces, geometry, scene, cameraTick]);

  const faceCount = pieces.length;
  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (faceCount === 0 || busy) return;
    const target: PickTarget = targetChoice === NEW_SET ? { kind: "new", name } : { kind: "add", file: targetChoice };
    onUse(pieces.map((piece) => piece.pick), target);
  };
  return (
    <div className="site-editor context-picker">
      <svg className="site-editor-drawing" aria-hidden="true">
        <g className="context-picker-pieces" style={{ fill: colour, stroke: colour }}>
          {drawn.map((points, index) => <polygon key={index} points={points} />)}
        </g>
      </svg>
      <form className="site-editor-bar context-picker-bar" role="toolbar" aria-label={messages.pickingSurfaces} onSubmit={submit}>
        <span className="site-editor-steps">{messages.pickingSteps}</span>
        {editing === undefined ? (
          <span className="context-picker-target">
            <select aria-label={messages.pickedSetTarget} value={targetChoice} disabled={busy} onChange={(event) => setTargetChoice(event.target.value)}>
              <option value={NEW_SET}>{messages.newSurfaceSet}</option>
              {pickedSets.map((set) => <option key={set.file} value={set.file}>{messages.addToSurfaceSet(set.name)}</option>)}
            </select>
            {targetChoice === NEW_SET && (
              <input id={nameId} type="text" aria-label={messages.surfaceSetName} value={name} maxLength={80} disabled={busy}
                     onChange={(event) => setName(event.target.value)} />
            )}
          </span>
        ) : <span className="context-picker-target">{messages.editingSurfaceSet(editing.name)}</span>}
        <span className="site-editor-buttons">
          <button type="button" className="secondary-button" disabled={busy} onClick={onCancel}>{messages.cancel}</button>
          <button type="submit" className="primary-button" disabled={busy || faceCount === 0 || (editing === undefined && targetChoice === NEW_SET && !name.trim())}>
            {editing === undefined ? messages.useFaces(faceCount) : messages.savePicks}
          </button>
        </span>
        {problem !== null && <span className="site-editor-problem" role="alert">{problem}</span>}
      </form>
    </div>
  );
}
