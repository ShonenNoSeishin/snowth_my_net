"""Small typed loader: plain YAML data -> dataclasses, with path-aware error messages.

Supported annotations: ``str``, ``int``, ``float``, ``bool``, ``Literal[...]``, ``X | None``,
unions, ``list[X]``, ``dict[str, X]``, nested dataclasses and ``Annotated[T, Converter(...)]``
for custom scalars (durations, networks).

Every problem is collected (not only the first one) and reported with its location, e.g.
``devices[2].features.arp: expected one of auto|force|off, got 'yes'``. Unknown keys are errors,
with a suggestion when the key looks like a typo. A dataclass may declare
``__forbidden_keys__ = {key: hint}`` to reject keys with a specific message (plain-text secrets)
and a ``check()`` method returning extra error messages.
"""

from __future__ import annotations

import dataclasses
import difflib
import ipaddress
import re
import types
from collections.abc import Callable
from typing import Annotated, Any, Literal, TypeVar, Union, get_args, get_origin, get_type_hints

T = TypeVar("T")


class ConfigError(Exception):
    """Invalid configuration; ``errors`` holds one human-readable message per problem."""

    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        super().__init__("\n".join(errors))


@dataclasses.dataclass(frozen=True)
class Converter:
    """``Annotated`` marker: ``func(value)`` returns the converted value or raises ValueError."""

    name: str
    func: Callable[[Any], Any]


_DURATION = re.compile(r"^\s*(\d+)\s*([smhd]?)\s*$")
_UNITS = {"": 1, "s": 1, "m": 60, "h": 3600, "d": 86400}


def parse_duration(value: Any) -> int:
    if isinstance(value, bool):
        raise ValueError("expected a duration, got a boolean")
    if isinstance(value, int) and value >= 0:
        return value
    if isinstance(value, str) and (m := _DURATION.match(value)):
        return int(m[1]) * _UNITS[m[2]]
    raise ValueError(f"expected a duration (seconds, or '30s', '10m', '24h', '7d'), got {value!r}")


def parse_network(value: Any) -> ipaddress.IPv4Network | ipaddress.IPv6Network:
    if isinstance(value, bool) or not isinstance(value, str | int):
        raise ValueError(f"expected an IP address or CIDR, got {value!r}")
    try:
        return ipaddress.ip_network(str(value).strip(), strict=False)
    except ValueError:
        raise ValueError(f"expected an IP address or CIDR, got {value!r}") from None


Duration = Annotated[int, Converter("duration", parse_duration)]
Network = Annotated[
    ipaddress.IPv4Network | ipaddress.IPv6Network, Converter("network", parse_network)
]


def build(cls: type[T], data: Any) -> T:
    """Build ``cls`` from ``data`` or raise :class:`ConfigError` listing every problem."""
    errors: list[str] = []
    result = _convert(cls, data, "", errors)
    if errors:
        raise ConfigError(errors)
    return result


def _where(path: str) -> str:
    return path or "<config>"


def _describe(value: Any) -> str:
    if value is None:
        return "nothing"
    if isinstance(value, dict):
        return "a mapping"
    if isinstance(value, list):
        return "a list"
    return repr(value)


