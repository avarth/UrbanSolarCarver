// The threshold setting (UX 5.5, 7). In time-based mode it is Shadow tolerated, a cutoff in m²·h; in the weighted modes it is
// the Carving rule: carve amount (the engine's default, so unset), automatic split, or a cutoff on the raw score with its value.
import { messages } from "../../messages";
import { NumberInput, type ControlProps } from "./NumberInput";

/** The engine's ThresholdSpec as the config stores it. */
export interface ThresholdSpec {
  method: "carve_fraction" | "headtail" | "cutoff";
  value?: number | null;
}

const CARVING_RULES = ["carve_fraction", "headtail", "cutoff"] as const;

interface ThresholdRuleProps extends ControlProps {
  value: ThresholdSpec | null;
  /** Time-based: the threshold is the shading a voxel may cause, so only the cutoff value is asked for. */
  isShadowTolerated: boolean;
  unit: string;
  onThreshold: (value: ThresholdSpec | null) => void;
}

export function ThresholdRule({ value, isShadowTolerated, unit, onThreshold, inputId, invalid, describedBy, disabled }: ThresholdRuleProps) {
  const cutoffValue = value?.method === "cutoff" ? (value.value ?? null) : null;
  if (isShadowTolerated) {
    // Unset, the engine applies a cutoff of 0 to time-based scores.
    return (
      <div className="setting-control">
        <NumberInput id={inputId} value={cutoffValue ?? 0} mayBeEmpty minimum={0} invalid={invalid} describedBy={describedBy} disabled={disabled}
                     onValue={(cutoff) => onThreshold(cutoff === null ? null : { method: "cutoff", value: cutoff })} />
        <span className="setting-unit">{unit}</span>
      </div>
    );
  }
  const chosenRule = value?.method ?? "carve_fraction";
  const chooseRule = (rule: ThresholdSpec["method"]) => {
    if (rule === "carve_fraction") onThreshold(null);     // the carve amount, as the engine does when unset
    else if (rule === "headtail") onThreshold({ method: "headtail" });
    else onThreshold({ method: "cutoff", value: cutoffValue ?? 0 });
  };
  return (
    <div className="setting-control setting-threshold-rule">
      <select id={inputId} className="setting-select" value={chosenRule} aria-invalid={invalid} aria-describedby={describedBy} disabled={disabled}
              onChange={(event) => chooseRule(event.target.value as ThresholdSpec["method"])}>
        {CARVING_RULES.map((rule) => <option key={rule} value={rule}>{messages.carvingRuleChoices[rule]}</option>)}
      </select>
      {chosenRule === "cutoff" && (
        <NumberInput ariaLabel={messages.scoreCutoffValue} value={cutoffValue} mayBeEmpty={false} minimum={0} invalid={invalid}
                     describedBy={describedBy} disabled={disabled} onValue={(cutoff) => onThreshold({ method: "cutoff", value: cutoff })} />
      )}
    </div>
  );
}
