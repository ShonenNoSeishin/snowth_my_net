"""Names given by hand to MAC addresses: "imprimante compta", "poste de Julie".

A name belongs to the MAC, not to a row: positions move, IP addresses change, a collect
rewrites everything it read — the name stays. It lives in its own file next to the state
rather than in the database, so that a lost state, a schema upgrade or a fresh start never
takes the names with it, and so that the read-only interface can write them without ever
touching what the collector owns.
"""

from __future__ import annotations

import csv
import io
import json
import os
import stat
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from snowth_my_net.export.csvout import formula_safe
from snowth_my_net.snmp.values import normalize_mac

STORE_NAME = "node_names.json"
FORMAT = 2                                       # 1 held a bare name; 2 holds the fields below
FIELDS = ("name", "description")
MAX_LENGTH = {"name": 60, "description": 200}    # a label, and a line about it


class NameError_(ValueError):
    """What is wrong with a name or a MAC, in a sentence meant for the reader."""


def clean_field(field: str, text: str) -> str:
    """One line, trimmed, no control character: it is rendered in a table cell."""
    if field not in FIELDS:
        raise NameError_(f"unknown field {field!r}; it is one of {', '.join(FIELDS)}")
    value = " ".join(str(text).split())
    value = "".join(c for c in value if unicodedata.category(c)[0] != "C")   # ESC, BEL, NUL…
    if len(value) > MAX_LENGTH[field]:
        raise NameError_(f"a {field} is at most {MAX_LENGTH[field]} characters")
    return value


def clean_mac(value: str) -> str:
    mac = normalize_mac(value)
    if mac is None:
        raise NameError_(f"{value!r} is not a MAC address")
    return mac


class Names:
    """``{mac: {field: value}}``. Reads never raise; writes replace the file atomically."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def read(self) -> dict[str, dict[str, str]]:
        """``{mac: {"name": …, "description": …}}``. A file written by an older version held
        the name alone; it is read as such and rewritten in the richer shape on the next
        change, so an upgrade never loses a name."""
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            names = data["names"]
        except (OSError, ValueError, KeyError, TypeError):
            return {}
        if not isinstance(names, dict):
            return {}
        found = {}
        for mac, entry in names.items():                     # JSON keys are always strings
            if isinstance(entry, str):                       # the shape of version 1
                entry = {"name": entry}
            if not isinstance(entry, dict):
                continue
            kept = {f: entry[f] for f in FIELDS
                    if isinstance(entry.get(f), str) and entry[f]}
            if kept:
                found[mac] = kept
        return found

    def get(self, mac: str, field: str = "name") -> str:
        return self.read().get(mac, {}).get(field, "")

    def set(self, mac: str, value: str, field: str = "name") -> str:
        """Set one field of a MAC, or forget it when the value is empty."""
        mac, value = clean_mac(mac), clean_field(field, value)
        names = self.read()
        entry = dict(names.get(mac, {}))
        if value:
            entry[field] = value
        else:
            entry.pop(field, None)
        if entry:
            names[mac] = entry
        else:
            names.pop(mac, None)                             # nothing left to remember
        self._write(names)
        return value

    def set_many(self, given: dict[str, str], field: str = "name") -> None:
        """Set one field of many MACs in one atomic write (values already cleaned)."""
        names = self.read()
        for mac, value in given.items():
            entry = dict(names.get(mac, {}))
            entry[field] = value
            names[mac] = entry
        self._write(names)

    def _write(self, names: dict[str, dict[str, str]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_name(self.path.name + ".new")
        text = json.dumps({"version": FORMAT, "names": names}, indent=2, sort_keys=True,
                          ensure_ascii=False) + "\n"
        fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC,
                     stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as out:
                out.write(text)
                out.flush()
                os.fsync(out.fileno())
            os.replace(temp, self.path)
        except BaseException:
            temp.unlink(missing_ok=True)
            raise


def store_for(paths) -> Names:
    """The store of a loaded configuration (``loaded.paths``)."""
    return Names(paths.state_dir / STORE_NAME)


# ---------------------------------------------------------------------- bulk import

MAX_IMPORT_ROWS = 5000
MAX_IMPORT_BYTES = 1024 * 1024
HEADERS = ("mac", "mac address", "adresse mac")
ADDED, UPDATED, UNCHANGED, SKIPPED, ERROR = "added", "updated", "unchanged", "skipped", "error"
RESULTS = (ERROR, UPDATED, ADDED, SKIPPED, UNCHANGED)   # the order a reader wants them in


@dataclass(frozen=True)
class ImportLine:
    line: int
    mac: str
    name: str
    result: str          # one of RESULTS
    detail: str
    before: str = ""     # the name this MAC had


def template(nodes: list[tuple[str, str, str, str]]) -> str:
    """The CSV to fill in: every node the network has shown, with the name it has (empty when
    none). ``nodes`` is ``(mac, name, address, vendor)``; the last two are there to help
    whoever fills the file and are not read back. With no node yet, an example is commented."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\r\n")
    writer.writerow(["mac", "name", "ip", "vendor"])
    for mac, name, address, vendor in sorted(nodes):
        writer.writerow([mac, formula_safe(name), address, formula_safe(vendor)])
    if not nodes:
        buffer.write("# 00:11:22:33:44:55,printer accounting\r\n")
    return buffer.getvalue()


