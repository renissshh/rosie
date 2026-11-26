/**
 * Messages between the orb and Rosie's core (src/rosie/bridge.py). One JSON object
 * per WebSocket message, told apart by `type`. Keep this file and docs/UI.md in sync.
 */

export type OrbState = "idle" | "listening" | "thinking" | "speaking";

export type BlockKind = "study" | "college" | "gym" | "review" | "sleep" | "other";
export interface DayBlock {
  start: string; // "HH:MM", local time
  end: string; // may be earlier than start: the block crosses midnight
  kind: BlockKind;
  label: string;
}
export interface DayMark {
  at: string; // "HH:MM"
  kind: "reminder" | "brief" | "review";
  text: string;
}
export interface DayData {
  type: "day";
  date: string; // YYYY-MM-DD
  blocks: DayBlock[];
  marks: DayMark[];
}

export interface BriefTask {
  id: string;
  title: string;
  due: string | null;
  priority: "high" | "medium" | "low" | null;
  overdue: boolean;
}
export interface BriefData {
  type: "brief";
  top3: BriefTask[];
  overdue: number;
  streak: number; // study days in a row
  countdown: { label: string; date: string; days: number } | null;
}

/** What the core sends. */
export type CoreEvent =
  | { type: "hello"; version: string }
  | { type: "pong"; id?: string | number }
  | { type: "state"; state: OrbState }
  | { type: "nudge"; title: string; text: string; urgent?: boolean }
  | { type: "focus"; on: boolean; label?: string }
  | DayData
  | BriefData
  | { type: "logged"; text: string; id?: string | number }
  | { type: "transcript"; role: "you" | "rosie"; text: string }
  | { type: "reply"; text: string; id?: string | number }
  | { type: "confirm"; id: string; question: string }
  | { type: "error"; text: string; id?: string | number };

/** What the orb sends. */
export type OrbRequest =
  | { type: "ping"; id?: string | number }
  | { type: "ask"; text: string; id?: string | number }
  | { type: "listen" }
  | { type: "log"; what: "study" | "gym" | "task"; text: string }
  | { type: "done"; id: string }
  | { type: "confirm_reply"; id: string; allow: boolean };

export const CORE_URL = "ws://127.0.0.1:8765";

/** Parse one message from the core; anything malformed is ignored (null). */
export function parseEvent(data: unknown): CoreEvent | null {
  if (typeof data !== "string") return null;
  try {
    const value: unknown = JSON.parse(data);
    if (value && typeof value === "object" && typeof (value as { type?: unknown }).type === "string") {
      return value as CoreEvent;
    }
  } catch {
    // not JSON: ignore
  }
  return null;
}
