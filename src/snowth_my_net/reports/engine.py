"""Running a report: dataset rows -> filters -> sort -> columns -> limit, or a read-only SQL query
over the datasets loaded into an in-memory SQLite database."""

from __future__ import annotations

import re
import sqlite3
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from snowth_my_net.clock import iso_z
from snowth_my_net.config.reports import ColumnCfg, FilterCfg, ReportCfg
from snowth_my_net.config.validate import parse_duration
from snowth_my_net.export.csvout import natural_key
from snowth_my_net.reports.datasets import (
    Dataset,
    DatasetError,
    Field,
    ReportContext,
    all_datasets,
    get_dataset,
)

SQL_TIMEOUT_S = 20.0
SQL_MAX_ROWS = 200_000
TRUE_WORDS = {"true", "yes", "1", "on", "y"}
FALSE_WORDS = {"false", "no", "0", "off", "n", ""}


class ReportError(ValueError):
    pass


@dataclass
class ReportTable:
    columns: list[tuple[str, str]]          # (label, field type)
    rows: list[list[Any]] = field(default_factory=list)
    total: int = 0                          # rows before the limit

    @property
    def labels(self) -> list[str]:
        return [label for label, _type in self.columns]


# --------------------------------------------------------------------------- filters


def parse_time(value: Any) -> int:
    """Epoch seconds, or an ISO date/time (``2026-09-01``, ``2026-09-01T10:00:00Z``), in UTC."""
    if isinstance(value, bool):
        raise ReportError(f"expected a date, got {value!r}")
    if isinstance(value, int):
        return value
    text = str(value).strip()
    if text.isdigit():
        return int(text)
    try:
        moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        raise ReportError(f"expected a date (2026-09-01 or 2026-09-01T10:00:00Z), "
                          f"got {value!r}") from None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return int(moment.timestamp())


def _coerce(value: Any, spec: Field) -> Any:
    if spec.type == "integer":
        if isinstance(value, bool):
            raise ReportError(f"{spec.name}: expected a number, got {value!r}")
        try:
            return int(str(value).strip())
        except ValueError:
            raise ReportError(f"{spec.name}: expected a number, got {value!r}") from None
    if spec.type == "time":
        return parse_time(value)
    if spec.type == "bool":
        if isinstance(value, bool):
            return value
        word = str(value).strip().casefold()
        if word in TRUE_WORDS:
            return True
        if word in FALSE_WORDS:
            return False
        raise ReportError(f"{spec.name}: expected true or false, got {value!r}")
    return str(value).casefold()


def _is_empty(value: Any) -> bool:
    return value is None or value == ""


def compile_filter(flt: FilterCfg, dataset: Dataset, now: int):
    """A predicate over a row. Text comparisons ignore case; empty values never match a
    comparison (use ``empty``/``not_empty`` for them)."""
    spec = dataset.field(flt.field)
    if spec is None:
        raise ReportError(f"filter: unknown field {flt.field!r} in dataset {dataset.name} "
                          f"(fields: {', '.join(f.name for f in dataset.fields)})")
    problems = flt.check()
    if problems:
        raise ReportError("; ".join(problems))
    name, op = spec.name, flt.op
    if op == "empty":
        return lambda row: _is_empty(row.get(name))
    if op == "not_empty":
        return lambda row: not _is_empty(row.get(name))
    if op in ("older_than", "newer_than"):
        if spec.type != "time":
            raise ReportError(f"filter {name}: {op} only applies to time fields")
        limit = now - parse_duration(flt.value)
        if op == "older_than":
            return lambda row: not _is_empty(row.get(name)) and row[name] < limit
        return lambda row: not _is_empty(row.get(name)) and row[name] >= limit

    def text(value: Any) -> Any:
        if spec.type == "text":
            return str(value).casefold()
        return value

    if op in ("in", "not_in"):
        wanted = {_coerce(v, spec) for v in flt.value}
        if op == "in":
            return lambda row: not _is_empty(row.get(name)) and text(row[name]) in wanted
        return lambda row: _is_empty(row.get(name)) or text(row[name]) not in wanted
    if op in ("contains", "not_contains", "startswith", "endswith", "regex"):
        if spec.type not in ("text",) and op != "regex":
            raise ReportError(f"filter {name}: {op} only applies to text fields")
        needle = str(flt.value).casefold()
        if op == "regex":
            pattern = re.compile(str(flt.value), re.IGNORECASE)
            return lambda row: (not _is_empty(row.get(name))
                                and pattern.search(display(row[name], spec.type)) is not None)
        if op == "contains":
            return lambda row: needle in str(row.get(name) or "").casefold()
        if op == "not_contains":
            return lambda row: needle not in str(row.get(name) or "").casefold()
        if op == "startswith":
            return lambda row: str(row.get(name) or "").casefold().startswith(needle)
        return lambda row: str(row.get(name) or "").casefold().endswith(needle)
    target = _coerce(flt.value, spec)
    if op == "ne":
        return lambda row: _is_empty(row.get(name)) or text(row[name]) != target
    if spec.type == "bool" and op != "eq":
        raise ReportError(f"filter {name}: {op} does not apply to true/false fields")
    compare = {"eq": lambda a: a == target, "gt": lambda a: a > target,
               "ge": lambda a: a >= target, "lt": lambda a: a < target,
               "le": lambda a: a <= target}[op]
    return lambda row: not _is_empty(row.get(name)) and compare(text(row[name]))


