# Coaches

Rosie coaches study and training from her own logs in rosie-vault. No LLM is needed for
the numbers: plain code reads the notes, and the agent puts the result in words.

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
