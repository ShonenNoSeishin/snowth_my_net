---
name: ui-screenshot
description: Look at the real rendering of the snowth_my_net web UI (light, dark, phone width) with Chromium in Docker. Use for any UI/UX change, a CSS fix, a layout complaint, or before saying a page "looks right".
---

# ui-screenshot

No browser is installed on the host and system libraries are missing, so Chromium runs in the Playwright Docker image. Never claim a visual result without a screenshot.

1. Serve sample data (fixtures from the tests, no real network):
   `.venv/bin/python .claude/skills/ui-screenshot/scripts/serve.py &` (listens on 127.0.0.1:8765, prints `ready`). Stop it with `fuser -k 8765/tcp` (not `pkill -f`, which kills your own shell).
2. Shoot pages (output dir must exist, e.g. the session scratchpad):
   ```
   docker run --rm --network host -e SCHEME=light -v <out>:/out \
     -v $PWD/.claude/skills/ui-screenshot/scripts/shot.py:/shot.py \
     mcr.microsoft.com/playwright/python:v1.49.0-noble \
     sh -c "pip install -q playwright==1.49.0 >/dev/null 2>&1; python /shot.py / /nodes /import"
   ```
   `SCHEME=dark` for the dark theme. It writes `<page>_1440.png` and `<page>_400.png`.
3. Open the PNGs with Read. Check: page title (h1), nothing cut or overlapping at 400 px, contrast in both themes, controls visibly clickable, empty and error states.
4. For a flow (upload, click, submit) write a small Playwright script like `scripts/flow.py` and run it the same way.

Delete old PNGs with `rm -f "${OUT:?}"/*.png` (a bare variable is refused by the safety check).
