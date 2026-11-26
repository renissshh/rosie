/**
 * Pure helpers for the Command Deck: the Now / Next line, countdown wording and the
 * live transcript (kept short so the window never grows without limit).
 */
import { currentBlock, nextBlock, toMinutes } from "./ringGeometry";
import { DayData } from "./protocol";

export const MAX_LINES = 50;

export interface Line {
  role: "you" | "rosie";
  text: string;
}

export function addLine(lines: Line[], line: Line): Line[] {
  const next = [...lines, line];
  return next.length > MAX_LINES ? next.slice(next.length - MAX_LINES) : next;
}

export interface NowNext {
  now: string | null; // "DBMS until 21:00"
  next: string | null; // "21:30 call mom"
}

/** What's on now, and the next block or timed event after now (today only). */
export function nowNext(day: DayData | null, minutes: number): NowNext {
  if (!day) return { now: null, next: null };
  const current = currentBlock(day.blocks, minutes);
  const block = nextBlock(day.blocks, minutes);
  const upcoming = day.marks
    .map((m) => ({ at: m.at, text: m.text }))
    .concat(block ? [{ at: block.start, text: block.label }] : [])
    .filter((item) => toMinutes(item.at) > minutes)
    .sort((a, b) => toMinutes(a.at) - toMinutes(b.at));
  return {
    now: current ? `${current.label} until ${current.end}` : null,
    next: upcoming[0] ? `${upcoming[0].at} ${upcoming[0].text}` : null,
  };
}

export function daysLeft(days: number): string {
  if (days === 0) return "today";
  if (days === 1) return "tomorrow";
  return `in ${days} days`;
}
