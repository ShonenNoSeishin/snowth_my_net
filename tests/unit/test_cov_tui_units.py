"""Terminal interface, Textual-free parts: translations, device rows, form changes, helpers."""

from __future__ import annotations

import ast
import logging
import re
from pathlib import Path

import pytest

from snowth_my_net.config.loader import load_config
from snowth_my_net.config.manual import ManualError
from snowth_my_net.state.db import open_db
from snowth_my_net.state.repo import Repo
from snowth_my_net.tui import app as tui_app
from snowth_my_net.tui import i18n
from snowth_my_net.tui.data import DeviceRow, _sort_key, list_devices, plan_form_change

TUI = Path(tui_app.__file__).resolve().parent
NOW = 1_790_000_000


def write_cfg(tmp_path: Path, extra: str = "") -> Path:
    cfg = tmp_path / "snowth_my_net.yml"
    cfg.write_text(f"""
general:
  state_dir: {tmp_path / 'state'}
  output_dir: {tmp_path / 'out'}
  secrets_dir: {tmp_path / 'secrets'}
  language: en
dns:
  enabled: false
{extra}""")
    return cfg


# --------------------------------------------------------------------------- translations


def test_every_string_has_an_english_and_a_french_text():
    for key, texts in i18n.STRINGS.items():
        assert isinstance(texts, tuple) and len(texts) == 2, key
        english, french = texts
        assert english.strip() and french.strip(), key
        # the same placeholders in both languages
        assert set(re.findall(r"\{(\w+)\}", english)) == set(re.findall(r"\{(\w+)\}", french)), key


def _literal_keys() -> set[str]:
    keys: set[str] = set()
    for path in TUI.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not node.args:
                continue
            func = node.func
            name = func.id if isinstance(func, ast.Name) else (
                func.attr if isinstance(func, ast.Attribute) else "")
            if name != "t" and not (isinstance(func, ast.Attribute) and func.attr == "t"):
                continue
            first = node.args[0]
            if isinstance(first, ast.Constant) and isinstance(first.value, str):
                keys.add(first.value)
    # keys passed as data (labels of columns, bindings, …)
    for path in TUI.glob("*.py"):
        for match in re.finditer(r'"((?:col|key|last|id|set|rep|ext|tab|save|tester|collect|'
                                 r'remote|role|feat|mode|src|op|st|type|custom|neighbors)'
                                 r'\.[a-z_]+)"', path.read_text(encoding="utf-8")):
            keys.add(match.group(1))
    return keys


def test_every_key_used_by_the_interface_exists():
    used = _literal_keys()
    assert len(used) > 100
    assert sorted(k for k in used if k not in i18n.STRINGS) == []


def test_dynamic_key_families_are_complete():
    from snowth_my_net.config.effective import FEATURES
    from snowth_my_net.tui.reports import OPS

    wanted = ([f"type.{t}" for t in tui_app.DEVICE_TYPES]
              + [f"st.{s}" for s in tui_app.STATUS_STYLE]
              + [f"src.{s}" for s in ("manual", "config", "default")]
              + [f"mode.{m}" for m in ("auto", "force", "off")]
              + [f"feat.{f}" for f in FEATURES]
              + [f"role.{r}" for r in ("access", "uplink")]
              + [f"op.{o}" for o in OPS])
    assert [k for k in wanted if k not in i18n.STRINGS] == []


def test_language_detection(monkeypatch):
    for var in ("LC_ALL", "LC_MESSAGES", "LANG"):
        monkeypatch.delenv(var, raising=False)
    assert i18n.detect_language("fr") == "fr" and i18n.detect_language("en") == "en"
    assert i18n.detect_language("auto") == "en"
    monkeypatch.setenv("LANG", "fr_BE.UTF-8")
    assert i18n.detect_language() == "fr"
    monkeypatch.setenv("LC_ALL", "C.UTF-8")
    assert i18n.detect_language() == "en"                    # LC_ALL wins over LANG


def test_translator_formats_and_switches_language():
    en, fr = i18n.Translator("en"), i18n.Translator("fr")
    assert en("tab.devices") == "Devices" and fr("tab.devices") == "Équipements"
    assert fr("add.done", target="192.0.2.1") == "192.0.2.1 ajouté"
    with pytest.raises(KeyError):
        en("no.such.key")


