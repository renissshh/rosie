import { initialModel, look, NUDGE_MS, OrbAction, OrbModel, orbReducer } from "./orb";
import { CoreEvent } from "./protocol";

const open = orbReducer(initialModel, { kind: "status", status: "open" });
const ev = (event: CoreEvent, now = 0): OrbAction => ({ kind: "event", event, now });
const run = (model: OrbModel, ...actions: OrbAction[]) => actions.reduce(orbReducer, model);

test("offline until the core answers", () => {
  expect(look(initialModel)).toBe("offline");
  expect(look(open)).toBe("idle");
});

test("voice and typed activity shows as listening, thinking, speaking", () => {
  for (const state of ["listening", "thinking", "speaking"] as const) {
    expect(look(run(open, ev({ type: "state", state })))).toBe(state);
  }
  expect(look(run(open, ev({ type: "state", state: "thinking" }), ev({ type: "state", state: "idle" })))).toBe("idle");
});

test("losing the core goes offline and forgets a stale activity", () => {
  const model = run(open, ev({ type: "state", state: "speaking" }), { kind: "status", status: "closed" });
  expect(look(model)).toBe("offline");
  expect(look(orbReducer(model, { kind: "status", status: "open" }))).toBe("idle");
});

test("a nudge pulses until dismissed", () => {
  const model = run(open, ev({ type: "nudge", title: "Reminder", text: "gym" }));
  expect(look(model)).toBe("nudge");
  expect(look(orbReducer(model, { kind: "dismiss" }))).toBe("idle");
});

test("a nudge fades by itself after a minute", () => {
  const model = run(open, ev({ type: "nudge", title: "R", text: "gym" }, 1000));
  expect(look(orbReducer(model, { kind: "tick", now: 1000 + NUDGE_MS - 1 }))).toBe("nudge");
  expect(look(orbReducer(model, { kind: "tick", now: 1000 + NUDGE_MS }))).toBe("idle");
});

test("speaking wins over a nudge, which shows again afterwards", () => {
  const model = run(open, ev({ type: "nudge", title: "R", text: "gym" }), ev({ type: "state", state: "speaking" }));
  expect(look(model)).toBe("speaking");
  expect(look(orbReducer(model, ev({ type: "state", state: "idle" })))).toBe("nudge");
});

test("focus dims the orb and holds normal nudges until it ends", () => {
  let model = run(open, ev({ type: "focus", on: true }), ev({ type: "nudge", title: "R", text: "water plants" }));
  expect(look(model)).toBe("focus");
  expect(model.held).toHaveLength(1);
  model = orbReducer(model, ev({ type: "focus", on: false }, 5000));
  expect(look(model)).toBe("nudge");
  expect(model.nudge?.text).toBe("water plants");
  expect(model.nudge?.at).toBe(5000); // its minute starts now
  expect(model.held).toEqual([]);
});

test("urgent nudges get through focus", () => {
  const model = run(open, ev({ type: "focus", on: true }), ev({ type: "nudge", title: "R", text: "exam!", urgent: true }));
  expect(look(model)).toBe("nudge");
  expect(model.held).toEqual([]);
});

test("unrelated events change nothing", () => {
  expect(orbReducer(open, ev({ type: "pong" }))).toBe(open);
});