def _rows(text: str) -> list[tuple[int, list[str]]]:
    """``(line number, cells)`` of the non-empty, non-comment lines. The separator is the one
    the first line uses (a spreadsheet in French writes ``;``)."""
    text = text.lstrip("\ufeff")
    first = next((ln for ln in text.splitlines() if ln.strip() and not ln.startswith("#")), "")
    delimiter = max(",;\t", key=first.count) if any(c in first for c in ",;\t") else ","
    rows = []
    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    for cells in reader:
        if not cells or not "".join(cells).strip() or cells[0].lstrip().startswith("#"):
            continue
        rows.append((reader.line_num, cells))
    return rows


def plan_import(current: dict[str, dict[str, str]], text: str,
                known: set[str]) -> tuple[list[ImportLine], dict[str, str]]:
    """What a two-column CSV (MAC, name) would do, and the names to write for it.

    A MAC that already has a name is updated, any other is added (``known`` tells whether the
    network has shown it yet, which the detail says). A line with no name changes nothing, a
    repeated MAC keeps its first line, a bad line is reported and skipped. Nothing is written.
    """
    rows = _rows(text)
    if rows and rows[0][1][0].strip().lower() in HEADERS:    # a header: mac,name
        rows = rows[1:]
    if len(rows) > MAX_IMPORT_ROWS:
        raise NameError_(f"at most {MAX_IMPORT_ROWS} lines at a time, this file has {len(rows)}")
    out: list[ImportLine] = []
    todo: dict[str, str] = {}
    seen: dict[str, int] = {}
    for number, cells in rows:
        raw_mac = cells[0].strip()
        name = cells[1] if len(cells) > 1 else ""
        mac = normalize_mac(raw_mac)
        if mac is None:
            out.append(ImportLine(number, raw_mac, name.strip(), ERROR, "not a MAC address"))
            continue
        if len(cells) < 2:
            out.append(ImportLine(number, mac, "", ERROR, "no second column: the name"))
            continue
        try:
            name = clean_field("name", name)
        except NameError_ as exc:
            out.append(ImportLine(number, mac, name.strip()[:60], ERROR, str(exc)))
            continue
        before = current.get(mac, {}).get("name", "")
        if mac in seen:
            out.append(ImportLine(number, mac, name, ERROR,
                                  f"MAC already on line {seen[mac]}, this line is ignored"))
            continue
        seen[mac] = number
        if not name:
            out.append(ImportLine(number, mac, "", SKIPPED,
                                  "no name on this line: nothing is changed", before))
        elif before == name:
            out.append(ImportLine(number, mac, name, UNCHANGED, "already named so", before))
        elif before:
            todo[mac] = name
            out.append(ImportLine(number, mac, name, UPDATED, "", before))
        else:
            todo[mac] = name
            out.append(ImportLine(number, mac, name, ADDED,
                                  "" if mac in known else "not seen on the network yet"))
    return out, todo


def import_names(store: Names, text: str, known: set[str]) -> list[ImportLine]:
    """Plan the import and write every name of it in one atomic write."""
    lines, todo = plan_import(store.read(), text, known)
    if todo:
        store.set_many(todo)
    return lines


def counts(lines: list[ImportLine]) -> dict[str, int]:
    return {kind: sum(1 for x in lines if x.result == kind) for kind in RESULTS}


def import_log(lines: list[ImportLine]) -> str:
    """The result as a CSV, one row per line of the upload and a last row with the totals.
    A cell a spreadsheet would run as a formula is quoted with a leading apostrophe."""
    def safe(value: str) -> str:
        return "'" + value if value[:1] in ("=", "+", "-", "@", "\t", "\r") else value

    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\r\n")
    writer.writerow(["line", "mac", "name", "before", "result", "detail"])
    for entry in lines:
        writer.writerow([entry.line, safe(entry.mac), safe(entry.name), safe(entry.before),
                         entry.result, safe(entry.detail)])
    total = counts(lines)
    writer.writerow(["", "", "", "", "total", ", ".join(f"{n} {k}" for k, n in total.items())])
    return buffer.getvalue()
