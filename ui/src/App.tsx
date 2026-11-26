/**
 * Rosie's window. The page is transparent; only the orb and its Day Ring are drawn.
 * Drag the edge around the orb to move it; click the orb to talk (or to dismiss a
 * reminder that is pulsing); right-click it for the Command Deck.
 */
import { useEffect, useRef, useState } from "react";
import { BridgeClient } from "./bridge";
import { DayRing } from "./DayRing";
import { look } from "./orbState";
import { Orb } from "./Orb";
import { CoreEvent, DayData } from "./protocol";
import { useCore } from "./useCore";
import { onHotkey as onTauriHotkey, openDeck as openDeckWindow } from "./windows";

interface AppProps {
  makeClient?: () => BridgeClient;
  clock?: () => Date;
  openDeck?: () => void;
  onHotkey?: (handler: () => void) => () => void;
}

export default function App({
  makeClient,
  clock = () => new Date(),
  openDeck = () => void openDeckWindow(),
  onHotkey = onTauriHotkey,
}: AppProps) {
  const [day, setDay] = useState<DayData | null>(null);
  const [now, setNow] = useState(clock);
  const { model, dispatch, send } = useCore(makeClient, (event: CoreEvent) => {
    if (event.type === "day") setDay(event);
    // No microphone on the core: typing in the deck is the way to talk.
    if (event.type === "error" && event.text.startsWith("voice is off")) openDeck();
  });
  const current = look(model);

  useEffect(() => {
    const timer = setInterval(() => setNow(clock()), 30_000); // the ring's hand
    return () => clearInterval(timer);
  }, [clock]);

  const onOrbClick = () => {
    if (current === "nudge") dispatch({ kind: "dismiss" });
    else if (current === "unwell" || current === "offline") openDeck(); // shows what's wrong
    else send({ type: "listen" });
  };

  // Ctrl+Space anywhere in Windows (registered by the Tauri shell) = a click on the orb.
  const clickRef = useRef(onOrbClick);
  clickRef.current = onOrbClick;
  useEffect(() => onHotkey(() => clickRef.current()), [onHotkey]);

  return (
    <main className="stage" data-tauri-drag-region>
      <DayRing day={day} now={now} nudging={current === "nudge"} />
      <Orb look={current} onClick={onOrbClick} onMenu={openDeck} />
    </main>
  );
}
