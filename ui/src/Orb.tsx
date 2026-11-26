import { Look, LOOK_LABEL } from "./orbState";

/**
 * The orb itself. `data-look` picks the animation in styles.css; the three particle
 * dots only show while thinking.
 */
export function Orb({ look, onClick, onMenu }: { look: Look; onClick: () => void; onMenu?: () => void }) {
  return (
    <button
      className="orb"
      data-look={look}
      aria-label={LOOK_LABEL[look]}
      title={LOOK_LABEL[look]}
      onClick={onClick}
      onContextMenu={(e) => {
        e.preventDefault(); // no browser menu: right-click opens the Command Deck
        onMenu?.();
      }}
    >
      <span className="core" />
      <span className="particles" aria-hidden="true">
        <i />
        <i />
        <i />
      </span>
    </button>
  );
}
