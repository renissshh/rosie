/**
 * Rosie's window. The page is transparent; only the orb and its Day Ring are drawn.
 * Drag the edge around the orb to move it; click the orb to talk (or to dismiss a
 * reminder that is pulsing).
 */
import { useEffect, useState } from "react";
import { BridgeClient } from "./bridge";
import { DayRing } from "./DayRing";
import { look } from "./orb";
import { Orb } from "./Orb";
import { CoreEvent, DayData } from "./protocol";
import { useCore } from "./useCore";

export default function App({ makeClient, clock = () => new Date() }: { makeClient?: () => BridgeClient; clock?: () => Date }) {
  const [day, setDay] = useState<DayData | null>(null);
  const [now, setNow] = useState(clock);
  const { model, dispatch, send } = useCore(makeClient, (event: CoreEvent) => {
    if (event.type === "day") setDay(event);
  });
  const current = look(model);

  useEffect(() => {
    const timer = setInterval(() => setNow(clock()), 30_000); // the ring's hand
    return () => clearInterval(timer);
  }, [clock]);

  const onOrbClick = () => {
    if (current === "nudge") dispatch({ kind: "dismiss" });
    else send({ type: "listen" });
  };

  return (
    <main className="stage" data-tauri-drag-region>
      <DayRing day={day} now={now} nudging={current === "nudge"} />
      <Orb look={current} onClick={onOrbClick} />
    </main>
  );
}
