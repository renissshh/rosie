# Working on Rosie

Owner: renissshh (MCA student, Windows laptop, data drive D:). Rosie is his personal assistant
and a portfolio project, so code must be clear enough for him to explain in an interview.

## Non-negotiables
- Follow `docs/PLAN.md`. Take the first unchecked item; tick it when done.
- Branch `dev` for work; `main` only receives sprint merges with a `v0.N` tag.
- Every commit is one real unit with tests. Run before each commit:
  `ruff format . && ruff check . && python -m pytest -q`
- Conventional Commits: `feat(scope): ...`, `fix`, `test`, `docs`, `ci`, `chore`.
- Windows first: use `pathlib`, no shell-only tricks, test on the CI Windows runner.
- Runtime data defaults to `D:\Rosie`. Never write to the user's own Obsidian vault;
  only `rosie-vault`.
- Never commit secrets. Keys are referenced by env var name (`api_key_env`), never stored.
- LLM must stay free to run: local Ollama first, free-tier cloud only as fallback.
- Only copy code from MIT/Apache-2.0 projects, and record it in `CREDITS.md`.

## End of every night
Write `docs/devlog/YYYY-MM-DD.md` with: Done, Commits, Blocked, Needs you, Next.
Keep "Needs you" short: the user has exams until Dec 23, 2026.
