"""Custom reports: a dataset (or a read-only SQL query) + columns + filters + sort + format.

    reports:
      - name: unknown-types
        title: Devices without a sure type
        dataset: devices
        columns: [name, ip, vendor, model, os]
        filters:
          - {field: device_type, op: empty}
        sort: [vendor, name]
        format: html
        schedule: "0 7 * * 1"            # optional: cron print adds "report run unknown-types"
        push: [cmdb]                     # optional: push targets receiving the file
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any, Literal

from snowth_my_net.config.validate import parse_duration

ReportFormat = Literal["csv", "json", "markdown", "html"]
FilterOp = Literal["eq", "ne", "contains", "not_contains", "startswith", "endswith", "regex",
                   "gt", "ge", "lt", "le", "empty", "not_empty", "in", "not_in",
                   "older_than", "newer_than"]
NO_VALUE_OPS = frozenset({"empty", "not_empty"})
EXTENSIONS = {"csv": "csv", "json": "json", "markdown": "md", "html": "html"}
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,62}$")
STATIC_DATASETS = ("devices", "interfaces", "nodes", "ip_history", "vlans", "links", "neighbors",
                   "runs", "custom")


@dataclass
class FilterCfg:
    field: str
    op: FilterOp = "eq"
    value: Any = None

    def check(self) -> list[str]:
        if self.op is None:             # already reported by the type validation
            return []
        if self.op in NO_VALUE_OPS:
            return [] if self.value is None else [f"filter {self.field}: {self.op} takes no value"]
        if self.value is None:
            return [f"filter {self.field}: {self.op} needs a value"]
        if self.op in ("in", "not_in") and not isinstance(self.value, list):
            return [f"filter {self.field}: {self.op} needs a list"]
        if self.op in ("older_than", "newer_than"):
            try:
                parse_duration(self.value)
            except ValueError as exc:
                return [f"filter {self.field}: {exc}"]
        if self.op == "regex":
            try:
                re.compile(str(self.value))
            except re.error as exc:
                return [f"filter {self.field}: invalid regex: {exc}"]
        return []


@dataclass
class ColumnCfg:
    field: str
    label: str = ""


@dataclass
class ReportCfg:
    name: str
    title: str = ""
    description: str = ""
    dataset: str | None = None
    sql: str | None = None
    columns: list[str | ColumnCfg] = field(default_factory=list)   # empty: default columns
    filters: list[FilterCfg] = field(default_factory=list)
    sort: list[str] = field(default_factory=list)          # "-field" = descending
    limit: int | None = None
    format: ReportFormat = "csv"
    output: str | None = None                              # relative to the output directory
    schedule: str | None = None
    push: list[str] = field(default_factory=list)
    allow_empty: bool = False

    def check(self) -> list[str]:
        errs = []
        if not NAME_RE.match(self.name):
            errs.append(f"report name {self.name!r}: use lowercase letters, digits, '-' and '_'")
        if bool(self.dataset) == bool(self.sql):
            errs.append(f"report {self.name!r}: set exactly one of dataset or sql")
        if self.dataset and self.dataset not in STATIC_DATASETS and not (
                self.dataset.startswith(("custom:", "py:"))
                and len(self.dataset.split(":", 1)[1]) > 0):
            errs.append(f"report {self.name!r}: unknown dataset {self.dataset!r} "
                        f"({', '.join(STATIC_DATASETS)}, custom:<collector>, "
                        "py:<python dataset>)")
        if self.sql:
            if not re.match(r"^\s*(select|with)\b", self.sql, re.IGNORECASE):
                errs.append(f"report {self.name!r}: sql must be a SELECT query")
            if self.columns or self.filters or self.sort:
                errs.append(f"report {self.name!r}: columns, filters and sort do not apply to "
                            "sql reports (write them in the query)")
        if self.limit is not None and self.limit < 1:
            errs.append("limit must be > 0")
        if self.output is not None:
            path = PurePosixPath(self.output)
            if path.is_absolute() or ".." in path.parts or not path.name:
                errs.append(f"report {self.name!r}: output must be a relative path inside the "
                            "output directory")
        if self.schedule:
            from snowth_my_net.schedule.cron import CronError, parse_cron

            try:
                parse_cron(self.schedule)
            except CronError as exc:
                errs.append(f"report {self.name!r}: schedule: {exc}")
        return errs

    def output_path(self, output_dir: Path) -> Path:
        relative = self.output or f"reports/{self.name}.{EXTENSIONS[self.format]}"
        return output_dir / relative

    def column_specs(self) -> list[ColumnCfg]:
        return [ColumnCfg(c) if isinstance(c, str) else c for c in self.columns]

    @property
    def source(self) -> str:
        return self.dataset or "sql"


@dataclass
class LoadedReport:
    cfg: ReportCfg
    origin: str                                            # file path, or "tui"
