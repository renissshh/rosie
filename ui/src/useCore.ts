/**
 * Connects the page to Rosie's core: one BridgeClient for the window's lifetime,
 * its status and events fed into the orb reducer, plus a clock tick so nudges fade.
 */
import { useEffect, useReducer, useRef } from "react";
import { BridgeClient } from "./bridge";
import { initialModel, orbReducer } from "./orb";
import { CoreEvent, OrbRequest } from "./protocol";

export function useCore(makeClient: () => BridgeClient = () => new BridgeClient(), onEvent?: (e: CoreEvent) => void) {
  const [model, dispatch] = useReducer(orbReducer, initialModel);
  const clientRef = useRef<BridgeClient | null>(null);
  const onEventRef = useRef(onEvent);
  onEventRef.current = onEvent;

  useEffect(() => {
    const client = makeClient();
    clientRef.current = client;
    const offStatus = client.onStatus((status) => dispatch({ kind: "status", status }));
    const offEvent = client.onEvent((event) => {
      dispatch({ kind: "event", event, now: Date.now() });
      onEventRef.current?.(event);
    });
    client.start();
    const tick = setInterval(() => dispatch({ kind: "tick", now: Date.now() }), 5000);
    return () => {
      clearInterval(tick);
      offStatus();
      offEvent();
      client.stop();
    };
    // The client is made once per window.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const send = (request: OrbRequest) => clientRef.current?.send(request) ?? false;
  return { model, dispatch, send };
}
