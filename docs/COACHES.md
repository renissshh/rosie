# Coaches

Rosie coaches study and training from her own logs in rosie-vault. No LLM is needed for
the numbers: plain code reads the notes, and the agent puts the result in words.

Every morning brief ends with a **Coach** section when there's something to say: up to
two subjects that need attention, and any lift that has stalled. Nothing logged yet
means nothing is said (no nagging about an empty log).

## Study coach

Set your subjects once in `config/rosie.yaml`:

```yaml
subjects: [DBMS, OS, Java, Maths]
```

| Say | What happens |
| --- | --- |
| "start studying DBMS" | `start_study`: a timer starts (kept in `D:\Rosie\index\study_session.json`, so a restart doesn't lose it) |
| "done" / "stop studying" | `stop_study`: `- 19:00 DBMS (52 min)` goes to `study-log/2026-11-26.md`. A timer left running is capped at 8 hours |
| "how's my studying?" | `study_report`: minutes per subject over the last 14 days, then the subjects that need attention |

The Command Deck's **+ Study** button and lines you type in Obsidian
(`- 19:00 OS paging (30 min)`) count the same way. A line counts for a subject when it
mentions it as a whole word: "DBMS normal forms" is DBMS, "javascript" is not Java.

A subject **needs attention** when, over the last 14 days, it was:

1. never studied, or
2. last studied a week or more ago, or
3. studied for less than half the average minutes per subject.

Worst first: never-studied subjects, then the longest-neglected.

### Quizzes from your notes

"Quiz me on DBMS" runs `quiz_from_note`: Rosie opens the note in your vault (read only)
and picks out facts written in the usual Obsidian ways:

```markdown
Primary key :: a column that uniquely identifies each row      <- spaced-repetition style
- **1NF**: every column holds a single, atomic value           <- term, colon
- inner join - rows that match in both tables                   <- term, dash
## Normalisation                                                <- heading, then the
Organising tables to reduce redundancy. ...                        first sentence
```

She asks five of them at random ("What is 1NF?"), one at a time, checks each answer
(generously: your words, not the note's) and gives a score. Code blocks, quotes, tables,
checkboxes and long sentences are skipped. A note with no such lines still works: she
writes the questions herself from its text.

## Training coach

Say or type a set the way you'd say it at the gym; spoken numbers work too.

| You say | Logged in `training-log/2026-11-26.md` |
| --- | --- |
| "bench 3x8 at 40 kg" | `- 18:10 Bench press 3x8 @ 40 kg` |
| "squat five by five sixty kilos" | `- 18:20 Squat 5x5 @ 60 kg` |
| "pull ups 3 sets of 10" | `- 18:30 Pull ups 3x10` (bodyweight) |

`log_sets` writes the line and answers with advice when there is some; the Command
Deck's **+ Gym** button uses the same format (anything it can't read, like
"30 min cardio", is kept as you typed it). `training_report` sums up the last 90 days.
Short names work: bench, OHP, DL, RDL.

The rules, one per exercise:

- **Progression**: the same weight for the same sets x reps in two sessions in a row
  means you own it. Next time add 2.5 kg (5 kg for squat, deadlift, leg press).
- **Stall**: the top weight hasn't gone up over the last three sessions, spread over
  two weeks or more. Rosie suggests a deload to 90% (rounded to 2.5 kg) or a new rep range.
