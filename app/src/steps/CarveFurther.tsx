// Carve further (in the Export step): the built envelope becomes the project's maximum volume, so another criterion can carve it
// again (chained carving keeps what every criterion keeps). The service keeps the replaced maximum volume and records the chain;
// the settings return to a new project's. Because the settings are reset, the button asks once before it acts.
import { useId, useState } from "react";
import { messages } from "../messages";
import { WarningIcon } from "../settings_form/SettingField";
import { plainModeName } from "./step_summaries";
import "./steps.css";

/** "Carved by Daylight, then Solar time-based. ..." for a project that carved further; null for one that did not. */
export function carvedByNote(chain: readonly { mode: string }[]): string | null {
  return chain.length === 0 ? null : messages.carvedBy(chain.map((step) => plainModeName(step.mode)).join(", then "));
}

interface CarveFurtherSectionProps {
  /** Why the envelope cannot be carved further now (no current envelope, a run); null when it can. */
  disabledReason: string | null;
  /** Asks the service to carve further; resolves with the reason it refused, or null once the project is reopened. */
  onCarveFurther: () => Promise<string | null>;
}

export function CarveFurtherSection({ disabledReason, onCarveFurther }: CarveFurtherSectionProps) {
  const [asking, setAsking] = useState(false);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const reasonId = useId();
  const confirm = async () => {
    setBusy(true);
    setProblem(null);
    try {
      setProblem(await onCarveFurther());
    } finally {
      setBusy(false);
      setAsking(false);
    }
  };
  return (
    <section className="carve-further">
      <h3 className="carve-further-title">{messages.carveFurtherTitle}</h3>
      <p className="input-box-hint">{messages.carveFurtherNote}</p>
      {!asking && (
        <button type="button" disabled={disabledReason !== null || busy} aria-describedby={disabledReason !== null ? reasonId : undefined}
                onClick={() => setAsking(true)}>{messages.carveFurtherButton}</button>
      )}
      {asking && (
        <div className="carve-further-question" role="group" aria-label={messages.carveFurtherTitle}>
          <p>{messages.carveFurtherQuestion}</p>
          <button type="button" disabled={busy} onClick={() => void confirm()}>{messages.carveFurtherConfirm}</button>
          <button type="button" className="link-button" disabled={busy} onClick={() => setAsking(false)}>{messages.cancel}</button>
        </div>
      )}
      {disabledReason !== null && <p id={reasonId} className="step-reason">{disabledReason}</p>}
      {problem !== null && <p className="setting-error"><WarningIcon /><span>{problem}</span></p>}
    </section>
  );
}