# --------------------------------------------------------------------------- dataset reports


def _sort_key(value: Any, type_: str) -> tuple:
    if _is_empty(value):
        return (1, 0)                       # empty values last, in both directions
    if type_ == "text":
        return (0, natural_key(str(value)))
    return (0, value)


def sort_rows(rows: list[dict], sort: list[str], dataset: Dataset) -> list[dict]:
    for item in reversed(sort):
        descending = item.startswith("-")
        name = item.lstrip("-+")
        spec = dataset.field(name)
        if spec is None:
            raise ReportError(f"sort: unknown field {name!r} in dataset {dataset.name}")
        present = [r for r in rows if not _is_empty(r.get(name))]
        missing = [r for r in rows if _is_empty(r.get(name))]
        present.sort(key=lambda r, n=name, t=spec.type: _sort_key(r[n], t), reverse=descending)
        rows = present + missing
    return rows


def dataset_rows(ctx: ReportContext, dataset: Dataset) -> list[dict]:
    """Rows of a dataset; an exception in a Python dataset becomes a report error."""
    if not dataset.name.startswith("py:"):
        return ctx.rows(dataset)
    try:
        return ctx.rows(dataset)
    except ReportError:
        raise
    except Exception as exc:  # extension code
        raise ReportError(f"dataset {dataset.name} failed: {type(exc).__name__}: {exc}") from exc


def resolve_columns(columns: list[ColumnCfg], dataset: Dataset) -> list[tuple[Field, str]]:
    if not columns:
        return [(f, f.name) for f in dataset.fields if f.default]
    result = []
    for column in columns:
        spec = dataset.field(column.field)
        if spec is None:
            raise ReportError(f"columns: unknown field {column.field!r} in dataset "
                              f"{dataset.name} (fields: "
                              f"{', '.join(f.name for f in dataset.fields)})")
        result.append((spec, column.label or column.field))
    return result


def run_dataset_report(cfg: ReportCfg, ctx: ReportContext) -> ReportTable:
    try:
        dataset = get_dataset(cfg.dataset or "", ctx.collectors, ctx.extra)
    except DatasetError as exc:
        raise ReportError(str(exc)) from None
    columns = resolve_columns(cfg.column_specs(), dataset)
    predicates = [compile_filter(f, dataset, ctx.now) for f in cfg.filters]
    rows = [r for r in dataset_rows(ctx, dataset) if all(p(r) for p in predicates)]
    rows = sort_rows(rows, cfg.sort, dataset)
    table = ReportTable([(label, spec.type) for spec, label in columns], total=len(rows))
    if cfg.limit is not None:
        rows = rows[:cfg.limit]
    table.rows = [[row.get(spec.name) for spec, _label in columns] for row in rows]
    return table


# --------------------------------------------------------------------------- SQL reports

# sqlite3 authorizer action codes that a SELECT needs; everything else is denied.
_ALLOWED_ACTIONS = {sqlite3.SQLITE_SELECT, sqlite3.SQLITE_READ, sqlite3.SQLITE_FUNCTION,
                    getattr(sqlite3, "SQLITE_RECURSIVE", 33)}
_DENIED_FUNCTIONS = {"load_extension", "readfile", "writefile", "edit", "fts3_tokenizer"}


def sql_table_name(dataset: str) -> str:
    """``custom:poe-ports`` -> ``custom_poe_ports``."""
    return re.sub(r"[^a-z0-9_]", "_", dataset.lower())


def _authorizer(action, arg1, arg2, _db, _trigger):
    if action not in _ALLOWED_ACTIONS:
        return sqlite3.SQLITE_DENY
    if action == sqlite3.SQLITE_FUNCTION and (arg2 or "").lower() in _DENIED_FUNCTIONS:
        return sqlite3.SQLITE_DENY
    return sqlite3.SQLITE_OK


