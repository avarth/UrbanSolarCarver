// The Envelope and massing step (UX 5.6, R2 5): two parts, each built on its own, since the massing reads the carving and not
// the envelope. Envelope: its settings, Build envelope and the volume of the last envelope. Building massing: its settings, Build
// massing, Gross floor area and Storeys as tiles and the floor area per storey as a table (storeys numbered from 1, a swatch of
// each storey's colour in the 3D view, a bold total). A part's results built from settings or a carving that changed since are
// greyed and say so. The link that opens the run report ends the step.
import type { ReactNode } from "react";
import type { RunSummary } from "../api_client/client";
import { messages } from "../messages";
import type { FormState } from "../settings_form/form_state";
import { settingsForStep } from "../settings_form/presentation";
import { SettingGroup } from "../settings_form/SettingGroup";
import { storeyColour } from "../viewer/colour_scales";
import { NumberTile } from "./CarvingStep";
import { formatNumber } from "./format_numbers";
import "./steps.css";

type EnvelopeSummary = NonNullable<RunSummary["envelope"]>;
type MassingSummary = NonNullable<RunSummary["massing"]>;

/** The setting group each part holds (setting_presentation.json). */
const ENVELOPE_GROUP = "Envelope";
const MASSING_GROUP = "Building massing";

/** The building massing's plates.json, as much of it as the step reads (heights in model coordinates, metres). */
export interface PlatesFile {
  plates: { floor: number; z_bottom: number; z_top: number; area_m2: number }[];
  floor_area_m2_per_floor: number[];
  total_floor_area_m2: number;
}

export interface StoreyRow {
  /** 0 for the ground storey, as the engine counts floors and names the parts of plates.obj. */
  floorIndex: number;
  /** Heights in metres above the bottom of the lowest storey (storey 1, the ground storey, when it has plates). */
  bottom: number;
  top: number;
  area: number;
}

/** One row per storey that has plates, from the ground up, its heights measured from the bottom of the lowest storey. */
export function storeyRows(platesFile: PlatesFile): StoreyRow[] {
  const rows = storeyRowsInModelHeights(platesFile);
  const ground = rows.length > 0 ? rows[0].bottom : 0;
  return rows.map((row) => ({ ...row, bottom: row.bottom - ground, top: row.top - ground }));
}

/** The storeys with the heights plates.json gives, in model coordinates. */
function storeyRowsInModelHeights(platesFile: PlatesFile): StoreyRow[] {
  const rows = new Map<number, StoreyRow>();
  for (const plate of platesFile.plates) {
    const row = rows.get(plate.floor);
    if (row === undefined) {
      rows.set(plate.floor, { floorIndex: plate.floor, bottom: plate.z_bottom, top: plate.z_top,
                              area: platesFile.floor_area_m2_per_floor[plate.floor] ?? plate.area_m2 });
    } else {
      row.bottom = Math.min(row.bottom, plate.z_bottom);
      row.top = Math.max(row.top, plate.z_top);
    }
  }
  return [...rows.values()].sort((first, second) => first.floorIndex - second.floorIndex);
}

/** The number of storeys the 3D view colours (the highest floor with a plate, plus one), so the swatches match its colours. */
export function colouredStoreyCount(platesFile: PlatesFile): number {
  return platesFile.plates.reduce((count, plate) => Math.max(count, plate.floor + 1), 0);
}

const heightText = (metres: number) => formatNumber(metres, undefined, 1);

