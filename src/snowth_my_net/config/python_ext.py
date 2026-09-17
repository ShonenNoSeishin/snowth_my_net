"""Loading Python extensions named in ``general.python_extensions``.

Nothing is imported unless named: first ``<extensions_dir>/<name>.py``, then an installed entry
point ``snowth_my_net.extensions`` called ``<name>``. An extension runs with the rights of
snowth_my_net itself; only enable code you trust.
"""

from __future__ import annotations

import importlib.metadata
import importlib.util
import sys
import traceback
from dataclasses import dataclass, field
from pathlib import Path

from snowth_my_net.config.validate import ConfigError, build, parse_duration

ENTRY_POINT_GROUP = "snowth_my_net.extensions"


@dataclass
class LoadedPython:
    name: str
    origin: str                       # file path or "entry point <value>"
    extension: object                 # snowth_my_net.api.Extension


@dataclass
class PythonParts:
    extensions: list[LoadedPython] = field(default_factory=list)
    collectors: list = field(default_factory=list)      # LoadedCollector
    datasets: list = field(default_factory=list)        # reports Dataset
    exporters: list = field(default_factory=list)       # (extension name, PythonExporter)


def _short_error(exc: BaseException) -> str:
    frames = traceback.extract_tb(exc.__traceback__)
    where = f" ({Path(frames[-1].filename).name}:{frames[-1].lineno})" if frames else ""
    return f"{type(exc).__name__}: {exc}{where}"


def _import_file(name: str, path: Path):
    module_name = f"snowth_my_net_ext_{name.replace('-', '_')}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        sys.modules.pop(module_name, None)
        raise
    return getattr(module, "extension", None)


def find_extension(name: str, directory: Path | None):
    path = directory / f"{name}.py" if directory is not None else None
    if path is not None and path.is_file():
        return _import_file(name, path), str(path)
    for entry in importlib.metadata.entry_points(group=ENTRY_POINT_GROUP):
        if entry.name == name:
            return entry.load(), f"entry point {entry.value}"
    return None, None


def load_python_extensions(names: list[str], directory: Path | None,
                           taken_collectors: set[str]) -> PythonParts:
    from snowth_my_net.api import API_VERSION, Extension
    from snowth_my_net.collect.custom import python_collector_cfg
    from snowth_my_net.config.extensions import AppliesTo, LoadedCollector
    from snowth_my_net.reports.datasets import Dataset

    parts = PythonParts()
    errors: list[str] = []
    seen_collectors = set(taken_collectors)
    seen_datasets: set[str] = set()
    seen_files: set[str] = set()
    for name in names:
        try:
            extension, origin = find_extension(name, directory)
        except Exception as exc:  # the extension's own code failed at import
            errors.append(f"python extension '{name}': import failed: {_short_error(exc)}")
            continue
        if origin is None:
            where = f"{directory}/{name}.py" if directory else "the extensions directory"
            errors.append(f"python extension '{name}': not found (no {where}, no installed "
                          f"entry point '{name}' in group {ENTRY_POINT_GROUP})")
            continue
        if not isinstance(extension, Extension):
            errors.append(f"python extension '{name}' ({origin}): must define a module-level "
                          "'extension = Extension(...)'")
            continue
        if extension.api_version != API_VERSION:
            errors.append(f"python extension '{name}': written for API {extension.api_version}, "
                          f"this version provides API {API_VERSION}")
            continue
        parts.extensions.append(LoadedPython(name, origin, extension))
        for collector in extension.collectors:
            if collector.name in seen_collectors:
                errors.append(f"python extension '{name}': collector name '{collector.name}' "
                              "is already used")
                continue
            try:
                scope = build(AppliesTo, collector.applies_to)
                every = parse_duration(collector.every)
            except (ConfigError, ValueError) as exc:
                text = "; ".join(exc.errors) if isinstance(exc, ConfigError) else str(exc)
                errors.append(f"python extension '{name}': collector '{collector.name}': {text}")
                continue
            seen_collectors.add(collector.name)
            parts.collectors.append(LoadedCollector(
                python_collector_cfg(collector, scope, every, name), f"python:{name}"))
        for ds in extension.datasets:
            if ds.name in seen_datasets:
                errors.append(f"python extension '{name}': dataset 'py:{ds.name}' is already "
                              "used")
                continue
            seen_datasets.add(ds.name)
            parts.datasets.append(Dataset(f"py:{ds.name}", ds.description or
                                          f"from the Python extension {name}", ds.fields,
                                          _dataset_builder(ds.func)))
        for exporter in extension.exporters:
            if exporter.filename in seen_files:
                errors.append(f"python extension '{name}': file '{exporter.filename}' is "
                              "already written by another exporter")
                continue
            seen_files.add(exporter.filename)
            parts.exporters.append((name, exporter))
    if errors:
        raise ConfigError(errors)
    return parts


def _dataset_builder(func):
    def build_rows(ctx) -> list[dict]:
        rows = func(ctx)
        if not isinstance(rows, list) or not all(isinstance(r, dict) for r in rows):
            raise TypeError("a Python dataset must return a list of dicts")
        return rows

    return build_rows
