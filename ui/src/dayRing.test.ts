import { arcPath, currentBlock, dueMarks, elapsed, nextBlock, point, span, toMinutes } from "./dayRing";
import { DayBlock, DayMark } from "./protocol";

const block = (start: string, end: string, kind: DayBlock["kind"] = "study"): DayBlock => ({ start, end, kind, label: kind });

test("clock positions: midnight top, 06:00 right, noon bottom, 18:00 left", () => {
  expect(point(100, 100, 50, 0)).toEqual([100, 50]);
  expect(point(100, 100, 50, toMinutes("06:00"))).toEqual([150, 100]);
  expect(point(100, 100, 50, toMinutes("12:00"))).toEqual([100, 150]);
  expect(point(100, 100, 50, toMinutes("18:00"))).toEqual([50, 100]);
});

test("short arcs use the small sweep, long ones the large", () => {
  expect(arcPath(100, 100, 50, 0, 360)).toBe("M 100 50 A 50 50 0 0 1 150 100");
  expect(arcPath(100, 100, 50, 0, 1080)).toBe("M 100 50 A 50 50 0 1 1 50 100");
});

test("arcs that cross midnight wrap around the top", () => {
  // 18:00 -> 06:00 is twelve hours over the top: from the left to the right
  expect(arcPath(100, 100, 50, 1080, 360)).toBe("M 50 100 A 50 50 0 0 1 150 100");
});

test("a 24-hour arc is drawn as two halves", () => {
  expect(arcPath(100, 100, 50, 0, 0).match(/A /g)).toHaveLength(2);
});

test("span unwraps blocks that cross midnight", () => {
  expect(span(block("09:00", "15:30"))).toEqual([540, 930]);
  expect(span(block("23:30", "06:30"))).toEqual([1410, 1830]);
});

test("elapsed part grows with the clock and stops at the end", () => {
  const study = block("19:00", "21:00");
  expect(elapsed(study, toMinutes("18:00"))).toBeNull();
  expect(elapsed(study, toMinutes("20:00"))).toEqual([1140, 1200]);
  expect(elapsed(study, toMinutes("22:00"))).toEqual([1140, 1260]);
});

test("elapsed works after midnight inside a night block", () => {
  const sleep = block("23:30", "06:30", "sleep");
  expect(elapsed(sleep, toMinutes("03:00"))).toEqual([1410, 1620]);
  expect(elapsed(sleep, toMinutes("23:45"))).toEqual([1410, 1425]);
  expect(elapsed(sleep, toMinutes("12:00"))).toBeNull();
});

test("current and next block", () => {
  const blocks = [block("09:00", "15:30", "college"), block("19:00", "21:00"), block("23:30", "06:30", "sleep")];
  expect(currentBlock(blocks, toMinutes("10:00"))?.kind).toBe("college");
  expect(currentBlock(blocks, toMinutes("16:00"))).toBeNull();
  expect(currentBlock(blocks, toMinutes("02:00"))?.kind).toBe("sleep");
  expect(nextBlock(blocks, toMinutes("16:00"))?.kind).toBe("study");
  expect(nextBlock(blocks, toMinutes("23:45"))).toBeNull();
});

test("due marks are reminders within 15 minutes, across midnight too", () => {
  const marks: DayMark[] = [
    { at: "18:00", kind: "reminder", text: "gym" },
    { at: "18:20", kind: "reminder", text: "later" },
    { at: "18:05", kind: "brief", text: "not a reminder" },
    { at: "23:55", kind: "reminder", text: "late" },
  ];
  expect(dueMarks(marks, toMinutes("18:04")).map((m) => m.text)).toEqual(["gym"]);
  expect(dueMarks(marks, toMinutes("00:05")).map((m) => m.text)).toEqual(["late"]);
});