# --------------------------------------------------------------------------- device rows


def row(**kw) -> DeviceRow:
    base = dict(target="192.0.2.1", host="192.0.2.1", device_id=1, name="sw1",
                device_type="switch", type_rule="catalog", vendor="Acme", model="X1",
                status="ok", last_seen=NOW, error="")
    return DeviceRow(**(base | kw))


def test_type_marks_and_search():
    assert row(device_type="").type_mark == "?"
    assert row(type_rule="manual").type_mark == "✎"
    assert row(type_rule="config").type_mark == "⚙"
    assert row().type_mark == ""
    r = row()
    assert r.matches("") and r.matches("  ACME ") and r.matches("192.0.2") and r.matches("ok")
    assert not r.matches("firewall")


def test_rows_sort_by_name_then_address_and_tolerate_names():
    rows = [row(name="b", host="192.0.2.10"), row(name="a", host="host.example"),
            row(name="b", host="192.0.2.9"), row(name="b", host="2001:db8::1")]
    ordered = sorted(rows, key=_sort_key)
    assert [(r.name, r.host) for r in ordered] == [
        ("a", "host.example"), ("b", "192.0.2.9"), ("b", "192.0.2.10"), ("b", "2001:db8::1")]


def test_list_devices_merges_polled_devices_and_pending_targets(tmp_path):
    cfg = write_cfg(tmp_path, "devices:\n  - address: 192.0.2.30\n    type: printer\n"
                              "    name: config-name\n")
    loaded = load_config(cfg)
    conn = open_db(loaded.paths.state_file)
    repo = Repo(conn)
    conn.execute("INSERT INTO devices(mgmt_address, sys_name, device_type, type_rule, vendor, "
                 "first_seen, last_seen, last_collect_status) VALUES "
                 "('192.0.2.1:1161', 'sw-a.example', 'switch', 'catalog', 'Acme', ?, ?, 'weird')",
                 (NOW, NOW))
    conn.commit()
    repo.ensure_target("192.0.2.1:1161", "seed", 0, NOW)
    conn.execute("UPDATE targets SET device_id = 1 WHERE address = '192.0.2.1:1161'")
    repo.ensure_target("192.0.2.20", "manual", 0, NOW)
    repo.target_failed("192.0.2.20", NOW, "no answer")
    repo.ensure_target("192.0.2.30", "seed", 0, NOW)
    repo.ensure_target("192.0.2.40", "state", 0, NOW)
    conn.execute("UPDATE targets SET is_alias = 1 WHERE address = '192.0.2.40'")
    conn.commit()
    rows = {r.target: r for r in list_devices(loaded, repo, NOW)}
    conn.close()
    assert set(rows) == {"192.0.2.1:1161", "192.0.2.20", "192.0.2.30"}
    polled = rows["192.0.2.1:1161"]
    assert (polled.host, polled.name, polled.status, polled.device_id) == (
        "192.0.2.1", "sw-a", "never", 1)
    failed = rows["192.0.2.20"]
    assert (failed.status, failed.error, failed.name, failed.device_id) == (
        "failed", "no answer", "192.0.2.20", None)
    declared = rows["192.0.2.30"]
    assert (declared.name, declared.device_type, declared.type_rule, declared.status) == (
        "config-name", "printer", "config", "never")


def test_plan_form_change(tmp_path):
    loaded = load_config(write_cfg(tmp_path, "devices:\n  - address: 192.0.2.1\n"
                                             "    type: switch\n"))
    host = "192.0.2.1"
    manual = {host: {"name": "old", "snmp.pace_ms": 50, "type": "router"}}
    change = plan_form_change(loaded, host, manual, {
        "type": "switch",               # equal to config.yml: back to the baseline
        "name": None,                   # automatic: removes the manual name
        "credential": "",               # nothing stored, nothing to do
        "snmp.pace_ms": 50,             # unchanged manual value
        "snmp.max_repetitions": 10,     # new manual value
        "features.fdb": "auto",         # equal to the default
    })
    assert change.to_set == {"snmp.max_repetitions": 10}
    assert sorted(change.to_unset) == ["name", "type"]
    assert not change.empty
    assert plan_form_change(loaded, host, {}, {"features.fdb": "auto"}).empty
    with pytest.raises(ManualError):
        plan_form_change(loaded, host, {}, {"snmp.max_repetitions": -5})


