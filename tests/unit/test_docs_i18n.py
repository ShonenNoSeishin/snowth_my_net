"""The French and English documentation stay in step, and no link is broken."""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path

import pytest

from snowth_my_net.config.schema import Config
from tests.unit.test_docs import keys

ROOT = Path(__file__).resolve().parents[2]
EN, FR = ROOT / "docs" / "en", ROOT / "docs" / "fr"
PAGES = sorted(p.name for p in EN.glob("*.md"))
MARKDOWN = [ROOT / "README.md", ROOT / "README.fr.md", *sorted(EN.glob("*.md")),
            *sorted(FR.glob("*.md"))]
FENCE = re.compile(r"^```(\w*)", re.MULTILINE)
LINK = re.compile(r"(?<!!)\[[^\]]*\]\(([^)\s]+)\)")


def test_same_pages_in_both_languages():
    assert PAGES
    assert sorted(p.name for p in FR.glob("*.md")) == PAGES


def structure(text: str) -> dict:
    lines = text.splitlines()
    return {
        "code_blocks": FENCE.findall(text)[::2],            # opening fences with their language
        "table_rows": sum(1 for line in lines if line.startswith("|")),
        "headings": [len(m.group(1)) for m in re.finditer(r"^(#+) ", text, re.MULTILINE)],
    }


@pytest.mark.parametrize("page", PAGES)
def test_same_structure(page):
    en, fr = (EN / page).read_text(encoding="utf-8"), (FR / page).read_text(encoding="utf-8")
    assert structure(fr) == structure(en)


@pytest.mark.parametrize("page", PAGES)
def test_literal_backticked_words_are_kept(page):
    """Keys, commands and values in backticks must survive the translation."""
    def literals(text):
        outside_code = re.sub(r"```.*?```", "", text, flags=re.DOTALL)
        return {w for w in re.findall(r"`([^`\n]+)`", outside_code)
                if re.fullmatch(r"[\w./:{}\[\]<>@*=-]+", w)}
    en = literals((EN / page).read_text(encoding="utf-8"))
    fr = literals((FR / page).read_text(encoding="utf-8"))
    assert en - fr == set()


def test_every_configuration_key_is_documented_in_french():
    text = (FR / "config.md").read_text(encoding="utf-8")
    assert [k for k in keys(Config) if f"`{k}`" not in text] == []


def anchor(heading: str) -> str:
    """GitHub heading anchors: lowercase, punctuation removed, spaces to dashes."""
    text = heading.strip().lower()
    text = "".join(ch for ch in text if ch.isalnum() or ch in " -_"
                   or unicodedata.category(ch).startswith("L"))
    return text.replace(" ", "-")


def anchors(path: Path) -> set[str]:
    text = re.sub(r"```.*?```", "", path.read_text(encoding="utf-8"), flags=re.DOTALL)
    return {anchor(m.group(1)) for m in re.finditer(r"^#+ (.+)$", text, re.MULTILINE)}


@pytest.mark.parametrize("path", MARKDOWN, ids=lambda p: str(p.relative_to(ROOT)))
def test_relative_links_resolve(path):
    broken = []
    text = re.sub(r"```.*?```", "", path.read_text(encoding="utf-8"), flags=re.DOTALL)
    for target in LINK.findall(text):
        if re.match(r"^[a-z]+:", target):
            continue                                   # external URL
        file_part, _, fragment = target.partition("#")
        resolved = (path.parent / file_part).resolve() if file_part else path
        if not resolved.exists():
            broken.append(f"{target}: no such file")
        elif fragment and resolved.suffix == ".md" and fragment not in anchors(resolved):
            broken.append(f"{target}: no heading with this anchor")
    assert broken == []


def test_readmes_point_to_their_language():
    assert "docs/fr/" not in (ROOT / "README.md").read_text(encoding="utf-8").split(
        "## Documentation")[1].split("\n* ")[1]
    assert all("docs/fr/" in line for line in (ROOT / "README.fr.md").read_text(
        encoding="utf-8").splitlines() if line.startswith("* [") and "docs/" in line)
