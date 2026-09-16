"""Serialization for the CRE data model.

The model is built on dataclasses + enums (stdlib only), so serialization is a
small recursive walk. Enums serialize to their string value; nested dataclasses
recurse; lists/dicts are walked element-wise.
"""

from __future__ import annotations

import dataclasses
import json
from enum import Enum
from typing import Any, Optional, Union, get_args, get_origin, get_type_hints

_NONE_TYPE = type(None)


def to_dict(obj: Any) -> Any:
    if obj is None:
        return None
    if isinstance(obj, Enum):
        return obj.value
    if dataclasses.is_dataclass(obj):
        return {f.name: to_dict(getattr(obj, f.name)) for f in dataclasses.fields(obj)}
    if isinstance(obj, list):
        return [to_dict(item) for item in obj]
    if isinstance(obj, tuple):
        return [to_dict(item) for item in obj]
    if isinstance(obj, dict):
        return {key: to_dict(value) for key, value in obj.items()}
    return obj


def from_dict(cls: type, data: Any) -> Any:
    hints = get_type_hints(cls)
    kwargs: dict[str, Any] = {}
    for name, field_type in hints.items():
        if name not in data:
            continue
        kwargs[name] = _coerce(field_type, data[name])
    return cls(**kwargs)


def _coerce(field_type: type, value: Any) -> Any:
    if value is None:
        return None

    origin = get_origin(field_type)

    if origin is Union:
        args = [a for a in get_args(field_type) if a is not _NONE_TYPE]
        if not args:
            return value
        return _coerce(args[0], value)

    if origin in (list, tuple):
        inner = get_args(field_type)[0] if get_args(field_type) else Any
        return [_coerce(inner, item) for item in value]

    if origin is dict:
        return value

    if isinstance(field_type, type):
        if issubclass(field_type, Enum):
            return field_type(value)
        if dataclasses.is_dataclass(field_type):
            return from_dict(field_type, value)

    return value


def to_json(obj: Any) -> str:
    return json.dumps(to_dict(obj), ensure_ascii=False)


def from_json(cls: type, data: str) -> Any:
    return from_dict(cls, json.loads(data))


def to_json_pretty(obj: Any) -> str:
    return json.dumps(to_dict(obj), ensure_ascii=False, indent=2)
