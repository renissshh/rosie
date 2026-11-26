import { BridgeClient, backoff, MAX_BACKOFF_MS, SocketLike } from "./bridge";
import { CoreEvent } from "./protocol";

class FakeSocket implements SocketLike {
  readyState = 0;
  sent: string[] = [];
  onopen: ((ev: unknown) => void) | null = null;
  onclose: ((ev: unknown) => void) | null = null;
  onmessage: ((ev: { data: unknown }) => void) | null = null;
  onerror: ((ev: unknown) => void) | null = null;
  send(data: string) {
    this.sent.push(data);
  }
  close() {
    this.readyState = 3;
    this.onclose?.({});
  }
  open() {
    this.readyState = 1;
    this.onopen?.({});
  }
  receive(data: unknown) {
    this.onmessage?.({ data });
  }
}

function setup() {
  const sockets: FakeSocket[] = [];
  const timers: { fn: () => void; ms: number }[] = [];
  const client = new BridgeClient({
    makeSocket: () => {
      const socket = new FakeSocket();
      sockets.push(socket);
      return socket;
    },
    setTimer: (fn, ms) => timers.push({ fn, ms }),
    clearTimer: () => timers.splice(0),
  });
  return { client, sockets, timers };
}

test("backoff doubles up to ten seconds", () => {
  expect([0, 1, 2, 3, 4, 10].map(backoff)).toEqual([1000, 2000, 4000, 8000, MAX_BACKOFF_MS, MAX_BACKOFF_MS]);
});

test("connects, reports status and delivers parsed events", () => {
  const { client, sockets } = setup();
  const statuses: string[] = [];
  const events: CoreEvent[] = [];
  client.onStatus((s) => statuses.push(s));
  client.onEvent((e) => events.push(e));
  client.start();
  sockets[0].open();
  sockets[0].receive(JSON.stringify({ type: "state", state: "thinking" }));
  expect(statuses).toEqual(["connecting", "open"]);
  expect(events).toEqual([{ type: "state", state: "thinking" }]);
});

test("ignores malformed messages", () => {
  const { client, sockets } = setup();
  const events: CoreEvent[] = [];
  client.onEvent((e) => events.push(e));
  client.start();
  sockets[0].open();
  ["not json", "[1]", JSON.stringify({ text: "no type" }), 42].forEach((d) => sockets[0].receive(d));
  expect(events).toEqual([]);
});

test("send works only while open", () => {
  const { client, sockets } = setup();
  client.start();
  expect(client.send({ type: "ping" })).toBe(false);
  sockets[0].open();
  expect(client.send({ type: "ask", text: "hi" })).toBe(true);
  expect(JSON.parse(sockets[0].sent[0])).toEqual({ type: "ask", text: "hi" });
});

test("reconnects with growing delays, and resets after a good connection", () => {
  const { client, sockets, timers } = setup();
  client.start();
  sockets[0].close(); // core not up yet
  expect(timers.map((t) => t.ms)).toEqual([1000]);
  timers.shift()!.fn();
  sockets[1].close();
  expect(timers.map((t) => t.ms)).toEqual([2000]);
  timers.shift()!.fn();
  sockets[2].open();
  sockets[2].close(); // core restarted
  expect(timers.map((t) => t.ms)).toEqual([1000]);
});

test("stop closes the socket and stops reconnecting", () => {
  const { client, sockets, timers } = setup();
  client.start();
  sockets[0].open();
  client.stop();
  expect(client.status).toBe("closed");
  expect(timers).toEqual([]);
});
