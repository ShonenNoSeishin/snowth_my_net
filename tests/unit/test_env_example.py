"""``.env.example`` documents every variable the Compose stack and the image use."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
COMPOSE = (ROOT / "compose.yml").read_text(encoding="utf-8")
DOCKERFILE = (ROOT / "Dockerfile").read_text(encoding="utf-8")
EXAMPLE = (ROOT / ".env.example").read_text(encoding="utf-8")

USED = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}")
DOCUMENTED = re.compile(r"^#?\s*([A-Z][A-Z0-9_]*)=(.*)$", re.MULTILINE)


def documented() -> dict[str, str]:
    return {name: value.strip() for name, value in DOCUMENTED.findall(EXAMPLE)}


def test_every_compose_variable_is_documented_with_its_default():
    used = dict(USED.findall(COMPOSE))
    assert set(used) == {"SNOWTH_VERSION", "SNOWTH_UID", "SNOWTH_GID", "TZ",
                         "SNOWTH_COLLECT_ON_START"}
    known = documented()
    assert [name for name in used if name not in known] == []
    mismatched = {name: (default, known[name]) for name, default in used.items()
                  if default and known[name] != default}
    assert mismatched == {}


def test_every_variable_is_commented_out():
    """Copying the file must change nothing until a line is uncommented."""
    active = [line for line in EXAMPLE.splitlines()
              if line.strip() and not line.lstrip().startswith("#")]
    assert active == []


def test_the_paths_baked_into_the_image_are_listed():
    image = dict(re.findall(r"(SNOWTH_[A-Z_]+)=(\S+)", DOCKERFILE))
    assert set(image) == {"SNOWTH_CONFIG", "SNOWTH_STATE_DIR", "SNOWTH_OUTPUT_DIR",
                          "SNOWTH_SECRETS_DIR", "SNOWTH_EXTENSIONS_DIR"}
    known = documented()
    assert [f"{name}={value}" for name, value in image.items()
            if known.get(name) != value] == []
