// The Envelope and massing step (UX 5.6): the envelope and building massing settings, then the results of the last build:
// Gross floor area, Storeys and Envelope volume as tiles in one row, the floor area per storey as a table (storeys numbered
// from 1, a swatch of each storey's colour in the 3D view, a bold total), and the link that opens the run report. Results of a
// carving that changed since are greyed and say so. Build envelope and massing is the step's button, pinned under the steps.
import type { RunSummary } from "../api_client/client";
import { messages } from "../messages";
import type { FormState } from "../settings_form/form_state";
import { settingsForStep } from "../settings_form/presentation";
import { SettingGroup } from "../settings_form/SettingGroup";
import { storeyColour } from "../viewer/colour_scales";
import { NumberTile } from "./CarvingStep";
import { formatNumber } from "./format_numbers";
import "./steps.css";

type MassingSummary = NonNullable<RunSummary["massing"]>;

/** The building massing's plates.json, as much of it as the step reads (heights in model coordinates, metres). */
export interface PlatesFile {
  plates: { floor: number; z_bottom: number; z_top: number; area_m2: number }[];
  floor_area_m2_per_floor: number[];
  total_floor_area_m2: number;
}

export interface StoreyRow {
  /** 0 for the ground storey, as the engine counts floors and names the parts of plates.obj. */
  floorIndex: number;
  bottom: number;
  top: number;
  area: number;
}

/** One row per storey that has plates, from the ground up. */
export function storeyRows(platesFile: PlatesFile): StoreyRow[] {
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

interface EnvelopeAndMassingStepProps {
  form: FormState;
  onChange: (values: Record<string, unknown>) => void;
  /** Why the settings cannot be changed now (a run of the project); null when they can. */
  disabledReason: string | null;
  massing: MassingSummary | null;
  platesFile: PlatesFile | null;
  /** The envelope or the massing was built from an earlier carving or other settings. */
  outOfDate: boolean;
  /** The run report exists. */
  hasRunReport: boolean;
  onOpenRunReport: () => void;
}

export function EnvelopeAndMassingStep({ form, onChange, disabledReason, massing, platesFile, outOfDate, hasRunReport, onOpenRunReport }: EnvelopeAndMassingStepProps) {
  return (
    <div className="envelope-step">
      {disabledReason !== null && <p className="step-reason">{disabledReason}</p>}
      {settingsForStep("envelope_and_massing", form.mode).map((group) => (
        <SettingGroup key={group.title} group={group} form={form} onChange={onChange} disabled={disabledReason !== null} />
      ))}
      {massing !== null && (
        <section className={outOfDate ? "envelope-results envelope-results-out-of-date" : "envelope-results"}>
          {outOfDate && <p className="out-of-date-label">{messages.outOfDateForCarving}</p>}
          <div className="number-tiles number-tiles-three">
            <NumberTile label={messages.grossFloorArea} value={formatNumber(massing.total_floor_area_m2)} unit="m²" />
            <NumberTile label={messages.storeys} value={formatNumber(massing.storeys_built)} />
            <NumberTile label={messages.envelopeVolume} value={formatNumber(massing.envelope_volume_m3)} unit="m³" />
          </div>
          {platesFile !== null && platesFile.plates.length > 0 && <StoreyTable platesFile={platesFile} />}
        </section>
      )}
      {hasRunReport && <button type="button" className="link-button" onClick={onOpenRunReport}>{messages.openRunReport}</button>}
    </div>
  );
}
