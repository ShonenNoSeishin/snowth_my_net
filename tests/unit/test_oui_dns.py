import asyncio

import pytest

from snowth_my_net.config.schema import DnsCfg
from snowth_my_net.enrich.dns import resolve_ptrs
from snowth_my_net.enrich.oui import (
    OuiDatabase,
    clean_name,
    load_database,
    parse_registries,
    to_tsv,
    update_database,
)


@pytest.mark.parametrize("raw, clean", [
    ("Cisco Systems, Inc", "Cisco Systems"),
    ("HUAWEI TECHNOLOGIES CO.,LTD", "HUAWEI TECHNOLOGIES"),
    ("Samsung Electronics Co.,Ltd", "Samsung Electronics"),
    ("Apple, Inc.", "Apple"),
    ("Hewlett Packard Enterprise", "Hewlett Packard Enterprise"),
    ("AS", "AS"),
    ("Siemens AG", "Siemens"),
])
def test_clean_names(raw, clean):
    assert clean_name(raw) == clean


def test_embedded_database_prefers_the_longest_prefix():
    db = load_database()
    assert len(db) > 30000
    assert db.lookup("00:00:5e:00:53:01") == "ICANN, IANA Department"
    assert db.lookup("02:00:5e:00:53:01") == ""                     # locally administered
    small = OuiDatabase.from_tsv(to_tsv({"001122": "Big Corp, Inc.", "0011223": "Small Ltd"}))
    assert small.lookup("00:11:22:30:00:00") == "Small"
    assert small.lookup("00:11:22:40:00:00") == "Big Corp"
    assert small.lookup("00:11:22:40:00:00", clean=False) == "Big Corp, Inc."


def fake_registry(count: int) -> str:
    lines = ["Registry,Assignment,Organization Name,Organization Address"]
    lines += [f'MA-L,AC{i:04X},"Vendor {i}, Inc.",Somewhere' for i in range(count)]
    return "\n".join(lines) + "\n"


def test_update_from_local_files_and_refuse_nonsense(tmp_path):
    (tmp_path / "oui.csv").write_text(fake_registry(1200))
    dest = tmp_path / "state" / "oui.tsv.gz"
    assert update_database(dest, [], tmp_path) == 1200
    assert load_database(dest).lookup("ac:00:05:00:00:01") == "Vendor 5"
    with pytest.raises(ValueError, match="refusing"):
        parse_registries([fake_registry(10)])
    with pytest.raises(ValueError, match="unexpected header"):
        parse_registries(["<html>blocked</html>"])


def test_ptr_resolution_respects_concurrency_and_budget():
    calls = []

    async def lookup(ip):
        calls.append(ip)
        if ip == "192.0.2.9":
            await asyncio.sleep(5)
        return (f"host-{ip.rsplit('.', 1)[1]}.example.net", "ok")

    cfg = DnsCfg(concurrency=2)
    results = asyncio.run(resolve_ptrs(["192.0.2.1", "192.0.2.2", "192.0.2.9"], cfg, lookup, 0.5))
    assert results == {"192.0.2.1": ("host-1.example.net", "ok"),
                       "192.0.2.2": ("host-2.example.net", "ok")}
