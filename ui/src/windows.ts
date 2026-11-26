/**
 * Opening the Command Deck window from the orb. Outside Tauri (tests, `npm run dev`
 * in a browser) there is no second window, so this quietly does nothing.
 */
const inTauri = () => "__TAURI_INTERNALS__" in window;

export async function openDeck(): Promise<void> {
  if (!inTauri()) return;
  const { WebviewWindow } = await import("@tauri-apps/api/webviewWindow");
  const deck = await WebviewWindow.getByLabel("deck");
  if (!deck) return;
  await deck.show();
  await deck.unminimize();
  await deck.setFocus();
}

/** Which window this page is: the orb, or the deck (opened at index.html#deck). */
export function windowKind(hash: string = window.location.hash): "orb" | "deck" {
  return hash === "#deck" ? "deck" : "orb";
}

/** The Tauri shell emits "hotkey" when Ctrl+Space is pressed. Returns an unsubscribe. */
export function onHotkey(handler: () => void): () => void {
  if (!inTauri()) return () => {};
  let stop: (() => void) | null = null;
  let cancelled = false;
  void import("@tauri-apps/api/event").then(({ listen }) =>
    listen("hotkey", () => handler()).then((unlisten) => {
      if (cancelled) unlisten();
      else stop = unlisten;
    }),
  );
  return () => {
    cancelled = true;
    stop?.();
  };
}
