// What Simulate puts over the 3D view. For now a note; the studies panel and their results replace it.
import { messages } from "../messages";
import "./simulate.css";

export function SimulateView() {
  return (
    <div className="simulate-view">
      <p>{messages.simulatePlaceholder}</p>
    </div>
  );
}
