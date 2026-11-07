// What a new project's Criteria step shows until a mode is chosen: the mode tiles under their title.
import { messages } from "../messages";
import { ModeStep } from "./ModeStep";

interface FirstModeProps {
  onChoose: (mode: string) => void;
  /** Why the mode cannot be chosen now (a run is in progress); null when it can. */
  disabledReason: string | null;
}

export function FirstMode({ onChoose, disabledReason }: FirstModeProps) {
  return (
    <section className="first-mode" aria-labelledby="first-mode-title">
      <h3 id="first-mode-title" className="first-mode-title">{messages.firstModeTitle}</h3>
      <ModeStep mode={null} onChoose={onChoose} disabledReason={disabledReason} />
    </section>
  );
}
