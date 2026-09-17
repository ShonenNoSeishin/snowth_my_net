"""Report renderers: CSV, JSON, Markdown and a standalone, sortable HTML page."""

from __future__ import annotations

import html
import json
from importlib import resources
from typing import Any

from snowth_my_net import __version__
from snowth_my_net.clock import iso_z
from snowth_my_net.config.reports import ReportCfg
from snowth_my_net.export.csvout import EOL, render_csv
from snowth_my_net.reports.engine import ReportTable, display


def _csv_header(labels: list[str], eol: str) -> str:
    import csv
    import io

    buf = io.StringIO(newline="")
    csv.writer(buf, lineterminator=eol, quoting=csv.QUOTE_MINIMAL).writerow(labels)
    return buf.getvalue().removesuffix(eol)


def to_csv(table: ReportTable, line_terminator: str = "crlf") -> bytes:
    rows = [[display(v, t) for v, (_l, t) in zip(row, table.columns, strict=True)]
            for row in table.rows]
    return render_csv(_csv_header(table.labels, EOL[line_terminator]), rows, line_terminator)


def _json_value(value: Any, type_: str) -> Any:
    if value is None:
        return None
    if type_ == "time":
        return iso_z(int(value))
    return value


def to_json(table: ReportTable, cfg: ReportCfg, now: int) -> bytes:
    document = {
        "report": cfg.name, "title": cfg.title or cfg.name, "generated_at": iso_z(now),
        "source": cfg.source, "generator": f"snowth_my_net {__version__}",
        "row_count": len(table.rows), "columns": table.labels,
        "rows": [{label: _json_value(v, t) for v, (label, t)
                  in zip(row, table.columns, strict=True)} for row in table.rows],
    }
    return (json.dumps(document, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def _md_cell(text: str) -> str:
    return " ".join(text.split()).replace("\\", "\\\\").replace("|", "\\|")


def to_markdown(table: ReportTable, cfg: ReportCfg, now: int) -> bytes:
    lines = [f"# {_md_cell(cfg.title or cfg.name)}", ""]
    if cfg.description:
        lines += [_md_cell(cfg.description), ""]
    lines += [f"Generated {iso_z(now)} — {len(table.rows)} row(s)", ""]
    if table.columns:
        lines.append("| " + " | ".join(_md_cell(label) for label in table.labels) + " |")
        lines.append("|" + "|".join("---:" if t == "integer" else "---"
                                    for _l, t in table.columns) + "|")
        for row in table.rows:
            lines.append("| " + " | ".join(_md_cell(display(v, t)) for v, (_l, t)
                                           in zip(row, table.columns, strict=True)) + " |")
    return ("\n".join(lines) + "\n").encode("utf-8")


def to_html(table: ReportTable, cfg: ReportCfg, now: int) -> bytes:
    template = resources.files("snowth_my_net.reports").joinpath("report_template.html")
    head = "".join(f'<th data-type="{t}" class="{t}"><button type="button">{html.escape(label)}'
                   '<span class="arrow"></span></button></th>' for label, t in table.columns)
    body = []
    for row in table.rows:
        cells = []
        for value, (_label, type_) in zip(row, table.columns, strict=True):
            sort = "" if value is None else (str(int(value)) if type_ in ("time", "bool")
                                             else str(value))
            cells.append(f'<td class="{type_}" data-sort="{html.escape(sort)}">'
                         f"{html.escape(display(value, type_))}</td>")
        body.append("<tr>" + "".join(cells) + "</tr>")
    page = template.read_text(encoding="utf-8")
    replacements = {
        "__TITLE__": html.escape(cfg.title or cfg.name),
        "__DESCRIPTION__": html.escape(cfg.description),
        "__META__": html.escape(f"{cfg.source} · generated {iso_z(now)} · "
                                f"snowth_my_net {__version__}"),
        "__COUNT__": str(len(table.rows)),
        "__HEAD__": head,
        "__BODY__": "\n".join(body),
    }
    for key, value in replacements.items():
        page = page.replace(key, value)
    return page.encode("utf-8")


def render(table: ReportTable, cfg: ReportCfg, now: int, fmt: str | None = None,
           line_terminator: str = "crlf") -> bytes:
    fmt = fmt or cfg.format
    if fmt == "csv":
        return to_csv(table, line_terminator)
    if fmt == "json":
        return to_json(table, cfg, now)
    if fmt == "markdown":
        return to_markdown(table, cfg, now)
    if fmt == "html":
        return to_html(table, cfg, now)
    raise ValueError(f"unknown format {fmt!r}")
