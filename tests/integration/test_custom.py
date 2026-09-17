"""Custom collectors (E1) against snmpsim."""

from __future__ import annotations

import json

from snowth_my_net.cli import main
from tests.support.lab import write_config

GENERIC_EXT = """
collectors:
  - name: generic-system
    description: firmware and temperature of the unknown-vendor switch
    applies_to: {sys_object_ids: [1.3.6.1.4.1.99999.1]}
    get:
      firmware: {oid: 1.3.6.1.4.1.99999.1.7.1.1.0, type: text}
      temperature: {oid: 1.3.6.1.4.1.99999.1.7.1.2.0, type: integer, scale: 0.1, unit: °C}
    fills: {os_version: firmware}
  - name: poe
    applies_to: {types: [switch]}
    walk:
      columns:
        detection: {oid: 1.3.6.1.2.1.105.1.1.1.6, type: enum, values: {2: searching, 3: delivering}}
"""


def run_json(capsys, *argv):
    code = main(["--json", *argv])
    return code, json.loads(capsys.readouterr().out)


def generic(report):
    return next(d for d in report["devices"] if d["sys_name"] == "sw-generic-02")


def lab_with_extension(lab, tmp_path, text=GENERIC_EXT, **kwargs):
    cfg = write_config(tmp_path, lab, seeds=[lab.agent("sw-generic")], **kwargs)
    (tmp_path / "extensions").mkdir(exist_ok=True)
    (tmp_path / "extensions" / "generic.yml").write_text(text)
    return cfg


def test_file_collectors_are_read_stored_and_fill_standard_fields(lab, tmp_path, capsys):
    cfg = lab_with_extension(lab, tmp_path, extra_devices=(
        "  - address: 127.0.0.12\n    type: switch\n"), files="[devices, snapshot]")
    code, report = run_json(capsys, "--config", str(cfg), "collect")
    assert code == 0, report
    device = generic(report)
    assert device["os_version"] == "2.4.1-build77"

    code, shown = run_json(capsys, "--config", str(cfg), "custom", "show", "127.0.0.12")
    system = shown["collectors"]["generic-system"]
    assert system["status"] == "ok"
    assert system["values"] == {"firmware": "2.4.1-build77", "temperature": "45.2 °C"}
    poe = shown["collectors"]["poe"]
    assert ["1.1", "detection", "delivering"] in poe["table"] and len(poe["table"]) == 4

    assert main(["--config", str(cfg), "-q", "export"]) == 0
    capsys.readouterr()
    line = next(line for line in (tmp_path / "out" / "devices.csv").read_text().splitlines()
                if line.startswith("sw-generic-02"))
    assert ",2.4.1-build77," in line
    snapshot = json.loads((tmp_path / "out" / "snapshot.json").read_text())
    snap_device = next(d for d in snapshot["devices"] if d["name"] == "sw-generic-02")
    assert snap_device["custom"]["poe"]["table"][0]["value"] in ("searching", "delivering")


def test_type_fill_and_every(lab, tmp_path, capsys):
    ext = GENERIC_EXT.replace("fills: {os_version: firmware}",
                              "fills: {os_version: firmware}\n    every: 1h") \
        + "  - name: kind\n    applies_to: {sys_object_ids: [1.3.6.1.4.1.99999.1.7]}\n" \
          "    get: {kind: 1.3.6.1.2.1.1.5.0}\n    fills: {device_type: kind}\n"
    cfg = lab_with_extension(lab, tmp_path, ext)
    assert main(["--config", str(cfg), "-q", "collect"]) == 0
    capsys.readouterr()
    _code, report = run_json(capsys, "--config", str(cfg), "collect")
    device = generic(report)
    assert device["os_version"] == "2.4.1-build77"          # filled from the stored pass
    assert "custom:generic-system" not in device["functions"]
    assert any("not a device type" in w for w in device["warnings"])


def test_custom_test_list_import_delete(lab, tmp_path, capsys):
    cfg = lab_with_extension(lab, tmp_path)
    code, result = run_json(capsys, "--config", str(cfg), "custom", "test", "generic-system",
                            lab.agent("sw-generic"))
    assert code == 0 and ["", "temperature", "45.2 °C"] in result["rows"]

    (tmp_path / "import.yml").write_text(
        "collectors:\n  - {name: contact, get: {contact: 1.3.6.1.2.1.1.6.0}}\n")
    assert main(["--config", str(cfg), "custom", "import", str(tmp_path / "import.yml")]) == 0
    capsys.readouterr()
    _code, listed = run_json(capsys, "--config", str(cfg), "custom", "list")
    assert {(c["name"], c["origin"] == "tui") for c in listed} == {
        ("generic-system", False), ("poe", False), ("contact", True)}
    assert main(["--config", str(cfg), "-q", "collect"]) == 0
    capsys.readouterr()
    _code, shown = run_json(capsys, "--config", str(cfg), "custom", "show", "127.0.0.12")
    assert shown["collectors"]["contact"]["values"] == {"contact": "Building B"}
    assert main(["--config", str(cfg), "custom", "delete", "generic-system"]) == 2
    assert main(["--config", str(cfg), "custom", "delete", "contact"]) == 0
    capsys.readouterr()


def test_forced_collector_without_data_is_a_partial_failure(lab, tmp_path, capsys):
    ext = "collectors:\n  - {name: nothing, mode: force, get: {x: 1.3.6.1.4.1.99999.9.9.0}}\n"
    cfg = lab_with_extension(lab, tmp_path, ext)
    code, report = run_json(capsys, "--config", str(cfg), "collect")
    assert code == 1 and generic(report)["status"] == "partial"


def test_check_reports_collectors_and_invalid_files_exit_2(lab, tmp_path, capsys):
    cfg = lab_with_extension(lab, tmp_path)
    _code, result = run_json(capsys, "--config", str(cfg), "check", "--quick")
    mibs = next(d for d in result["devices"] if d["sys_name"] == "sw-generic-02")["mibs"]
    assert mibs["custom:generic-system"] == "ok(2)"
    assert "custom:poe" not in mibs                    # applies to switches; type is empty
    (tmp_path / "extensions" / "broken.yml").write_text("collectors: [{name: X}]\n")
    assert main(["--config", str(cfg), "collect"]) == 2
