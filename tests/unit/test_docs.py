"""The configuration reference documents every key of the schema."""

import dataclasses
import types
import typing
from pathlib import Path

from snowth_my_net.config.schema import Config

DOC = Path(__file__).resolve().parents[2] / "docs" / "config.md"


def keys(cls, prefix=""):
    hints = typing.get_type_hints(cls, include_extras=True)
    for f in dataclasses.fields(cls):
        tp, path = hints[f.name], f"{prefix}{f.name}"
        origin = typing.get_origin(tp)
        args = [a for a in typing.get_args(tp) if a is not type(None)]
        nested = None
        if origin is typing.Annotated:
            nested = None
        elif dataclasses.is_dataclass(tp):
            nested = (tp, path + ".")
        elif origin is list and args and dataclasses.is_dataclass(args[0]):
            nested = (args[0], path + "[].")
        elif origin in (typing.Union, types.UnionType):
            dcs = [a for a in args if dataclasses.is_dataclass(a)]
            nested = (dcs[0], path + ".") if dcs else None
        elif origin is dict and dataclasses.is_dataclass(typing.get_args(tp)[1]):
            nested = (typing.get_args(tp)[1], path + ".<name>.")
        if nested:
            yield from keys(*nested)
        else:
            yield path


def test_every_configuration_key_is_documented():
    text = DOC.read_text(encoding="utf-8")
    missing = [k for k in keys(Config) if f"`{k}`" not in text]
    assert missing == []
