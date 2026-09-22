"""``explain`` in both languages: same facts, English for the CLI, French in the interface."""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from snowth_my_net.i18n import STRINGS, Translator
from snowth_my_net.merge.explain import explain, explain_node
from snowth_my_net.merge.view import build_view

# a small state built through the repository, with no SNMP
from tests.unit.test_cov_views import MULTI, NOW, A, build_state, make_loaded

EXPLAIN_SOURCE = Path(__file__).resolve().parents[2] / "src" / "snowth_my_net" / "merge" / \
    "explain.py"


def keys_used_by_explain() -> set[str]:
    """Every literal key passed to the translator, including the f-string families."""
    tree = ast.parse(EXPLAIN_SOURCE.read_text(encoding="utf-8"))
    used = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "t":
            first = node.args[0] if node.args else None
            if isinstance(first, ast.Constant) and isinstance(first.value, str):
                used.add(first.value)
            elif isinstance(first, ast.JoinedStr):               # f"xp.excl.{code}"
                prefix = "".join(p.value for p in first.values if isinstance(p, ast.Constant))
                used.add(prefix + "*")
    return used


def test_every_key_used_by_explain_exists():
    missing = []
    for key in sorted(keys_used_by_explain()):
        if key.endswith("*"):
            if not any(k.startswith(key[:-1]) for k in STRINGS):
                missing.append(key)
        elif key not in STRINGS:
            missing.append(key)
    assert missing == []


def test_reason_and_exclusion_codes_are_all_translated():
    """Every code the merge can produce has a text, so no English leaks into French."""
    merge = Path(__file__).resolve().parents[2] / "src" / "snowth_my_net" / "merge"
    sources = (merge / "nodes.py").read_text(), (merge / "topology.py").read_text()
    codes = set()
    for text in sources:
        codes |= set(re.findall(r'append\(\("(\w+)"', text))       # role reasons
        codes |= set(re.findall(r'return PortRole\("access", \(\("(\w+)"', text))
        codes |= set(re.findall(r'hard\.append\(\("(\w+)"', text))
        codes |= set(re.findall(r'return "(\w+)", ', text))        # uplink_reason
    assert codes, "no reason code found: the patterns must follow the merge code"
    assert [c for c in codes if f"xp.reason.{c}" not in STRINGS] == []
    exclusions = set(re.findall(r'Exclusion\("(\w+)"', (merge / "nodes.py").read_text()))
    assert exclusions and [c for c in exclusions if f"xp.excl.{c}" not in STRINGS] == []


@pytest.fixture
def view(tmp_path):
    return build_view(make_loaded(tmp_path), build_state(tmp_path), NOW)


def text_of(view, query, lang):
    return "\n".join(line for line, _kind in explain(view, query, Translator(lang)))


def test_english_text_is_unchanged_and_french_says_the_same(view):
    english = text_of(view, A, "en")
    french = text_of(view, A, "fr")
    assert "Current position :" in english and "Rule             :" in english
    assert "Position actuelle :" in french and "Règle             :" in french
    assert "MAC table sightings" in english and "Observations dans les tables MAC" in french
    assert "ARP sightings" in english and "Observations ARP" in french
    # the facts themselves (MAC, ports, addresses, dates) are identical
    facts = re.compile(r"(?:[0-9a-f]{2}:){5}[0-9a-f]{2}|\d+\.\d+\.\d+\.\d+|\d{4}-\d\d-\d\dT")
    assert facts.findall(english) == facts.findall(french)
    assert "access port" in english and "port d'accès" in french


def test_unknown_mac_and_exclusion_are_translated(view):
    assert "not seen in any MAC or ARP table" in text_of(view, "02:00:00:00:00:99", "en")
    assert "vue dans aucune table MAC ou ARP" in text_of(view, "02:00:00:00:00:99", "fr")
    excluded = next(n for n in (view.find(MULTI) or []) if n.excluded)
    lines = [line for line, kind in explain_node(view, excluded, Translator("fr"))
             if kind == "bad"]
    assert lines and lines[0] == "Pas un nœud : adresse multicast ou broadcast"
