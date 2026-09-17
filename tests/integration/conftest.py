"""Integration tests run against the snmpsim lab of ``tests/support/lab.py``.

Skipped automatically when snmpsim (and pysmi, which it needs) is not installed.
"""

from __future__ import annotations

import pytest

from tests.support.lab import have_snmpsim, start_lab

HAVE_SNMPSIM = have_snmpsim()


def pytest_collection_modifyitems(config, items):
    if HAVE_SNMPSIM:
        return
    skip = pytest.mark.skip(reason="snmpsim (and pysmi) not installed")
    for item in items:
        if "integration" in str(item.fspath):
            item.add_marker(skip)


@pytest.fixture(scope="session")
def lab(tmp_path_factory):
    if not HAVE_SNMPSIM:
        pytest.skip("snmpsim not installed")
    running = start_lab(tmp_path_factory.mktemp("lab"))
    try:
        yield running
    finally:
        running.stop()
