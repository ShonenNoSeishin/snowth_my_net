"""Sorting a table by a column the reader writes in (the manual hostname, the description).

The script that sorts cannot run here, so the two facts it depends on are held: the cell's
form starts with hidden inputs (the MAC, the field), and the script reads the visible one by
name — reading "the first input with a name" sorted the column by MAC address.
"""

from __future__ import annotations

import re
from importlib import resources

from snowth_my_net.web.pages import Editable
from snowth_my_net.web.server import Site
from tests.unit.test_cov_views import make_loaded
from tests.unit.test_cov_web import FixedClock


def test_an_editable_cell_starts_with_hidden_inputs_so_the_script_must_name_the_visible_one(
        tmp_path):
    site = Site(make_loaded(tmp_path), FixedClock())
    html = site.name_field(Editable("poste-julie", "00:00:5e:00:53:d0", "name"), site.t)
    inputs = re.findall(r"<input[^>]*>", html)
    assert 'type="hidden"' in inputs[0] and 'name="mac"' in inputs[0]
    assert 'name="name"' in inputs[-1] and "hidden" not in inputs[-1]


def test_the_script_reads_the_written_value_not_the_first_named_input():
    script = resources.files("snowth_my_net.web.assets").joinpath("app.js").read_text("utf-8")
    assert "input[name=name]" in script
    assert "input[name]" not in script
