"""Training coach: log sets by voice, suggest the next weight, spot stalls.

    "bench 3x8 at 40 kg"            -> - 18:10 Bench press 3x8 @ 40 kg
    "squat five by five 60 kilos"   -> - 18:20 Squat 5x5 @ 60 kg
    "pull ups 3 sets of 10"         -> - 18:30 Pull ups 3x10          (bodyweight)

Lines go to rosie-vault/training-log/YYYY-MM-DD.md (the same notes the Command Deck's
"+ Gym" button writes). From that history:

- progression: the same weight for the same sets x reps in two sessions in a row means
  it's time to add weight: +2.5 kg, or +5 kg for squat, deadlift and leg press;
- stall: no increase in the top weight over the last three sessions spread across two
  weeks or more. Rosie suggests a deload (-10%) or a new rep range.

Plain rules that are easy to explain and test; no LLM needed for the numbers.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

from rosie.tools import Tool, ToolError, ToolRegistry
from rosie.vault_writer import VaultWriter

HISTORY_DAYS = 90
STALL_SESSIONS = 3
STALL_DAYS = 14
LOWER_BODY = {"squat", "deadlift", "leg press", "romanian deadlift"}
ALIASES = {
    "bench": "bench press",
    "ohp": "overhead press",
    "dl": "deadlift",
    "rdl": "romanian deadlift",
    "pullup": "pull ups",
    "pullups": "pull ups",
    "pull up": "pull ups",
    "squats": "squat",
    "deadlifts": "deadlift",
}
_WORDS = {
    w: n
    for n, w in enumerate(
        [
            "zero",
            "one",
            "two",
            "three",
            "four",
            "five",
            "six",
            "seven",
            "eight",
            "nine",
            "ten",
            "eleven",
            "twelve",
            "thirteen",
            "fourteen",
            "fifteen",
            "sixteen",
            "seventeen",
            "eighteen",
            "nineteen",
            "twenty",
        ]
    )
}
_WORDS |= {"thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80}
_SETS = re.compile(r"(\d+)\s*(?:x|by|\*|sets? of)\s*(\d+)(?:\s*reps?)?")
_WEIGHT = re.compile(
    r"(?:@\s*|\bat\s+|\bwith\s+)(\d+(?:\.\d+)?)(?:\s*(?:kg|kgs|kilos?|kilograms?)\b)?"
    r"|(\d+(?:\.\d+)?)\s*(?:kg|kgs|kilos?|kilograms?)\b"
)
_LOG_LINE = re.compile(r"^- (\d{1,2}:\d{2}) (.+?) (\d+)x(\d+)(?: @ (\d+(?:\.\d+)?) kg)?\s*$")


@dataclass(frozen=True)
class SetEntry:
    exercise: str  # normalised, lower case: "bench press"
    sets: int
    reps: int
    weight: float | None = None  # kg; None = bodyweight

    def describe(self) -> str:
        weight = f" @ {self.weight:g} kg" if self.weight is not None else ""
        return f"{self.exercise.capitalize()} {self.sets}x{self.reps}{weight}"

    def line(self, at: datetime) -> str:
        return f"- {at:%H:%M} {self.describe()}"


def _numbers(text: str) -> str:
    """'forty two' -> '42', 'five' -> '5', so spoken numbers parse like typed ones."""
    words = text.split()
    out: list[str] = []
    for word in words:
        if word == "hundred" and out and out[-1].isdigit():
            out[-1] = str(int(out[-1]) * 100)  # "one hundred" -> 100
            continue
        value = _WORDS.get(word)
        if value is None:
            out.append(word)
        elif out and out[-1].isdigit() and int(out[-1]) % 10 == 0 and int(out[-1]) >= 20:
            out[-1] = str(int(out[-1]) + value)  # "forty two" -> 42, "one hundred ten" -> 110
        else:
            out.append(str(value))
    return " ".join(out)


def normalise(name: str) -> str:
    name = " ".join(re.sub(r"[^a-z ]", " ", name.lower()).split())
    return ALIASES.get(name, name)


def parse_sets(text: str) -> SetEntry | None:
    """Read one exercise from a sentence; None if sets x reps aren't there."""
    clean = _numbers(re.sub(r"[,;]", " ", text.lower()).replace("×", "x"))
    clean = re.sub(r"^(?:log|logged|did|done)\s+", "", clean.strip())
    sets = _SETS.search(clean)
    if not sets:
        return None
    weight = _WEIGHT.search(clean)
    cut = min(sets.start(), weight.start() if weight else len(clean))
    exercise = normalise(clean[:cut])
    if not exercise:
        return None
    return SetEntry(
        exercise,
        int(sets.group(1)),
        int(sets.group(2)),
        float(weight.group(1) or weight.group(2)) if weight else None,
    )


@dataclass(frozen=True)
class Session:
    day: date
    entry: SetEntry


