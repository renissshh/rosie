/**
 * The Command Deck: the morning brief as cards, the live transcript, a text box to
 * talk to Rosie, and one-tap logging (study, gym, task). It opens from the orb
 * (right-click, or Ctrl+Space) in its own window and talks to the same core.
 */
import { FormEvent, useEffect, useState } from "react";
import { BridgeClient } from "./bridge";
import { minutesOf } from "./ringGeometry";
import { addLine, daysLeft, Line, nowNext } from "./deckModel";
import { BriefData, CoreEvent, DayData, HealthData } from "./protocol";
import { useCore } from "./useCore";

type LogKind = "study" | "gym" | "task";
const LOG_BUTTONS: { what: LogKind; label: string; hint: string }[] = [
  { what: "study", label: "Study", hint: "e.g. DBMS normal forms 45m" },
  { what: "gym", label: "Gym", hint: "e.g. push day, bench 3x8 40kg" },
  { what: "task", label: "Task", hint: "e.g. buy notebook" },
];

export default function Deck({ makeClient, clock = () => new Date() }: { makeClient?: () => BridgeClient; clock?: () => Date }) {
  const [lines, setLines] = useState<Line[]>([]);
  const [brief, setBrief] = useState<BriefData | null>(null);
  const [health, setHealth] = useState<HealthData | null>(null);
  const [day, setDay] = useState<DayData | null>(null);
  const [confirms, setConfirms] = useState<{ id: string; question: string }[]>([]);
  const [notice, setNotice] = useState("");
  const [text, setText] = useState("");
  const [now, setNow] = useState(clock);

  const { model, send } = useCore(makeClient, (event: CoreEvent) => {
    if (event.type === "transcript") setLines((old) => addLine(old, { role: event.role, text: event.text }));
    else if (event.type === "brief") setBrief(event);
    else if (event.type === "health") setHealth(event);
    else if (event.type === "day") setDay(event);
    else if (event.type === "confirm") setConfirms((old) => [...old, { id: event.id, question: event.question }]);
    else if (event.type === "logged" || event.type === "error") setNotice(event.text);
  });

  useEffect(() => {
    const timer = setInterval(() => setNow(clock()), 30_000);
    return () => clearInterval(timer);
  }, [clock]);

  const online = model.core === "open";
  const plan = nowNext(day, minutesOf(now));

  const ask = (e: FormEvent) => {
    e.preventDefault();
    if (text.trim() && send({ type: "ask", text: text.trim() })) setText("");
  };

  const log = (what: LogKind) => {
    if (!text.trim()) {
      setNotice(`Type what to log first (${LOG_BUTTONS.find((b) => b.what === what)!.hint}).`);
      return;
    }
    if (send({ type: "log", what, text: text.trim() })) setText("");
  };

  const answer = (id: string, allow: boolean) => {
    send({ type: "confirm_reply", id, allow });
    setConfirms((old) => old.filter((c) => c.id !== id));
  };

  return (
    <main className="deck">
      <header>
        <h1>Rosie</h1>
        <span className={online ? "status on" : "status"}>{online ? "online" : "core offline"}</span>
      </header>

      {confirms.map((c) => (
        <section key={c.id} className="card confirm" aria-label="Rosie asks">
          <p>{c.question}</p>
          <div className="row">
            <button onClick={() => answer(c.id, true)}>Allow</button>
            <button className="quiet" onClick={() => answer(c.id, false)}>
              Deny
            </button>
          </div>
        </section>
      ))}

      {health && !health.ok && (
        <section className="card problem" aria-label="Needs a hand">
          <h2>Needs a hand</h2>
          {health.checks
            .filter((c) => c.status === "fail")
            .map((c) => (
              <p key={c.name}>
                <strong>{c.name}</strong>: {c.detail}
              </p>
            ))}
          <button className="quiet" onClick={() => send({ type: "health" })}>
            Check again
          </button>
        </section>
      )}

      <section className="card" aria-label="Top 3 today">
        <h2>Top 3 today</h2>
        {brief && brief.top3.length > 0 ? (
          <ul className="tasks">
            {brief.top3.map((task) => (
              <li key={task.id} className={task.overdue ? "overdue" : undefined}>
                <input type="checkbox" aria-label={`Done: ${task.title}`} onChange={() => send({ type: "done", id: task.id })} />
                <span>{task.title}</span>
                {task.due && <small>{task.overdue ? "overdue" : task.due}</small>}
              </li>
            ))}
          </ul>
        ) : (
          <p className="muted">Nothing on the list.</p>
        )}
      </section>

      <section className="card stats" aria-label="Today">
        <div>
          <h2>Now</h2>
          <p>{plan.now ?? "Free time"}</p>
          <h2>Next</h2>
          <p>{plan.next ?? "Nothing else today"}</p>
        </div>
        <div>
          <h2>Study streak</h2>
          <p className="big">{brief ? `${brief.streak} ${brief.streak === 1 ? "day" : "days"}` : "-"}</p>
          {brief?.countdown && (
            <>
              <h2>{brief.countdown.label}</h2>
              <p>{daysLeft(brief.countdown.days)}</p>
            </>
          )}
          {brief && brief.overdue > 0 && <p className="overdue">{brief.overdue} overdue</p>}
        </div>
      </section>

      <section className="card transcript" aria-label="Conversation">
        {lines.length === 0 ? (
          <p className="muted">Say "Hey Rosie" or type below.</p>
        ) : (
          lines.map((line, i) => (
            <p key={i} className={line.role}>
              {line.text}
            </p>
          ))
        )}
      </section>

      <form onSubmit={ask} className="ask">
        <input
          aria-label="Message Rosie"
          placeholder={online ? "Ask Rosie, or type and tap a log button" : "Waiting for Rosie's core..."}
          value={text}
          onChange={(e) => setText(e.target.value)}
          disabled={!online}
        />
        <button type="submit" disabled={!online}>
          Send
        </button>
      </form>
      <div className="row quicklog" aria-label="Quick log">
        {LOG_BUTTONS.map((b) => (
          <button key={b.what} className="quiet" onClick={() => log(b.what)} disabled={!online} title={b.hint}>
            + {b.label}
          </button>
        ))}
      </div>
      {notice && (
        <p className="notice" role="status">
          {notice}
        </p>
      )}
    </main>
  );
}