def sql_tables(collectors: list, extra: list = ()) -> dict[str, Dataset]:
    return {sql_table_name(name): ds for name, ds in all_datasets(collectors, extra).items()}


def run_sql_report(cfg: ReportCfg, ctx: ReportContext, timeout_s: float = SQL_TIMEOUT_S
                   ) -> ReportTable:
    """Run a SELECT over the datasets it names, in a private in-memory database.

    The query never sees the state file: only copies of the dataset rows it mentions. The
    connection is ``query_only`` and an authorizer refuses anything but reading (no ATTACH,
    PRAGMA, writes or extension loading); a progress handler stops runaway queries.
    """
    query = (cfg.sql or "").strip().rstrip(";")
    if not re.match(r"^(select|with)\b", query, re.IGNORECASE):
        raise ReportError("sql must be a SELECT query")
    tables = sql_tables(ctx.collectors, ctx.extra)
    words = set(re.findall(r"[a-z0-9_]+", query.lower()))
    wanted = {name: ds for name, ds in tables.items() if name in words}
    if not wanted:
        raise ReportError(f"the query uses no dataset table (tables: {', '.join(tables)})")
    db = sqlite3.connect(":memory:")
    try:
        for name, ds in wanted.items():
            types = {"integer": "INTEGER", "time": "INTEGER", "bool": "INTEGER"}
            columns = ", ".join(f'"{f.name}" {types.get(f.type, "TEXT")}' for f in ds.fields)
            db.execute(f'CREATE TABLE "{name}" ({columns})')
            names = [f.name for f in ds.fields]
            db.executemany(
                # name comes from sql_table_name(): [a-z0-9_] only
                f'INSERT INTO "{name}" VALUES ({", ".join("?" * len(names))})',  # noqa: S608
                ([_sql_value(row.get(n)) for n in names] for row in dataset_rows(ctx, ds)))
        db.create_function("iso", 1, lambda v: iso_z(int(v)) if v is not None else None,
                           deterministic=True)
        db.create_function("now", 0, lambda: ctx.now)
        db.create_function("age_days", 1, lambda v: (ctx.now - int(v)) // 86400
                           if v is not None else None)
        db.execute("PRAGMA query_only = ON")
        db.set_authorizer(_authorizer)
        deadline = time.monotonic() + timeout_s
        db.set_progress_handler(lambda: 1 if time.monotonic() > deadline else 0, 10_000)
        try:
            cursor = db.execute(query)
            rows = cursor.fetchmany(SQL_MAX_ROWS + 1)
        except sqlite3.ProgrammingError as exc:
            text = str(exc)
            if "one statement" in text:
                text = "only one SELECT statement is allowed"
            raise ReportError(f"sql: {text}") from None
        except sqlite3.Warning as exc:
            raise ReportError(f"sql: only one SELECT statement is allowed ({exc})") from None
        except sqlite3.DatabaseError as exc:
            text = str(exc)
            if "interrupted" in text:
                text = f"query stopped after {timeout_s:g} s"
            elif "not authorized" in text:
                text = "not authorized: reports can only read (SELECT)"
            raise ReportError(f"sql: {text}") from None
        if len(rows) > SQL_MAX_ROWS:
            raise ReportError(f"sql: more than {SQL_MAX_ROWS} rows; add a LIMIT")
        labels = [d[0] for d in cursor.description or ()]
    finally:
        db.close()
    kinds = []
    for i in range(len(labels)):
        values = [r[i] for r in rows if r[i] is not None]
        kinds.append("integer" if values and all(isinstance(v, int) for v in values)
                     else "text")
    table = ReportTable(list(zip(labels, kinds, strict=True)), total=len(rows))
    if cfg.limit is not None:
        rows = rows[:cfg.limit]
    table.rows = [list(r) for r in rows]
    return table


def _sql_value(value: Any) -> Any:
    if isinstance(value, bool):
        return int(value)
    return value


def run_report(cfg: ReportCfg, ctx: ReportContext) -> ReportTable:
    problems = cfg.check()
    if problems:
        raise ReportError("; ".join(problems))
    if cfg.sql:
        return run_sql_report(cfg, ctx)
    return run_dataset_report(cfg, ctx)


def display(value: Any, type_: str) -> str:
    if value is None:
        return ""
    if type_ == "time":
        return iso_z(int(value))
    if type_ == "bool":
        return "yes" if value else "no"
    return str(value)


