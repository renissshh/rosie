/**
 * Opening the Command Deck window from the orb. Outside Tauri (tests, `npm run dev`
 * in a browser) there is no second window, so this quietly does nothing.
 */
export async function openDeck(): Promise<void> {
  if (!("__TAURI_INTERNALS__" in window)) return;
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