# --------------------------------------------------------------------------- helpers


def test_context_times_status_and_credentials(tmp_path, monkeypatch):
    from datetime import datetime

    loaded = load_config(write_cfg(tmp_path, """
credentials:
  - name: missing
    version: 2c
    community_file: nowhere
"""))
    ctx = tui_app.TuiContext(loaded)
    try:
        assert ctx.credentials == [] and "nowhere" in ctx.credentials_error
        assert ctx.local_time(None) == "—" and ctx.local_time_iso("") == "—"
        today = int(datetime.now().replace(hour=9, minute=5, second=0).timestamp())
        assert ctx.local_time(today) == "09:05"
        assert ctx.local_time(int(datetime(2020, 3, 4, 7, 8).timestamp())) == "04/03 07:08"
        assert ctx.local_time_iso("2020-03-04T07:08:00Z") == ctx.local_time(1583305680)
        ok = ctx.status_text("ok")
        assert str(ok) == f"● {ctx.t('st.ok')}" and ok.style == "green"
        assert str(ctx.status_text("never")).startswith("○")
        assert ctx.type_label("") == "" and ctx.type_label("switch") == ctx.t("type.switch")
    finally:
        ctx.close()


def test_scope_text_and_collector_definition():
    from snowth_my_net.config.extensions import parse_collector

    t = i18n.Translator("en")
    everywhere = parse_collector({"name": "a", "get": {"v": "1.3.6.1.2.1.1.5.0"}})
    assert tui_app.scope_text(everywhere, t) == t("ext.all")
    scoped = parse_collector({"name": "b", "get": {"v": "1.3.6.1.2.1.1.5.0"}, "applies_to": {
        "vendors": ["Acme"], "types": ["switch"], "addresses": ["192.0.2.0/24"],
        "sys_object_ids": ["1.3.6.1.4.1.9"]}})
    assert tui_app.scope_text(scoped, t) == (
        f"Acme · {t('type.switch')} · 192.0.2.0/24 · 1.3.6.1.4.1.9")
    import dataclasses

    cleaned = tui_app._definition(dataclasses.asdict(scoped))
    assert cleaned == {"name": "b", "applies_to": {
        "vendors": ["Acme"], "types": ["switch"], "addresses": ["192.0.2.0/24"],
        "sys_object_ids": ["1.3.6.1.4.1.9"]}, "get": {"v": "1.3.6.1.2.1.1.5.0"}}


def test_log_handler_never_raises():
    class Broken:
        def write(self, _text):
            raise RuntimeError("widget gone")

    handler = tui_app.TuiLogHandler(Broken())
    errors = []
    handler.handleError = errors.append
    record = logging.LogRecord("snowth_my_net", logging.WARNING, __file__, 1, "msg", (), None)
    handler.emit(record)
    assert errors == [record]

    written = []

    class Widget:
        def write(self, text):
            written.append(text)

    tui_app.TuiLogHandler(Widget()).emit(record)
    assert written and str(written[0]).endswith("msg") and written[0].style == "yellow"


def test_check_action_before_mount_hides_report_actions(tmp_path):
    ctx = tui_app.TuiContext(load_config(write_cfg(tmp_path)))
    try:
        screen = tui_app.MainScreen(ctx)
        assert screen.check_action("new_report", ()) is False
        assert screen.check_action("refresh", ()) is True
    finally:
        ctx.close()


def test_run_tui_closes_the_state(tmp_path, monkeypatch):
    ran = []
    monkeypatch.setattr(tui_app.SnowthApp, "run", lambda self: ran.append(self.ctx))
    assert tui_app.run_tui(load_config(write_cfg(tmp_path))) == 0
    ctx = ran[0]
    with pytest.raises(Exception, match="closed"):
        ctx.conn.execute("SELECT 1")

    def boom(self):
        raise RuntimeError("terminal lost")

    monkeypatch.setattr(tui_app.SnowthApp, "run", boom)
    with pytest.raises(RuntimeError):
        tui_app.run_tui(load_config(write_cfg(tmp_path)))
