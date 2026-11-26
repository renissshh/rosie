import { render } from "@testing-library/react";
import { DayRing } from "./DayRing";
import { DayData } from "./protocol";

const day: DayData = {
  type: "day",
  date: "2026-11-26",
  blocks: [
    { start: "09:00", end: "15:30", kind: "college", label: "College" },
    { start: "19:00", end: "21:00", kind: "study", label: "DBMS" },
  ],
  marks: [
    { at: "18:00", kind: "reminder", text: "gym" },
    { at: "22:00", kind: "review", text: "Nightly review" },
  ],
};

const at = (clock: string) => new Date(`2026-11-26T${clock}:00`);

test("draws one arc per block and one dot per mark", () => {
  const { container } = render(<DayRing day={day} now={at("08:00")} nudging={false} />);
  expect(container.querySelectorAll("path.block")).toHaveLength(2);
  expect(container.querySelectorAll("circle.mark")).toHaveLength(2);
  expect(container.querySelectorAll("path.block-done")).toHaveLength(0); // nothing started yet
});

test("blocks fill in as the day goes on", () => {
  const { container } = render(<DayRing day={day} now={at("20:00")} nudging={false} />);
  const done = [...container.querySelectorAll("path.block-done")].map((p) => p.parentElement?.dataset.kind);
  expect(done).toEqual(["college", "study"]);
});

test("the due reminder pulses only while nudging", () => {
  const quiet = render(<DayRing day={day} now={at("18:01")} nudging={false} />);
  expect(quiet.container.querySelectorAll("circle.due")).toHaveLength(0);
  quiet.unmount();
  const { container } = render(<DayRing day={day} now={at("18:01")} nudging={true} />);
  const due = container.querySelectorAll("circle.due");
  expect(due).toHaveLength(1);
  expect(due[0].textContent).toBe("18:00 gym");
});

test("an empty ring before the core sends the day", () => {
  const { container } = render(<DayRing day={null} now={at("12:00")} nudging={false} />);
  expect(container.querySelector("circle.track")).toBeTruthy();
  expect(container.querySelector("line.now")).toBeTruthy();
});