def _convert(tp: Any, value: Any, path: str, errors: list[str]) -> Any:
    origin = get_origin(tp)

    if origin is Annotated:
        base, *meta = get_args(tp)
        for marker in meta:
            if isinstance(marker, Converter):
                try:
                    return marker.func(value)
                except (ValueError, TypeError) as exc:
                    errors.append(f"{_where(path)}: {exc}")
                    return None
        return _convert(base, value, path, errors)

    if tp is Any:
        return value

    if origin in (Union, types.UnionType):
        args = get_args(tp)
        if value is None:
            if type(None) in args:
                return None
            errors.append(f"{_where(path)}: a value is required")
            return None
        candidates = [a for a in args if a is not type(None)]
        if len(candidates) == 1:
            return _convert(candidates[0], value, path, errors)
        attempts: list[tuple[Any, list[str]]] = []
        for candidate in candidates:
            attempt: list[str] = []
            result = _convert(candidate, value, path, attempt)
            if not attempt:
                return result
            attempts.append((candidate, attempt))
        # Report the errors of the alternative that has the shape of the value (a mapping for
        # a dataclass, a list for a list…), which is what the author meant.
        for candidate, attempt in attempts:
            shaped = ((isinstance(value, dict) and (dataclasses.is_dataclass(candidate)
                                                    or get_origin(candidate) is dict))
                      or (isinstance(value, list) and get_origin(candidate) is list))
            if shaped:
                errors.extend(attempt)
                return None
        errors.append(f"{_where(path)}: unexpected value {_describe(value)}")
        return None

    if origin is Literal:
        options = get_args(tp)
        candidate = value
        if isinstance(value, bool):
            # YAML 1.1 reads a bare `off` / `on` as a boolean: accept it where it means that.
            word = "on" if value else "off"
            if word in options:
                return word
        elif isinstance(value, int) and value not in options:
            candidate = str(value)  # e.g. ``version: 3`` for Literal["2c", "3"]
        if candidate in options:
            return candidate
        choices = "|".join(str(o) for o in options)
        errors.append(f"{_where(path)}: expected one of {choices}, got {_describe(value)}")
        return None

    if origin is list:
        (item_type,) = get_args(tp)
        if value is None:
            return []
        if not isinstance(value, list):
            errors.append(f"{_where(path)}: expected a list, got {_describe(value)}")
            return []
        return [_convert(item_type, v, f"{path}[{i}]", errors) for i, v in enumerate(value)]

    if origin is dict:
        key_type, value_type = get_args(tp)
        if value is None:
            return {}
        if not isinstance(value, dict):
            errors.append(f"{_where(path)}: expected a mapping, got {_describe(value)}")
            return {}
        result = {}
        for k, v in value.items():
            if get_origin(key_type) is Literal and str(k) not in get_args(key_type):
                choices = "|".join(get_args(key_type))
                errors.append(f"{path}.{k}: unknown key, expected one of {choices}")
                continue
            result[str(k)] = _convert(value_type, v, f"{path}.{k}", errors)
        return result

    if dataclasses.is_dataclass(tp):
        return _build_dataclass(tp, value, path, errors)

    if tp is bool:
        if isinstance(value, bool):
            return value
        errors.append(f"{_where(path)}: expected true or false, got {_describe(value)}")
        return None
    if tp is int:
        if isinstance(value, int) and not isinstance(value, bool):
            return value
        errors.append(f"{_where(path)}: expected an integer, got {_describe(value)}")
        return None
    if tp is float:
        if isinstance(value, int | float) and not isinstance(value, bool):
            return float(value)
        errors.append(f"{_where(path)}: expected a number, got {_describe(value)}")
        return None
    if tp is str:
        if isinstance(value, str):
            return value
        if isinstance(value, int | float) and not isinstance(value, bool):
            return str(value)
        errors.append(f"{_where(path)}: expected a string, got {_describe(value)}")
        return None

    raise TypeError(f"unsupported annotation {tp!r} at {_where(path)}")


def _build_dataclass(cls: type, value: Any, path: str, errors: list[str]) -> Any:
    if value is None:
        value = {}
    if not isinstance(value, dict):
        errors.append(f"{_where(path)}: expected a mapping, got {_describe(value)}")
        return None
    hints = get_type_hints(cls, include_extras=True)
    fields = {f.name: f for f in dataclasses.fields(cls) if f.init}
    forbidden: dict[str, str] = getattr(cls, "__forbidden_keys__", {})
    prefix = f"{path}." if path else ""

    for key in value:
        key_s = str(key)
        if key_s in forbidden:
            errors.append(f"{prefix}{key_s}: {forbidden[key_s]}")
        elif key_s not in fields:
            close = difflib.get_close_matches(key_s, list(fields), n=1)
            hint = f" (did you mean '{close[0]}'?)" if close else ""
            errors.append(f"{prefix}{key_s}: unknown key{hint}")

    kwargs: dict[str, Any] = {}
    missing = False
    for name, field in fields.items():
        if name in value:
            kwargs[name] = _convert(hints[name], value[name], f"{prefix}{name}", errors)
        elif field.default is dataclasses.MISSING and field.default_factory is dataclasses.MISSING:
            errors.append(f"{prefix}{name}: required")
            missing = True
    if missing:
        return None

    obj = cls(**kwargs)
    check = getattr(obj, "check", None)
    if callable(check):
        errors.extend(f"{_where(path)}: {msg}" for msg in check())
    return obj
