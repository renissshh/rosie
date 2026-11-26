import { fireEvent, render, screen } from "@testing-library/react";
import App from "./App";
import { fakeCore } from "./testing";

function mount(openDeck = () => {}) {
  const core = fakeCore();
  render(<App makeClient={core.makeClient} openDeck={openDeck} />);
  return { socket: core.socket, core };
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

test("right-click on the orb opens the Command Deck", () => {
  const opened: string[] = [];
  const { core } = mount(() => opened.push("deck"));
  core.open();
  fireEvent.contextMenu(screen.getByRole("button"));
  expect(opened).toEqual(["deck"]);
});

test("without voice, a click opens the deck so you can type", () => {
  const opened: string[] = [];
  const { core } = mount(() => opened.push("deck"));
  core.open();
  fireEvent.click(screen.getByRole("button"));
  core.say({ type: "error", text: "voice is off: start the core with `rosie serve --voice`" });
  expect(opened).toEqual(["deck"]);
});