def read_history(vault: Path, until: date, days: int = HISTORY_DAYS) -> list[Session]:
    """Every parsable line in training-log over the last `days` days, oldest first."""
    history = []
    for offset in range(days - 1, -1, -1):
        day = until - timedelta(days=offset)
        note = vault / "training-log" / f"{day:%Y-%m-%d}.md"
        if not note.is_file():
            continue
        for line in note.read_text(encoding="utf-8").splitlines():
            match = _LOG_LINE.match(line.strip())
            if match:
                _, name, sets, reps, weight = match.groups()
                entry = SetEntry(
                    normalise(name), int(sets), int(reps), float(weight) if weight else None
                )
                history.append(Session(day, entry))
    return history


def sessions_of(history: list[Session], exercise: str) -> list[Session]:
    """One entry per day for an exercise (the heaviest), oldest first."""
    best: dict[date, Session] = {}
    for s in history:
        if s.entry.exercise != exercise:
            continue
        current = best.get(s.day)
        if current is None or (s.entry.weight or 0) >= (current.entry.weight or 0):
            best[s.day] = s
    return [best[d] for d in sorted(best)]


def increment(exercise: str) -> float:
    return 5.0 if exercise in LOWER_BODY else 2.5


def next_weight(sessions: list[Session]) -> float | None:
    """Add weight after the same weight x sets x reps twice in a row; else None."""
    if len(sessions) < 2:
        return None
    last, before = sessions[-1].entry, sessions[-2].entry
    if last.weight is None:
        return None
    same = (last.weight, last.sets, last.reps) == (before.weight, before.sets, before.reps)
    return last.weight + increment(last.exercise) if same else None


def stalled(sessions: list[Session]) -> bool:
    """No increase in weight across the last 3 sessions spanning 2+ weeks."""
    recent = sessions[-STALL_SESSIONS:]
    if len(recent) < STALL_SESSIONS or recent[0].entry.weight is None:
        return False
    if (recent[-1].day - recent[0].day).days < STALL_DAYS:
        return False
    return max(s.entry.weight or 0 for s in recent[1:]) <= (recent[0].entry.weight or 0)


def advice(history: list[Session], exercise: str) -> str:
    sessions = sessions_of(history, exercise)
    if not sessions:
        return ""
    name = exercise.capitalize()
    if stalled(sessions):
        weight = sessions[-1].entry.weight or 0
        deload = round(weight * 0.9 / 2.5) * 2.5
        return (
            f"{name} has been stuck at {weight:g} kg for {STALL_SESSIONS} sessions. "
            f"Try a deload to {deload:g} kg, or a new rep range."
        )
    target = next_weight(sessions)
    if target is not None:
        return f"{name}: same weight twice in a row, try {target:g} kg next time."
    return ""


def report(vault: Path, today: date) -> str:
    history = read_history(vault, today)
    if not history:
        return f"No training logged in the last {HISTORY_DAYS} days."
    lines = [f"Training, last {HISTORY_DAYS} days:"]
    for exercise in sorted({s.entry.exercise for s in history}):
        sessions = sessions_of(history, exercise)
        last = sessions[-1].entry
        weight = f" @ {last.weight:g} kg" if last.weight is not None else ""
        done = f"{len(sessions)} sessions, last {last.sets}x{last.reps}{weight}"
        line = f"- {exercise.capitalize()}: {done}"
        hint = advice(history, exercise)
        lines.append(line + (f". {hint}" if hint else ""))
    return "\n".join(lines)


def stall_alerts(vault: Path, today: date) -> list[str]:
    """One sentence per stalled exercise (for the morning brief)."""
    history = read_history(vault, today)
    exercises = sorted({s.entry.exercise for s in history})
    return [advice(history, e) for e in exercises if stalled(sessions_of(history, e))]


class TrainingLog:
    def __init__(self, writer: VaultWriter, now: Callable[[], datetime]) -> None:
        self.writer = writer
        self.now = now

    def log(self, text: str) -> str:
        entry = parse_sets(text)
        if entry is None:
            raise ToolError("say it like 'bench 3x8 at 40 kg' (exercise, sets x reps, weight)")
        now = self.now()
        rel = f"training-log/{now:%Y-%m-%d}.md"
        head = "" if (self.writer.root / rel).is_file() else f"# Training, {now:%a %d %b %Y}\n\n"
        self.writer.append(rel, head + entry.line(now) + "\n")
        reply = f"Logged {entry.describe()}."
        hint = advice(read_history(self.writer.root, now.date()), entry.exercise)
        return f"{reply} {hint}".strip()


def register_training_tools(registry: ToolRegistry, log: TrainingLog) -> None:
    registry.register(
        Tool(
            "log_sets",
            "Log one exercise to the training log, e.g. 'bench 3x8 at 40 kg'",
            lambda text: log.log(text),
            "personal",
            {
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "exercise, sets x reps, weight"}
                },
                "required": ["text"],
            },
            action="log.training",
        )
    )
    registry.register(
        Tool(
            "training_report",
            "Training over the last 90 days per exercise, with progression and stall advice",
            lambda: report(log.writer.root, log.now().date()),
            "read",
        )
    )