export function StoreyTable({ platesFile }: { platesFile: PlatesFile }) {
  const storeyCount = colouredStoreyCount(platesFile);
  return (
    <table className="storey-table">
      <caption>{messages.floorAreaPerStorey}</caption>
      <thead>
        <tr>
          <th scope="col">{messages.storeyColumns.storey}</th>
          <th scope="col">{messages.storeyColumns.bottom}</th>
          <th scope="col">{messages.storeyColumns.top}</th>
          <th scope="col">{messages.storeyColumns.area}</th>
        </tr>
      </thead>
      <tbody>
        {storeyRows(platesFile).map((row) => (
          <tr key={row.floorIndex}>
            <th scope="row">
              <span className="storey-swatch" style={{ background: storeyColour(row.floorIndex, storeyCount) }} aria-hidden="true" />
              {messages.storeyRowLabel(row.floorIndex + 1)}
            </th>
            <td>{heightText(row.bottom)}</td>
            <td>{heightText(row.top)}</td>
            <td>{formatNumber(row.area)}</td>
          </tr>
        ))}
      </tbody>
      <tfoot>
        <tr>
          <th scope="row">{messages.totalRow}</th>
          <td />
          <td />
          <td>{formatNumber(platesFile.total_floor_area_m2)}</td>
        </tr>
      </tfoot>
    </table>
  );
}

export interface EnvelopeAndMassingStepProps {
  form: FormState;
  onChange: (values: Record<string, unknown>) => void;
  /** Why the settings cannot be changed now (a run of the project); null when they can. */
  disabledReason: string | null;
  envelope: EnvelopeSummary | null;
  /** The envelope was built from settings or a carving that changed since. */
  envelopeOutOfDate: boolean;
  /** Build envelope, with the reason it waits and the progress of its run. */
  envelopeButton: ReactNode;
  massing: MassingSummary | null;
  platesFile: PlatesFile | null;
  /** The massing was built from settings or a carving that changed since. */
  massingOutOfDate: boolean;
  /** Build massing, with the reason it waits and the progress of its run. */
  massingButton: ReactNode;
  /** The progress of a build of both parts started from Carving, which opened this step. */
  buildFeedback: ReactNode;
  /** The run report exists. */
  hasRunReport: boolean;
  onOpenRunReport: () => void;
}

/** A part's results, greyed with the out-of-date label when it was built from what changed since. */
function PartResults({ outOfDate, children }: { outOfDate: boolean; children: ReactNode }) {
  return (
    <section className={outOfDate ? "envelope-results envelope-results-out-of-date" : "envelope-results"}>
      {outOfDate && <p className="out-of-date-label">{messages.outOfDateForCarving}</p>}
      {children}
    </section>
  );
}

export function EnvelopeAndMassingStep(props: EnvelopeAndMassingStepProps) {
  const { form, onChange, disabledReason, envelope, massing, platesFile } = props;
  const groups = settingsForStep("envelope_and_massing", form.mode);
  const part = (groupTitle: string, button: ReactNode, results: ReactNode) => (
    <div className="build-part">
      {groups.filter((group) => group.title === groupTitle).map((group) => (
        <SettingGroup key={group.title} group={group} form={form} onChange={onChange} disabled={disabledReason !== null} />
      ))}
      {button}
      {results}
    </div>
  );
  return (
    <div className="envelope-step">
      {disabledReason !== null && <p className="step-reason">{disabledReason}</p>}
      {props.buildFeedback}
      {part(ENVELOPE_GROUP, props.envelopeButton, envelope !== null && (
        <PartResults outOfDate={props.envelopeOutOfDate}>
          <div className="number-tiles number-tiles-two">
            <NumberTile label={messages.envelopeVolume} value={formatNumber(envelope.envelope_volume_m3)} unit={messages.units.cubicMetres} />
          </div>
        </PartResults>
      ))}
      {part(MASSING_GROUP, props.massingButton, massing !== null && (
        <PartResults outOfDate={props.massingOutOfDate}>
          <div className="number-tiles number-tiles-two">
            <NumberTile label={messages.grossFloorArea} value={formatNumber(massing.total_floor_area_m2)} unit={messages.units.squareMetres} />
            <NumberTile label={messages.storeys} value={formatNumber(massing.storeys_built)} />
          </div>
          {platesFile !== null && platesFile.plates.length > 0 && <StoreyTable platesFile={platesFile} />}
        </PartResults>
      ))}
      {props.hasRunReport && <button type="button" className="link-button" onClick={props.onOpenRunReport}>{messages.openRunReport}</button>}
    </div>
  );
}
