/**
 * The orb's end of the WebSocket to Rosie's core.
 *
 * It keeps reconnecting (1 s, 2 s, 4 s ... up to 10 s), because at login the orb
 * often opens before the Python core is ready, and the core may restart.
 * Listeners get every event; `status` tells the UI whether the core is reachable.
 */
import { CORE_URL, CoreEvent, OrbRequest, parseEvent } from "./protocol";

export type Status = "connecting" | "open" | "closed";

/** The parts of the browser WebSocket we use, so tests can pass a fake. */
export interface SocketLike {
  readyState: number;
  onopen: ((ev: unknown) => void) | null;
  onclose: ((ev: unknown) => void) | null;
  onmessage: ((ev: { data: unknown }) => void) | null;
  onerror: ((ev: unknown) => void) | null;
  send(data: string): void;
  close(): void;
}

export interface BridgeOptions {
  url?: string;
  makeSocket?: (url: string) => SocketLike;
  setTimer?: (fn: () => void, ms: number) => unknown;
  clearTimer?: (handle: unknown) => void;
}

const OPEN = 1;
export const MAX_BACKOFF_MS = 10_000;

export function backoff(attempt: number): number {
  return Math.min(1000 * 2 ** attempt, MAX_BACKOFF_MS);
}

export class BridgeClient {
  status: Status = "closed";
  private socket: SocketLike | null = null;
  private attempt = 0;
  private timer: unknown = null;
  private stopped = true;
  private listeners = new Set<(event: CoreEvent) => void>();
  private statusListeners = new Set<(status: Status) => void>();
  private readonly url: string;
  private readonly makeSocket: (url: string) => SocketLike;
  private readonly setTimer: (fn: () => void, ms: number) => unknown;
  private readonly clearTimer: (handle: unknown) => void;

  constructor(options: BridgeOptions = {}) {
    this.url = options.url ?? CORE_URL;
    this.makeSocket = options.makeSocket ?? ((url) => new WebSocket(url) as unknown as SocketLike);
    this.setTimer = options.setTimer ?? ((fn, ms) => setTimeout(fn, ms));
    this.clearTimer = options.clearTimer ?? ((handle) => clearTimeout(handle as number));
  }

  start(): void {
    this.stopped = false;
    this.connect();
  }

  stop(): void {
    this.stopped = true;
    if (this.timer !== null) this.clearTimer(this.timer);
    this.timer = null;
    this.socket?.close();
    this.socket = null;
    this.setStatus("closed");
  }

  /** Send a request; returns false (and drops it) while the core is unreachable. */
  send(request: OrbRequest): boolean {
    if (!this.socket || this.socket.readyState !== OPEN) return false;
    this.socket.send(JSON.stringify(request));
    return true;
  }

  onEvent(listener: (event: CoreEvent) => void): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  onStatus(listener: (status: Status) => void): () => void {
    this.statusListeners.add(listener);
    return () => this.statusListeners.delete(listener);
  }

  private connect(): void {
    this.timer = null;
    this.setStatus("connecting");
    const socket = this.makeSocket(this.url);
    this.socket = socket;
    socket.onopen = () => {
      this.attempt = 0;
      this.setStatus("open");
    };
    socket.onmessage = (ev) => {
      const event = parseEvent(ev.data);
      if (event) this.listeners.forEach((listener) => listener(event));
    };
    socket.onerror = () => socket.close();
    socket.onclose = () => {
      if (this.socket !== socket) return; // an old socket we already replaced
      this.socket = null;
      this.setStatus("closed");
      if (!this.stopped) {
        this.timer = this.setTimer(() => this.connect(), backoff(this.attempt));
        this.attempt += 1;
      }
    };
  }

  private setStatus(status: Status): void {
    if (this.status === status) return;
    this.status = status;
    this.statusListeners.forEach((listener) => listener(status));
  }
}
