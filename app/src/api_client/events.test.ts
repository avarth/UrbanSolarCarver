import { afterEach, expect, test, vi } from "vitest";
import { subscribeToRunEvents, type RunEvent } from "./events";

class FakeWebSocket {
  static opened: FakeWebSocket[] = [];
  onmessage: ((message: { data: string }) => void) | null = null;
  onclose: ((event: { code: number; reason: string }) => void) | null = null;
  closed = false;
  constructor(readonly address: string) {
    FakeWebSocket.opened.push(this);
  }
  close() {
    this.closed = true;
  }
}

function subscribe() {
  FakeWebSocket.opened = [];
  vi.stubGlobal("WebSocket", FakeWebSocket);
  const received: RunEvent[] = [];
  const unsubscribe = subscribeToRunEvents("run 1", "secret", (event) => received.push(event));
  return { received, unsubscribe, socket: FakeWebSocket.opened[0] };
}

afterEach(() => vi.unstubAllGlobals());

test("the socket address carries the run and the token", () => {
  const { socket } = subscribe();
  expect(socket.address).toBe(`ws://${window.location.host}/api/runs/run%201/events?token=secret`);
});

test("events reach the listener as they arrive", () => {
  const { received, socket } = subscribe();
  socket.onmessage?.({ data: JSON.stringify({ type: "stage_progress", stage: "preprocessing", done: 1, total: 4 }) });
  socket.onmessage?.({ data: JSON.stringify({ type: "run_finished", stages: ["preprocessing"], files: [] }) });
  socket.onclose?.({ code: 1000, reason: "" });
  expect(received.map((event) => event.type)).toEqual(["stage_progress", "run_finished"]);
});

test.each([[4401], [4403], [4404], [1006]])("a close with code %i before the last event is reported as a lost connection", (code) => {
  const { received, socket } = subscribe();
  socket.onclose?.({ code, reason: "refused" });
  expect(received).toEqual([{ type: "connection_lost", code, reason: "refused" }]);
});

test("unsubscribing closes the socket and silences it", () => {
  const { received, unsubscribe, socket } = subscribe();
  unsubscribe();
  socket.onclose?.({ code: 1005, reason: "" });
  expect(socket.closed).toBe(true);
  expect(received).toEqual([]);
});
