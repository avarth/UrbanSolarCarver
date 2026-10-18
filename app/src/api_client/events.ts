// The events of a run, over the service's WebSocket.

export type RunEvent =
  | { type: "stage_progress"; stage: string | null; done: number; total: number }
  | { type: "issue"; stage: string | null; code: string; message: string }     // null: raised before any stage began (the config loading)
  | { type: "run_finished"; stages: string[]; files: string[] }
  | { type: "run_cancelled" }
  | { type: "run_failed"; error_type: string; message: string; field_errors: { field: string | null; message: string }[] }
  // Made here, not sent by the service: the socket closed before the run's last event. The service refuses with
  // 4401 (token), 4403 (Host) or 4404 (unknown run) after accepting the connection; 1006 is a connection that dropped.
  | { type: "connection_lost"; code: number; reason: string };

const LAST_EVENT_TYPES = ["run_finished", "run_cancelled", "run_failed"];

/** Calls *onEvent* with every event of the run, from the first. The returned function stops the subscription. */
export function subscribeToRunEvents(runId: string, token: string, onEvent: (event: RunEvent) => void): () => void {
  const scheme = window.location.protocol === "https:" ? "wss" : "ws";
  const socket = new WebSocket(`${scheme}://${window.location.host}/api/runs/${encodeURIComponent(runId)}/events?token=${encodeURIComponent(token)}`);
  let stopped = false;
  let lastEventSeen = false;

  socket.onmessage = (message) => {
    if (stopped) return;
    const event = JSON.parse(message.data) as RunEvent;
    lastEventSeen = LAST_EVENT_TYPES.includes(event.type);
    onEvent(event);
  };
  socket.onclose = (closeEvent) => {
    if (stopped || lastEventSeen) return;
    onEvent({ type: "connection_lost", code: closeEvent.code, reason: closeEvent.reason });
  };

  return () => {
    stopped = true;
    socket.close();
  };
}
