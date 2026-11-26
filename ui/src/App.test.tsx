import { act, fireEvent, render, screen } from "@testing-library/react";
import App from "./App";
import { BridgeClient, SocketLike } from "./bridge";

class FakeSocket implements SocketLike {
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

function mount() {
  const socket = new FakeSocket();
  const client = () => new BridgeClient({ makeSocket: () => socket, setTimer: () => 0, clearTimer: () => {} });
  render(<App makeClient={client} />);
  const core = {
    open: () => act(() => {
      socket.readyState = 1;
      socket.onopen?.({});
    }),
    say: (event: object) => act(() => socket.onmessage?.({ data: JSON.stringify(event) })),
  };
  return { socket, core };
}

test("the stage can be dragged", () => {
  mount();
  expect(screen.getByRole("main").hasAttribute("data-tauri-drag-region")).toBe(true);
});

test("the orb shows offline until the core connects, then follows its state", () => {
  const { core } = mount();
  expect(screen.getByRole("button").dataset.look).toBe("offline");
  core.open();
  expect(screen.getByRole("button", { name: "Rosie is here" })).toBeTruthy();
  core.say({ type: "state", state: "thinking" });
  expect(screen.getByRole("button").dataset.look).toBe("thinking");
});

test("clicking the orb asks the core to listen", () => {
  const { socket, core } = mount();
  core.open();
  fireEvent.click(screen.getByRole("button"));
  expect(socket.sent).toEqual([{ type: "listen" }]);
});

test("clicking a pulsing nudge dismisses it instead", () => {
  const { socket, core } = mount();
  core.open();
  core.say({ type: "nudge", title: "Reminder", text: "gym" });
  expect(screen.getByRole("button").dataset.look).toBe("nudge");
  fireEvent.click(screen.getByRole("button"));
  expect(screen.getByRole("button").dataset.look).toBe("idle");
  expect(socket.sent).toEqual([]);
});

test("the Day Ring draws what the core sends", () => {
  const { core } = mount();
  core.open();
  core.say({ type: "day", date: "2026-11-26", blocks: [{ start: "19:00", end: "21:00", kind: "study", label: "DBMS" }], marks: [] });
  expect(screen.getByRole("img", { name: "Today's plan" }).querySelectorAll("path.block")).toHaveLength(1);
});
