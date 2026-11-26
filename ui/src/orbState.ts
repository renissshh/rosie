/**
 * What the orb looks like right now, worked out from what the core tells it.
 *
 *   offline   the core isn't reachable (grey, no glow)
 *   listening / thinking / speaking   the voice or a typed question is in progress
 *   nudge     a reminder fired (amber pulse) until you click it or 60 s pass
 *   focus     a study block is on: dimmed, only urgent nudges get through;
 *             the others wait and show when focus ends
 *   idle      slow breathing
 *
 * Earlier in that list wins. It is a pure reducer so every rule is unit-tested.
 */
import { Status } from "./bridge";
import { CoreEvent, OrbState } from "./protocol";

export type Look = "offline" | OrbState | "nudge" | "focus";

export interface Nudge {
  title: string;
  text: string;
  urgent: boolean;
  at: number; // ms timestamp when it fired
}

export interface OrbModel {
  core: Status;
  activity: OrbState;
  focus: boolean;
  nudge: Nudge | null;
  held: Nudge[]; // nudges waiting for focus to end
}

export const NUDGE_MS = 60_000;

export const initialModel: OrbModel = {
  core: "connecting",
  activity: "idle",
  focus: false,
  nudge: null,
  held: [],
};

export type OrbAction =
  | { kind: "event"; event: CoreEvent; now: number }
  | { kind: "status"; status: Status }
  | { kind: "dismiss" }
  | { kind: "tick"; now: number };

export function orbReducer(model: OrbModel, action: OrbAction): OrbModel {
  switch (action.kind) {
    case "status":
      return action.status === "open"
        ? { ...model, core: "open" }
        : { ...model, core: action.status, activity: "idle" };
    case "dismiss":
      return { ...model, nudge: null };
    case "tick":
      return model.nudge && action.now - model.nudge.at >= NUDGE_MS ? { ...model, nudge: null } : model;
    case "event":
      return onEvent(model, action.event, action.now);
  }
}

function onEvent(model: OrbModel, event: CoreEvent, now: number): OrbModel {
  switch (event.type) {
    case "state":
      return { ...model, activity: event.state };
    case "nudge": {
      const nudge = { title: event.title, text: event.text, urgent: event.urgent === true, at: now };
      if (model.focus && !nudge.urgent) return { ...model, held: [...model.held, nudge] };
      return { ...model, nudge };
    }
    case "focus": {
      if (event.on) return { ...model, focus: true };
      const [first, ...rest] = model.held;
      // Focus over: show the first held nudge now; the rest stay listed in the deck.
      return { ...model, focus: false, nudge: first ? { ...first, at: now } : model.nudge, held: rest };
    }
    default:
      return model;
  }
}

export function look(model: OrbModel): Look {
  if (model.core !== "open") return "offline";
  if (model.activity !== "idle") return model.activity;
  if (model.nudge) return "nudge";
  if (model.focus) return "focus";
  return "idle";
}

/** Short words for screen readers and the tooltip. */
export const LOOK_LABEL: Record<Look, string> = {
  offline: "Rosie's core is offline",
  idle: "Rosie is here",
  listening: "Rosie is listening",
  thinking: "Rosie is thinking",
  speaking: "Rosie is speaking",
  nudge: "Rosie has a reminder",
  focus: "Focus time",
};
