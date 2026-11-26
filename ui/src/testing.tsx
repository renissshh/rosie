/** Test helpers: a fake socket and a client wired to it. Not part of the app bundle. */
import { act } from "@testing-library/react";
import { BridgeClient, SocketLike } from "./bridge";

export class FakeSocket implements SocketLike {
  readyState = 0;
  sent: unknown[] = [];
  onopen: ((ev: unknown) => void) | null = null;
  onclose: ((ev: unknown) => void) | null = null;
  onmessage: ((ev: { data: unknown }) => void) | null = null;
  onerror: ((ev: unknown) => void) | null = null;
  send(data: string) {
    this.sent.push(JSON.parse(data));
  }
  close() {
    this.readyState = 3;
  }
}

export function fakeCore() {
  const socket = new FakeSocket();
  const makeClient = () => new BridgeClient({ makeSocket: () => socket, setTimer: () => 0, clearTimer: () => {} });
  return {
    socket,
    makeClient,
    open: () =>
      act(() => {
        socket.readyState = 1;
        socket.onopen?.({});
      }),
    say: (event: object) => act(() => socket.onmessage?.({ data: JSON.stringify(event) })),
  };
}
