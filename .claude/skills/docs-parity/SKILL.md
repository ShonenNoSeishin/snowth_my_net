---
name: docs-parity
description: Keep the English and French docs of snowth_my_net in step so the docs tests pass. Use when adding or changing a command, an option, a config key, a web page or any documented behaviour, or when tests/unit/test_docs*.py fails.
---

# docs-parity

The tests enforce these rules; write the docs to satisfy them the first time.

- Every CLI command, action word and `--option` appears in `docs/en/commands.md` AND `docs/fr/commands.md`. README.md and README.fr.md get a row for a new command.
- Every config key is documented in `docs/en/config.md` and `docs/fr/config.md`, and appears in `src/snowth_my_net/config/example.yml` (commented when off by default).
- Every single-token backticked literal in an EN page must also exist in the FR page (`test_literal_backticked_words_are_kept`). So: identical placeholders and identical file names in both, e.g. `names-import-<time>.csv` in both, never `<heure>`. Translate the prose, not the backticked tokens.
- UI strings live in `src/snowth_my_net/i18n.py` as `"key": ("English", "Français")`; add both.

Check fast: `.venv/bin/pytest -q tests/unit/test_docs.py tests/unit/test_docs_i18n.py tests/unit/test_docs_commands.py`. The failure message names the missing token and the page.
