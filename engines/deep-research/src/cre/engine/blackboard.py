"""Blackboard projection: serialize units / map entries to Markdown files.

Frontmatter holds only control fields (+ agent-facing metadata for map entries);
cognitive content lives in the Markdown body. Frontmatter is a single JSON line
between ``---`` fences (stdlib only, no YAML dependency).
"""

from __future__ import annotations

import json

from ..models import MapStatus, ResearchMapEntry, ResearchUnit, UnitStatus

_FM = "---"


def _split(text: str) -> tuple[dict, str]:
    lines = text.split("\n")
    if not lines or lines[0].strip() != _FM:
        return {}, text
    end = -1
    for i in range(1, len(lines)):
        if lines[i].strip() == _FM:
            end = i
            break
    if end <= 0:
        return {}, text
    fm_json = "\n".join(lines[1:end]).strip()
    meta = json.loads(fm_json) if fm_json else {}
    body = "\n".join(lines[end + 1 :]).lstrip("\n")
    return meta, body


def unit_to_markdown(unit: ResearchUnit) -> str:
    meta = {
        "unit_id": unit.unit_id,
        "status": unit.status.value,
        "source_ids": unit.source_ids,
    }
    fm = json.dumps(meta, ensure_ascii=False)
    return f"{_FM}\n{fm}\n{_FM}\n\n{unit.content}"


def unit_from_markdown(text: str) -> ResearchUnit:
    meta, body = _split(text)
    return ResearchUnit(
        unit_id=meta["unit_id"],
        status=UnitStatus(meta.get("status", "tentative")),
        source_ids=list(meta.get("source_ids", [])),
        content=body,
    )


def map_to_markdown(entry: ResearchMapEntry) -> str:
    meta = {
        "map_id": entry.map_id,
        "title": entry.title,
        "status": entry.status.value,
        "importance": entry.importance,
        "coverage": entry.coverage,
        "uncertainty": entry.uncertainty,
    }
    fm = json.dumps(meta, ensure_ascii=False)
    return f"{_FM}\n{fm}\n{_FM}\n\n{entry.note}"


def map_from_markdown(text: str) -> ResearchMapEntry:
    meta, body = _split(text)
    return ResearchMapEntry(
        map_id=meta["map_id"],
        title=meta.get("title", ""),
        status=MapStatus(meta.get("status", "active")),
        importance=meta.get("importance"),
        coverage=meta.get("coverage"),
        uncertainty=meta.get("uncertainty"),
        note=body,
    )
