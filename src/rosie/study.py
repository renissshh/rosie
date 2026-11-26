"""Study coach: timed sessions, and which subjects are being neglected.

    "start studying DBMS"   -> start_study: the clock starts (survives a restart)
    "done"                  -> stop_study:  - 19:00 DBMS (52 min) in study-log/
    "how's my studying?"    -> study_report: minutes per subject over 14 days,
                               and the weak ones: never/long ago studied, or far
                               below the average

Everything comes from the study-log notes in rosie-vault (the same lines the Command
Deck's "+ Study" button writes), so a session typed by hand in Obsidian counts too.
Subjects are the `subjects` list in rosie.yaml; without one, the subjects seen in the
logs are used. Plain code, no LLM: the agent explains the report in her own words.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

from rosie.quicklog import study_note
from rosie.tools import Tool, ToolError, ToolRegistry
from rosie.vault_writer import VaultWriter

_LINE = re.compile(r"^- (\d{1,2}:\d{2}) (.+?)(?: \((\d+) min\))?\s*$")
WINDOW_DAYS = 14
STALE_DAYS = 7  # not studied for a week -> weak
MAX_SESSION_MIN = 8 * 60  # a forgotten timer is capped, not logged as 30 hours


@dataclass(frozen=True)
class Session:
    day: date
    time: str
    text: str
    minutes: int | None


def read_sessions(vault: Path, since: date, until: date) -> list[Session]:
    """All study-log entries from `since` to `until` (inclusive), oldest first."""
    sessions = []
    day = since
    while day <= until:
        note = vault / study_note(day)
        if note.is_file():
            for line in note.read_text(encoding="utf-8").splitlines():
                match = _LINE.match(line.strip())
                if match:
                    minutes = int(match.group(3)) if match.group(3) else None
                    sessions.append(Session(day, match.group(1), match.group(2), minutes))
        day += timedelta(days=1)
    return sessions


def subject_of(text: str, subjects: list[str]) -> str:
    """Which configured subject a log line is about ('DBMS normal forms' -> 'DBMS')."""
    words = re.findall(r"[\w+#.]+", text.lower())
    for subject in subjects:
        wanted = subject.lower().split()
        if any(words[i : i + len(wanted)] == wanted for i in range(len(words))):
            return subject
    return text.split()[0] if not subjects else "other"


@dataclass(frozen=True)
class SubjectStats:
    subject: str
    minutes: int
    sessions: int
    last: date | None


def subject_stats(sessions: list[Session], subjects: list[str]) -> list[SubjectStats]:
    """Minutes, session count and last study day per subject. Untimed entries count
    as sessions with 0 minutes, so they still mark the subject as studied."""
    names = list(subjects) or sorted({subject_of(s.text, []) for s in sessions})
    totals = {name: [0, 0, None] for name in names}
    for session in sessions:
        name = subject_of(session.text, subjects)
        if name not in totals:
            continue  # "other" when a subjects list is set
        entry = totals[name]
        entry[0] += session.minutes or 0
        entry[1] += 1
        entry[2] = max(entry[2], session.day) if entry[2] else session.day
    return [SubjectStats(n, t[0], t[1], t[2]) for n, t in totals.items()]


def weak_subjects(stats: list[SubjectStats], today: date) -> list[tuple[SubjectStats, str]]:
    """Subjects that need attention, worst first, each with the reason."""
    if not stats:
        return []
    average = sum(s.minutes for s in stats) / len(stats)
    weak = []
    for s in stats:
        if s.last is None:
            weak.append((s, f"not studied in the last {WINDOW_DAYS} days"))
        elif (today - s.last).days >= STALE_DAYS:
            weak.append((s, f"last studied {(today - s.last).days} days ago"))
        elif average and s.minutes < average / 2:
            weak.append((s, f"{s.minutes} min vs {average:.0f} min average"))
    return sorted(weak, key=lambda pair: (pair[0].last or date.min, pair[0].minutes))


def report(vault: Path, subjects: list[str], today: date) -> str:
    since = today - timedelta(days=WINDOW_DAYS - 1)
    sessions = read_sessions(vault, since, today)
    if not sessions:
        return f"No study sessions logged in the last {WINDOW_DAYS} days."
    stats = subject_stats(sessions, subjects)
    lines = [f"Study, last {WINDOW_DAYS} days:"]
    for s in sorted(stats, key=lambda s: -s.minutes):
        last = f", last {s.last:%a %d %b}" if s.last else ""
        lines.append(f"- {s.subject}: {s.minutes} min in {s.sessions} sessions{last}")
    weak = weak_subjects(stats, today)
    if weak:
        lines.append("Needs attention:")
        lines += [f"- {s.subject}: {why}" for s, why in weak]
    return "\n".join(lines)


class StudyTimer:
    """A running study session, kept in a small JSON file so a restart doesn't lose it."""

    def __init__(self, state_file: Path, writer: VaultWriter, now: Callable[[], datetime]):
        self.state_file = state_file
        self.writer = writer
        self.now = now

    def current(self) -> dict | None:
        if not self.state_file.is_file():
            return None
        try:
            return json.loads(self.state_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def start(self, subject: str) -> str:
        subject = " ".join(subject.split())
        if not subject:
            raise ToolError("which subject?")
        running = self.current()
        if running:
            raise ToolError(f"a {running['subject']} session is already running; stop it first")
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        started = self.now()
        self.state_file.write_text(
            json.dumps({"subject": subject, "started": started.isoformat()}), encoding="utf-8"
        )
        return f"Started {subject} at {started:%H:%M}. Say when you're done."

    def stop(self) -> str:
        running = self.current()
        if not running:
            raise ToolError("no study session is running")
        started = datetime.fromisoformat(running["started"])
        minutes = int((self.now() - started).total_seconds() // 60)
        capped = min(minutes, MAX_SESSION_MIN)
        rel = study_note(started.date())
        head = "" if (self.writer.root / rel).is_file() else f"# Study, {started:%a %d %b %Y}\n\n"
        self.writer.append(rel, f"{head}- {started:%H:%M} {running['subject']} ({capped} min)\n")
        self.state_file.unlink(missing_ok=True)
        note = " (capped: was the timer left running?)" if capped < minutes else ""
        return f"Logged {running['subject']}: {capped} min{note}."


def register_study_tools(
    registry: ToolRegistry, timer: StudyTimer, subjects: list[str], today: Callable[[], date]
) -> None:
    """start_study / stop_study write the study log ("log.study": allowed);
    study_report only reads it."""
    registry.register(
        Tool(
            "start_study",
            "Start timing a study session for a subject",
            lambda subject: timer.start(subject),
            "personal",
            {
                "type": "object",
                "properties": {"subject": {"type": "string", "description": "e.g. DBMS"}},
                "required": ["subject"],
            },
            action="log.study",
        )
    )
    registry.register(
        Tool(
            "stop_study",
            "Stop the running study session and log its minutes",
            lambda: timer.stop(),
            "personal",
            action="log.study",
        )
    )
    registry.register(
        Tool(
            "study_report",
            "Minutes per subject over the last 14 days and the subjects being neglected",
            lambda: report(timer.writer.root, subjects, today()),
            "read",
        )
    )
