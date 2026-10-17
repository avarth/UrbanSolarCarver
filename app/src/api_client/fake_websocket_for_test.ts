// A stand-in for the browser's WebSocket in tests (vi.stubGlobal("WebSocket", FakeWebSocket)): it records each socket the page
// opens, and a test sends the run's events through it as the service would.
import { act } from "react";

export class FakeWebSocket {
  /** The sockets opened since the test reset this list, in order. */
  static opened: FakeWebSocket[] = [];
  onmessage: ((message: { data: string }) => void) | null = null;
  onclose: ((event: { code: number; reason: string }) => void) | null = null;

  constructor(readonly address: string) {
    FakeWebSocket.opened.push(this);
  }

  close() {}

  /** Delivers one event of the run, as JSON, the way the service sends it. */
  send(event: object) {
    act(() => this.onmessage?.({ data: JSON.stringify(event) }));
  }
}
