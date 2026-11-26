/**
 * Rosie's window. The whole page is transparent; only the orb is drawn.
 * `data-tauri-drag-region` lets you drag the orb anywhere on the screen.
 */
export default function App() {
  return (
    <main className="stage" data-tauri-drag-region>
      <div className="orb" role="img" aria-label="Rosie" data-tauri-drag-region>
        <div className="core" />
      </div>
    </main>
  );
}
