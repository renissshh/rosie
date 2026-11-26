import { Look, LOOK_LABEL } from "./orb";

/**
 * The orb itself. `data-look` picks the animation in styles.css; the three particle
 * dots only show while thinking.
 */
export function Orb({ look, onClick }: { look: Look; onClick: () => void }) {
  return (
    <button className="orb" data-look={look} aria-label={LOOK_LABEL[look]} title={LOOK_LABEL[look]} onClick={onClick}>
      <span className="core" />
      <span className="particles" aria-hidden="true">
        <i />
        <i />
        <i />
      </span>
    </button>
  );
}
