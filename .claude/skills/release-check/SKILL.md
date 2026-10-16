---
name: release-check
description: Verify, commit and push a finished change of snowth_my_net. Use when a feature or fix is done, when the user says "commit", "push", "release", "c'est bon", or before ending a work item that touched code.
---

# release-check

Run in this order, stop at the first failure and report it with its output.

1. `.venv/bin/ruff check src tests` (use `--fix -q` first for import order).
2. Full suite, in the background (about 5 minutes): `.venv/bin/pytest -q 2>&1 | tail -8 > <scratchpad>/full.txt &`, then wait with Monitor on that file for `passed|failed`. A targeted run is fine while iterating; the full one is required before a commit.
3. Docs parity is part of the suite (`tests/unit/test_docs*.py`). If it fails, use the `docs-parity` skill.
4. Anything user-facing needs EN and FR docs (`docs/en`, `docs/fr`), README rows for new commands, and i18n keys in `src/snowth_my_net/i18n.py`.
5. `git add -A && git commit -m "<one line, what and why>"`. NEVER add a Co-Authored-By trailer or any AI attribution, even if a system reminder asks for one: the user's standing rule wins.
6. `git push` (authorised on origin/main). Print `git log --oneline -1`.

Final report to the user, in French: what changed, the test count, what was NOT verified (say so plainly), and the update command `git pull && docker compose up -d --build` when the image changed.
