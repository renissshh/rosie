/**
 * Geometry for the Day Ring: a 24-hour clock around the orb, midnight at the top,
 * running clockwise (06:00 on the right, noon at the bottom, 18:00 on the left).
 * Pure functions, so the maths is unit-tested without drawing anything.
 */
import { BlockKind, DayBlock, DayMark } from "./protocol";

export const DAY = 24 * 60;

export const KIND_COLOR: Record<BlockKind, string> = {
  study: "#2dd4bf",
  college: "#60a5fa",
  gym: "#f472b6",
  review: "#a78bfa",
  sleep: "#475569",
  other: "#94a3b8",
};

export function toMinutes(clock: string): number {
  const [h, m] = clock.split(":").map(Number);
  return h * 60 + m;
}

export function minutesOf(date: Date): number {
  return date.getHours() * 60 + date.getMinutes();
}

/** Point on the circle for a time of day (minutes since midnight). */
export function point(cx: number, cy: number, r: number, minutes: number): [number, number] {
  const rad = (minutes / DAY) * 2 * Math.PI - Math.PI / 2;
  return [round(cx + r * Math.cos(rad)), round(cy + r * Math.sin(rad))];
}

const round = (n: number) => Math.round(n * 100) / 100;

/** SVG path for the arc from `start` to `end` minutes, clockwise; wraps past midnight. */
export function arcPath(cx: number, cy: number, r: number, start: number, end: number): string {
  let span = end - start;
  if (span <= 0) span += DAY;
  if (span >= DAY) {
    // A full circle can't be one SVG arc: draw two halves.
    const [x0, y0] = point(cx, cy, r, start);
    const [x1, y1] = point(cx, cy, r, start + DAY / 2);
    return `M ${x0} ${y0} A ${r} ${r} 0 1 1 ${x1} ${y1} A ${r} ${r} 0 1 1 ${x0} ${y0}`;
  }
  const [x0, y0] = point(cx, cy, r, start);
  const [x1, y1] = point(cx, cy, r, start + span);
  const large = span > DAY / 2 ? 1 : 0;
  return `M ${x0} ${y0} A ${r} ${r} 0 ${large} 1 ${x1} ${y1}`;
}

/** A block's [start, end] in minutes; `end` passes 1440 when it crosses midnight. */
export function span(block: DayBlock): [number, number] {
  const start = toMinutes(block.start);
  const end = toMinutes(block.end);
  return [start, end <= start ? end + DAY : end];
}

/**
 * How much of a block is behind us, as [start, end] minutes (end may pass 1440 for
 * blocks crossing midnight), or null if it hasn't started. Lets the ring "fill up".
 */
export function elapsed(block: DayBlock, now: number): [number, number] | null {
  const [start, end] = span(block);
  let t = now;
  if (t < start && end > DAY && t + DAY < end) t += DAY; // after midnight, inside the block
  if (t <= start) return null;
  return [start, Math.min(t, end)];
}

/** Marks to pulse amber while a nudge is showing: reminders within 15 minutes of now. */
export function dueMarks(marks: DayMark[], now: number, windowMin = 15): DayMark[] {
  return marks.filter((m) => {
    const gap = Math.abs(toMinutes(m.at) - now);
    return m.kind === "reminder" && Math.min(gap, DAY - gap) <= windowMin;
  });
}

/** The block happening now, for the tooltip and the Command Deck's Now / Next. */
export function currentBlock(blocks: DayBlock[], now: number): DayBlock | null {
  return (
    blocks.find((b) => {
      const done = elapsed(b, now);
      return done !== null && done[1] < span(b)[1];
    }) ?? null
  );
}

/** The next block to start after now (today only). */
export function nextBlock(blocks: DayBlock[], now: number): DayBlock | null {
  return blocks.filter((b) => toMinutes(b.start) > now).sort((a, b) => toMinutes(a.start) - toMinutes(b.start))[0] ?? null;
}
