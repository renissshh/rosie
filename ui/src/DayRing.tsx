/**
 * The Day Ring: today's blocks drawn around the orb as a 24-hour clock.
 * Each block is a faint arc that fills in brightly as its time passes; reminders and
 * the brief/review are dots; a small hand shows "now". While a nudge is showing, the
 * reminder that is due pulses amber. Clicks pass through to the orb.
 */
import { arcPath, DAY, dueMarks, elapsed, KIND_COLOR, minutesOf, point, span, toMinutes } from "./dayRing";
import { DayData } from "./protocol";

const SIZE = 200;
const C = SIZE / 2;
const R = 88;

export function DayRing({ day, now, nudging }: { day: DayData | null; now: Date; nudging: boolean }) {
  const minutes = minutesOf(now);
  const due = new Set(nudging && day ? dueMarks(day.marks, minutes).map((m) => m.at + m.text) : []);
  const [hx, hy] = point(C, C, R + 7, minutes);
  const [ix, iy] = point(C, C, R - 7, minutes);
  return (
    <svg className="day-ring" viewBox={`0 0 ${SIZE} ${SIZE}`} aria-label="Today's plan" role="img">
      <circle className="track" cx={C} cy={C} r={R} />
      {day?.blocks.map((block) => {
        const [start, end] = span(block);
        const done = elapsed(block, minutes);
        return (
          <g key={block.start + block.kind} data-kind={block.kind}>
            <title>{`${block.label} ${block.start}-${block.end}`}</title>
            <path className="block" d={arcPath(C, C, R, start, end % DAY)} stroke={KIND_COLOR[block.kind]} />
            {done && done[1] > done[0] && (
              <path className="block-done" d={arcPath(C, C, R, done[0], done[1] % DAY)} stroke={KIND_COLOR[block.kind]} />
            )}
          </g>
        );
      })}
      {day?.marks.map((mark) => {
        const [x, y] = point(C, C, R, toMinutes(mark.at));
        const isDue = due.has(mark.at + mark.text);
        return (
          <circle key={mark.at + mark.text} className={isDue ? "mark due" : "mark"} data-kind={mark.kind} cx={x} cy={y} r={isDue ? 5 : 3.5}>
            <title>{`${mark.at} ${mark.text}`}</title>
          </circle>
        );
      })}
      <line className="now" x1={ix} y1={iy} x2={hx} y2={hy} />
    </svg>
  );
}
