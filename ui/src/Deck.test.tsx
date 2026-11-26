import { fireEvent, render, screen } from "@testing-library/react";
import Deck from "./Deck";
import { addLine, daysLeft, MAX_LINES, nowNext } from "./deck";
import { DayData } from "./protocol";
import { fakeCore } from "./testing";
import { windowKind } from "./windows";

const DAY: DayData = {
  type: "day",
  date: "2026-11-26",
  blocks: [
    { start: "19:00", end: "21:00", kind: "study", label: "DBMS" },
    { start: "22:00", end: "22:15", kind: "review", label: "Review" },
  ],
  marks: [{ at: "21:30", kind: "reminder", text: "call mom" }],
};

const BRIEF = {
  type: "brief",
  top3: [
    { id: "a1", title: "Submit assignment", due: "2026-11-25", priority: "high", overdue: true },
    { id: "b2", title: "Revise DBMS", due: null, priority: null, overdue: false },
  ],
  overdue: 1,
  streak: 4,
  countdown: { label: "Exams", date: "2026-12-07", days: 11 },
};

function mount() {
  const core = fakeCore();
  render(<Deck makeClient={core.makeClient} clock={() => new Date("2026-11-26T20:00:00")} />);
  core.open();
  return core;
}

test("the page picks its window from the hash", () => {
  expect(windowKind("#deck")).toBe("deck");
  expect(windowKind("")).toBe("orb");
});

test("now / next mixes blocks and timed events", () => {
  expect(nowNext(DAY, 20 * 60)).toEqual({ now: "DBMS until 21:00", next: "21:30 call mom" });
  expect(nowNext(DAY, 21 * 60 + 45)).toEqual({ now: null, next: "22:00 Review" });
  expect(nowNext(null, 0)).toEqual({ now: null, next: null });
});

test("countdown wording", () => {
  expect([0, 1, 11].map(daysLeft)).toEqual(["today", "tomorrow", "in 11 days"]);
});

test("the transcript keeps the last 50 lines", () => {
  let lines = [] as { role: "you" | "rosie"; text: string }[];
  for (let i = 0; i < 60; i++) lines = addLine(lines, { role: "you", text: String(i) });
  expect(lines).toHaveLength(MAX_LINES);
  expect(lines[0].text).toBe("10");
});

test("brief cards show top 3, streak, countdown and now/next", () => {
  const core = mount();
  core.say(BRIEF);
  core.say(DAY);
  expect(screen.getByText("Submit assignment")).toBeTruthy();
  expect(screen.getByText("4 days")).toBeTruthy();
  expect(screen.getByText("in 11 days")).toBeTruthy();
  expect(screen.getByText("1 overdue")).toBeTruthy();
  expect(screen.getByText("DBMS until 21:00")).toBeTruthy();
  expect(screen.getByText("21:30 call mom")).toBeTruthy();
});

test("ticking a task marks it done in the core", () => {
  const core = mount();
  core.say(BRIEF);
  fireEvent.click(screen.getByLabelText("Done: Revise DBMS"));
  expect(core.socket.sent).toEqual([{ type: "done", id: "b2" }]);
});

test("typing and sending asks Rosie, and the transcript shows both sides", () => {
  const core = mount();
  fireEvent.change(screen.getByLabelText("Message Rosie"), { target: { value: "what's next?" } });
  fireEvent.click(screen.getByText("Send"));
  expect(core.socket.sent).toEqual([{ type: "ask", text: "what's next?" }]);
  core.say({ type: "transcript", role: "you", text: "what's next?" });
  core.say({ type: "transcript", role: "rosie", text: "Call mom at 21:30." });
  expect(screen.getByText("Call mom at 21:30.").className).toBe("rosie");
  expect((screen.getByLabelText("Message Rosie") as HTMLInputElement).value).toBe("");
});

test("quick log sends the typed text with its kind", () => {
  const core = mount();
  fireEvent.change(screen.getByLabelText("Message Rosie"), { target: { value: "DBMS 45m" } });
  fireEvent.click(screen.getByText("+ Study"));
  expect(core.socket.sent).toEqual([{ type: "log", what: "study", text: "DBMS 45m" }]);
  core.say({ type: "logged", text: "Logged study: DBMS, 45 min" });
  expect(screen.getByRole("status").textContent).toBe("Logged study: DBMS, 45 min");
});

test("quick log with an empty box explains instead of sending", () => {
  const core = mount();
  fireEvent.click(screen.getByText("+ Gym"));
  expect(core.socket.sent).toEqual([]);
  expect(screen.getByRole("status").textContent).toContain("Type what to log first");
});

test("the safety gate's question can be answered in the deck", () => {
  const core = mount();
  core.say({ type: "confirm", id: "q1", question: "Delete note daily/2026-11-20.md?" });
  fireEvent.click(screen.getByText("Deny"));
  expect(core.socket.sent).toEqual([{ type: "confirm_reply", id: "q1", allow: false }]);
  expect(screen.queryByText("Delete note daily/2026-11-20.md?")).toBeNull();
});

test("offline core disables the box", () => {
  const core = fakeCore();
  render(<Deck makeClient={core.makeClient} />);
  expect((screen.getByLabelText("Message Rosie") as HTMLInputElement).disabled).toBe(true);
  expect(screen.getByText("core offline")).toBeTruthy();
});
