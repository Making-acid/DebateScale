"""Load editable prompt resources without embedding research policy in Python."""

from __future__ import annotations

from functools import lru_cache
from importlib.resources import files
from pathlib import PurePosixPath


_PROMPT_PACKAGE = "cre.prompts"


@lru_cache(maxsize=64)
def load_prompt(name: str) -> str:
    """Return one UTF-8 prompt resource by its package-relative path."""

    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts or not path.parts:
        raise ValueError(f"invalid prompt resource path: {name!r}")
    return files(_PROMPT_PACKAGE).joinpath(*path.parts).read_text(encoding="utf-8").strip()


def render_prompt(name: str, **values: object) -> str:
    """Load a prompt and substitute its declared runtime variables."""

    return load_prompt(name).format_map(values)
