// The threshold setting (UX 5.5, 7). In time-based mode it is Shadow tolerated, a cutoff in m²·h; in the weighted modes it is
// the Carving rule: Manual, a carve amount (the engine's default, so unset), or Automatic; a cutoff the config holds shows as Manual.
import { messages } from "../../messages";
import { NumberInput, type ControlProps } from "./NumberInput";

/** The engine's ThresholdSpec as the config stores it. */
export interface ThresholdSpec {
  method: "carve_fraction" | "headtail" | "cutoff";
  value?: number | null;
}

const CARVING_RULES = ["carve_fraction", "headtail"] as const;

interface ThresholdRuleProps extends ControlProps {
  value: ThresholdSpec | null;
  /** Time-based: the threshold is the shading a voxel may cause, so only the cutoff value is asked for. */
  isShadowTolerated: boolean;
  unit: string;
  onThreshold: (value: ThresholdSpec | null) => void;
}

export function ThresholdRule({ value, isShadowTolerated, unit, onThreshold, inputId, invalid, describedBy, disabled, onRefusedInput }: ThresholdRuleProps) {
  const cutoffValue = value?.method === "cutoff" ? (value.value ?? null) : null;
  if (isShadowTolerated) {
    // Unset, the engine applies a cutoff of 0 to time-based scores.
    return (
      <div className="setting-control">
        <NumberInput id={inputId} value={cutoffValue ?? 0} mayBeEmpty minimum={0} invalid={invalid} describedBy={describedBy} disabled={disabled}
                     onValue={(cutoff) => onThreshold(cutoff === null ? null : { method: "cutoff", value: cutoff })} onRefused={onRefusedInput} />
        <span className="setting-unit">{unit}</span>
      </div>
    );
  }
  const chosenRule = value?.method === "headtail" ? "headtail" : "carve_fraction";
  const chooseRule = (rule: (typeof CARVING_RULES)[number]) => onThreshold(rule === "headtail" ? { method: "headtail" } : null);   // unset: the carve amount
  return (
    <div className="setting-control setting-threshold-rule">
      <select id={inputId} className="setting-select" value={chosenRule} aria-invalid={invalid} aria-describedby={describedBy} disabled={disabled}
              onChange={(event) => chooseRule(event.target.value as (typeof CARVING_RULES)[number])}>
        {CARVING_RULES.map((rule) => <option key={rule} value={rule}>{messages.carvingRuleChoices[rule]}</option>)}
      </select>
    </div>
  );
}
