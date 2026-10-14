"""The Documentation tab: both languages, nothing unescaped, and no key that does not exist."""

from __future__ import annotations

import re

import pytest

from snowth_my_net.config.schema import Config
from snowth_my_net.web import doctext
from tests.unit.test_cov_web_auth import PASSWORD, guarded_config  # noqa: F401
from tests.unit.test_docs import keys

CONFIG_KEYS = set(keys(Config))


def spans(lang_index: int):
    for _key, _title, blocks in doctext.SECTIONS:
        for block in blocks:
            yield from re.findall(r"`([^`]+)`", block[lang_index])


def test_every_block_exists_in_both_languages_and_names_the_same_code():
    for _key, (title_en, title_fr), blocks in doctext.SECTIONS:
        assert title_en and title_fr
        for kind, en, fr in blocks:
            assert kind in ("p", "li") and en and fr
            assert re.findall(r"`([^`]+)`", en) == re.findall(r"`([^`]+)`", fr)


def test_a_documented_configuration_key_is_a_real_one():
    """The tab names `nodes.…` and `export.…` keys: a renamed key must not stay in the text."""
    named = {s.split(":")[0] for s in spans(1)
             if s.startswith(("nodes.", "export.")) and not s.endswith(".csv")}   # a file name
    assert named and named <= CONFIG_KEYS, sorted(named - CONFIG_KEYS)


@pytest.mark.parametrize("lang", ["en", "fr"])
def test_the_page_renders_with_a_table_of_contents_and_escapes_everything(lang, monkeypatch):
    monkeypatch.setattr(doctext, "SECTIONS", (
        ("x", ("<b>t</b>", "<b>t</b>"), (("p", "a <script>1</script> `<i>`", "b <u>"),)),))
    page = doctext.render(lang)
    assert "<script>" not in page and "<b>t</b>" not in page
    assert ("<code>&lt;i&gt;</code>" in page) == (lang == "en")
    assert ("&lt;u&gt;" in page) == (lang == "fr")


@pytest.mark.parametrize("lang", ["en", "fr"])
def test_the_real_page_is_in_the_navigation_and_needs_the_login(lang, tmp_path):
    from snowth_my_net.web.server import Site
    from tests.unit.test_cov_web import FixedClock

    site = Site(guarded_config(tmp_path), FixedClock())
    assert site.respond("/docs", {}, None, lang=lang)[0] == 303          # signed out: login
    token = site.sessions.open("alice")
    status, _type, body = site.respond("/docs", {}, token, lang=lang)
    page = body.decode()
    assert status == 200 and 'href="/docs"' in page and 'class="doctoc"' in page
    assert ("local MAC" in page) if lang == "en" else ("MAC local" in page)
