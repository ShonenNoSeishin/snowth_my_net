"""The commands page documents every command and every option the program has.

The page is written for a reader who types commands; a command or an option that exists and is
not on it is one nobody finds. The check reads the program's own parser, so adding a command or a
flag fails here until the page, in both languages, says what it does.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

import pytest

from snowth_my_net import cli

ROOT = Path(__file__).resolve().parents[2]
PAGES = {"en": ROOT / "docs" / "en" / "commands.md", "fr": ROOT / "docs" / "fr" / "commands.md"}
GLOBAL = {"--help", "--config", "--state-dir", "--output-dir", "--json", "--log-level",
          "--log-file", "--quiet"}                      # documented once, for every command
ACTIONS = ("show", "dns", "node", "names")              # commands whose action is a word to type


def parser_parts():
    parser = cli.build_parser()
    sub = next(a for a in parser._actions if isinstance(a, argparse._SubParsersAction))
    return sub.choices


def documented(language: str) -> str:
    return PAGES[language].read_text(encoding="utf-8")


@pytest.mark.parametrize("language", PAGES)
def test_every_command_is_on_the_page(language):
    text = documented(language)
    missing = [name for name in parser_parts()
               if not re.search(rf"`{re.escape(name)}[ `]", text)]
    assert missing == []


@pytest.mark.parametrize("language", PAGES)
def test_every_word_of_a_command_that_takes_one_is_on_the_page(language):
    """``show uplinks``, ``dns probe``, ``node reset``, ``names ask``: typed as written."""
    text = documented(language)
    missing = []
    for name in ACTIONS:
        action = next(a for a in parser_parts()[name]._actions
                      if a.dest in ("what", "action") and getattr(a, "choices", None))
        missing += [f"{name} {choice}" for choice in action.choices
                    if f"`{name} {choice}`" not in text]
    assert missing == []


@pytest.mark.parametrize("language", PAGES)
def test_every_option_of_every_command_is_on_the_page(language):
    text = documented(language)
    missing = []
    for name, sub in parser_parts().items():
        for action in sub._actions:
            for flag in action.option_strings:
                if flag.startswith("--") and flag not in GLOBAL and f"`{flag}" not in text:
                    missing.append(f"{name} {flag}")
    assert sorted(set(missing)) == []


@pytest.mark.parametrize("language", PAGES)
def test_the_options_every_command_shares_are_on_the_page(language):
    text = documented(language)
    assert [flag for flag in sorted(GLOBAL - {"--help"}) if f"`{flag}`" not in text] == []
