/**
 * Rosie's window. The page is transparent; only the orb is drawn.
 * Drag the edge around the orb to move it; click the orb to talk (or to dismiss a
 * reminder that is pulsing).
 */
import { BridgeClient } from "./bridge";
import { look } from "./orb";
import { Orb } from "./Orb";
import { useCore } from "./useCore";

export default function App({ makeClient }: { makeClient?: () => BridgeClient }) {
  const { model, dispatch, send } = useCore(makeClient);
  const current = look(model);

  const onOrbClick = () => {
    if (current === "nudge") dispatch({ kind: "dismiss" });
    else send({ type: "listen" });
  };

  return (
    <main className="stage" data-tauri-drag-region>
      <Orb look={current} onClick={onOrbClick} />
    </main>
  );
}
