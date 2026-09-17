"""Terminal interface OID tester against snmpsim: presets, truncation, errors, save flows."""

from __future__ import annotations

import pytest
from textual.widgets import Button, DataTable, Input, OptionList, Static

from snowth_my_net.cli import main
from snowth_my_net.config.loader import load_config
from snowth_my_net.tui.app import SaveCollectorModal, SnowthApp, TuiContext
from tests.support.lab import write_config


@pytest.fixture
def collected(lab, tmp_path, capsys):
    cfg = write_config(tmp_path, lab, seeds=[lab.agent("sw-access"), lab.agent("sw-generic")])
    assert main(["--config", str(cfg), "-q", "collect"]) == 0
    capsys.readouterr()
    return cfg


async def settle(app, pilot, rounds: int = 4):
    for _ in range(rounds):
        await pilot.pause()
        await app.workers.wait_for_complete()
    await pilot.pause()


async def open_device(app, pilot, name: str):
    row = next(r for r in app.screen.rows if r.name == name)
    app.push_screen(app.device_screen(row))
    await settle(app, pilot)
    return app.screen


def record_notes(app) -> list[tuple[str, str]]:
    notes: list[tuple[str, str]] = []
    original = app.notify

    def notify(message, *args, severity="information", **kwargs):
        notes.append((str(message), severity))
        return original(message, *args, severity=severity, **kwargs)

    app.notify = notify
    return notes


async def test_presets_truncation_enterprise_and_saving(collected):
    ctx = TuiContext(load_config(collected))
    app = SnowthApp(ctx)
    notes = record_notes(app)
    try:
        async with app.run_test(size=(170, 48)) as pilot:
            await settle(app, pilot)
            device = await open_device(app, pilot, "sw-access-01")
            status = device.query_one("#tester-status", Static)
            save = device.query_one("#save-oid", Button)

            # A preset chosen in the list (OptionList selection), cut by a limit of 1 row.
            device.query_one("#limit", Input).value = "1"
            presets = device.query_one("#presets", OptionList)
            presets.focus()
            presets.highlighted = next(i for i in range(presets.option_count)
                                       if presets.get_option_at_index(i).id == "interfaces")
            await pilot.press("enter")
            await settle(app, pilot)
            text = str(status.render())
            assert text.endswith(f"({app.ctx.t('tester.truncated', limit=1)})")
            assert device.query_one("#results", DataTable).row_count == 1
            assert not save.disabled

            # Saving a table preset proposes a walk collector named after the preset.
            device.save_oid_pressed()
            await settle(app, pilot)
            modal = app.screen
            assert isinstance(modal, SaveCollectorModal)
            assert modal.kind == "walk" and modal.default_name == "interfaces"
            assert modal.vendor == "HPE Aruba" and modal.device_type == "switch"
            await pilot.press("escape")                                   # cancelled
            await settle(app, pilot)
            assert app.screen is device and not any("saved" in n for n, _s in notes)

            # The vendor sub-tree preset cannot be saved (the generic switch has private data).
            await pilot.press("escape")
            await settle(app, pilot)
            device = await open_device(app, pilot, "sw-generic-02")
            status = device.query_one("#tester-status", Static)
            save = device.query_one("#save-oid", Button)
            device.query_one("#limit", Input).value = "5"
            device.run_probe("enterprise")
            await settle(app, pilot)
            assert device.last_probe[3].status == "ok"
            device.save_oid_pressed()
            await settle(app, pilot)
            assert notes[-1] == (app.ctx.t("save.enterprise"), "warning")

            # Without a sysObjectID the vendor sub-tree is unknown: an error with its detail.
            device.connection.system.object_id = ""
            device.run_probe("enterprise")
            await settle(app, pilot)
            assert "unknown vendor sub-tree" in str(status.render())
            assert save.disabled
            device.save_oid_pressed()
            assert notes[-1] == (app.ctx.t("save.nothing"), "warning")
    finally:
        ctx.close()
