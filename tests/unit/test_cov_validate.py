"""Validator: every conversion path and its error message."""

from __future__ import annotations

import ipaddress
from dataclasses import dataclass, field
from typing import Annotated, Any, ClassVar, Literal

import pytest

from snowth_my_net.config.validate import (
    ConfigError,
    Converter,
    Duration,
    Network,
    build,
    parse_duration,
    parse_network,
)


@dataclass
class Inner:
    name: str
    level: int = 0


@dataclass
class Shapes:
    flag: bool = False
    count: int = 0
    ratio: float = 0.0
    label: str = ""
    anything: Any = None
    mode: Literal["on", "off", "auto"] = "auto"
    version: Literal["2c", "3"] = "2c"
    items: list[int] = field(default_factory=list)
    table: dict[str, int] = field(default_factory=dict)
    keyed: dict[Literal["a", "b"], int] = field(default_factory=dict)
    inner: Inner | None = None
    either: Inner | list[str] | None = None
    number_or_word: int | Literal["auto"] = 0
    wait: Duration = 0
    net: Network | None = None
    plain: Annotated[int, "no converter"] = 0


def errors_of(data) -> list[str]:
    with pytest.raises(ConfigError) as caught:
        build(Shapes, data)
    return caught.value.errors


def test_parse_duration_and_network():
    assert parse_duration(5) == 5 and parse_duration(" 10m ") == 600
    assert parse_duration("2d") == 172800
    with pytest.raises(ValueError, match="boolean"):
        parse_duration(True)
    with pytest.raises(ValueError, match="expected a duration"):
        parse_duration(-1)
    with pytest.raises(ValueError, match="expected a duration"):
        parse_duration("1w")
    assert parse_network("192.0.2.7/24") == ipaddress.ip_network("192.0.2.0/24")
    for bad in (True, None, 1.5, "not-an-ip"):
        with pytest.raises(ValueError, match="expected an IP address or CIDR"):
            parse_network(bad)


def test_valid_values_of_every_shape():
    obj = build(Shapes, {
        "flag": True, "count": 3, "ratio": 2, "label": 7, "anything": {"x": 1}, "mode": False,
        "version": 3, "items": [1, 2], "table": {"x": 1}, "keyed": {"a": 1},
        "inner": {"name": "n"}, "either": ["x"], "number_or_word": "auto", "wait": "1h",
        "net": "10.0.0.0/8", "plain": 4})
    assert (obj.flag, obj.count, obj.ratio, obj.label, obj.mode, obj.version) == (
        True, 3, 2.0, "7", "off", "3")
    assert obj.items == [1, 2] and obj.table == {"x": 1} and obj.keyed == {"a": 1}
    assert obj.inner == Inner("n") and obj.either == ["x"] and obj.number_or_word == "auto"
    assert obj.wait == 3600 and str(obj.net) == "10.0.0.0/8" and obj.plain == 4
    empty = build(Shapes, {"items": None, "table": None, "inner": None})
    assert empty.items == [] and empty.table == {} and empty.inner is None
    assert build(Shapes, None) == Shapes()


def test_error_messages():
    errors = errors_of({
        "flag": "yes", "count": True, "ratio": "x", "label": [1], "mode": "maybe",
        "items": "1,2", "table": [1], "keyed": {"c": 1}, "wait": "soon", "net": "nope",
        "unknwn": 1, "cuont": 2})
    text = "\n".join(errors)
    for expected in ("flag: expected true or false, got 'yes'",
                     "count: expected an integer, got True",
                     "ratio: expected a number, got 'x'",
                     "label: expected a string, got a list",
                     "mode: expected one of on|off|auto, got 'maybe'",
                     "items: expected a list, got '1,2'",
                     "table: expected a mapping, got a list",
                     ".c: unknown key, expected one of a|b",
                     "wait: expected a duration",
                     "net: expected an IP address or CIDR",
                     "unknwn: unknown key",
                     "cuont: unknown key (did you mean 'count'?)"):
        assert expected in text, expected
    assert "mode: expected one of on|off|auto" in text


def test_booleans_for_literals_without_on_off_are_errors():
    assert "version: expected one of 2c|3, got True" in "\n".join(errors_of({"version": True}))


def test_union_errors_follow_the_shape_of_the_value():
    assert errors_of({"either": {"level": 1}}) == ["either.name: required"]
    assert errors_of({"either": [[1]]}) == ["either[0]: expected a string, got a list"]
    assert errors_of({"either": 5}) == ["either: unexpected value 5"]
    assert errors_of({"number_or_word": None}) == ["number_or_word: a value is required"]
    assert errors_of({"inner": "x"}) == ["inner: expected a mapping, got 'x'"]
    assert errors_of({"count": None}) == ["count: expected an integer, got nothing"]


def test_top_level_errors_and_forbidden_keys():
    with pytest.raises(ConfigError) as caught:
        build(Inner, [1])
    assert caught.value.errors == ["<config>: expected a mapping, got a list"]

    @dataclass
    class Secretive:
        __forbidden_keys__: ClassVar = {"password": "not here"}
        user: str = ""

    with pytest.raises(ConfigError, match="password: not here"):
        build(Secretive, {"password": "x"})

    @dataclass
    class Checked:
        value: int = 0

        def check(self):
            return ["value must be even"] if self.value % 2 else []

    with pytest.raises(ConfigError, match="<config>: value must be even"):
        build(Checked, {"value": 3})


def test_unsupported_annotation_is_a_programming_error():
    @dataclass
    class Odd:
        value: bytes = b""

    with pytest.raises(TypeError, match="unsupported annotation"):
        build(Odd, {"value": b"x"})


def _boom(value):
    raise TypeError("bad type")


@dataclass
class WithConverter:
    value: Annotated[int, Converter("boom", _boom)] = 0


def test_converter_type_errors_are_reported():
    with pytest.raises(ConfigError, match="value: bad type"):
        build(WithConverter, {"value": 1})


def test_config_error_str():
    exc = ConfigError(["a", "b"])
    assert exc.errors == ["a", "b"]
