"""Final editorial pass from engine state to a human-readable debate report."""

from __future__ import annotations

import json
import re
from importlib.resources import files
from typing import Any

from ..ports.llm import LLMPort


REPORT_TOOL = {
    "type": "function",
    "function": {
        "name": "submit_reader_report",
        "description": "提交经过重写、可直接供人阅读和备赛的完整中文报告。",
        "parameters": {
            "type": "object",
            "required": ["title", "opening_summary", "motion", "sides", "clashes", "preparation", "limitations"],
            "properties": {
                "title": {"type": "string"},
                "opening_summary": {"type": "array", "items": {"type": "string"}, "minItems": 2},
                "motion": {
                    "type": "object",
                    "required": ["core_question", "definitions", "decision_rule", "burdens"],
                    "properties": {
                        "core_question": {"type": "string"},
                        "definitions": {"type": "array", "items": {"type": "string"}},
                        "decision_rule": {"type": "string"},
                        "burdens": {
                            "type": "object",
                            "properties": {
                                "affirmative": {"type": "array", "items": {"type": "string"}},
                                "negative": {"type": "array", "items": {"type": "string"}},
                            },
                        },
                    },
                },
                "sides": {
                    "type": "object",
                    "required": ["affirmative", "negative"],
                    "properties": {
                        "affirmative": {"$ref": "#/definitions/side"},
                        "negative": {"$ref": "#/definitions/side"},
                    },
                },
                "clashes": {"type": "array", "items": {"$ref": "#/definitions/clash"}},
                "preparation": {
                    "type": "object",
                    "properties": {
                        "affirmative": {"$ref": "#/definitions/preparation"},
                        "negative": {"$ref": "#/definitions/preparation"},
                    },
                },
                "limitations": {"type": "array", "items": {"type": "string"}},
            },
            "definitions": {
                "side": {
                    "type": "object",
                    "required": ["position", "case_thesis", "arguments", "rebuttals"],
                    "properties": {
                        "position": {"type": "string"},
                        "case_thesis": {"type": "string"},
                        "arguments": {"type": "array", "items": {"$ref": "#/definitions/argument"}},
                        "rebuttals": {"type": "array", "items": {"$ref": "#/definitions/rebuttal"}},
                    },
                },
                "argument": {
                    "type": "object",
                    "required": ["title", "claim", "reasoning", "support", "strategic_value", "boundary", "challenge", "response"],
                    "properties": {
                        "title": {"type": "string"}, "claim": {"type": "string"},
                        "reasoning": {"type": "array", "items": {"type": "string"}},
                        "support": {"type": "array", "items": {"type": "string"}},
                        "strategic_value": {"type": "string"}, "boundary": {"type": "string"},
                        "challenge": {"type": "string"}, "response": {"type": "string"},
                    },
                },
                "rebuttal": {
                    "type": "object",
                    "required": ["target", "opponent_case", "answer", "impact"],
                    "properties": {
                        "target": {"type": "string"}, "opponent_case": {"type": "string"},
                        "answer": {"type": "string"}, "impact": {"type": "string"},
                    },
                },
                "clash": {
                    "type": "object",
                    "required": ["question", "affirmative_answer", "negative_answer", "deciding_test"],
                    "properties": {
                        "question": {"type": "string"}, "affirmative_answer": {"type": "string"},
                        "negative_answer": {"type": "string"}, "deciding_test": {"type": "string"},
                    },
                },
                "preparation": {
                    "type": "object",
                    "properties": {
                        "opening_order": {"type": "array", "items": {"type": "string"}},
                        "rebuttal_priorities": {"type": "array", "items": {"type": "string"}},
                        "cross_examination": {"type": "array", "items": {"type": "string"}},
                    },
                },
            },
        },
    },
}

MARKDOWN_REPORT_TOOL = {
    "type": "function",
    "function": {
        "name": "submit_reader_report",
        "description": "提交一份已经彻底重写、可供普通读者直接阅读和备赛的完整 Markdown 报告。",
        "parameters": {
            "type": "object",
            "required": ["title", "markdown"],
            "properties": {
                "title": {"type": "string"},
                "markdown": {
                    "type": "string",
                    "description": "完整中文报告，从一级标题开始，不含代码围栏、内部编号、状态标签或运行过程。",
                },
            },
        },
    },
}


def _clean(value: Any) -> str:
    return " ".join(str(value or "").split())


def _active(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [item for item in items if item.get("status") not in {"withdrawn", "answered"}]


def build_editorial_packet(data: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Build a compact packet with no engine ids, histories, versions or tool traces."""

    evidence_by_id = {
        item.get("evidence_id"): item
        for side in ("A", "B") for item in (data.get("evidence", {}).get(side) or [])
    }
    source_by_id = {item.get("source_id"): item for item in data.get("sources") or []}
    used_source_ids: list[str] = []

    def cite_evidence(ids: list[str]) -> list[str]:
        output = []
        for evidence_id in ids or []:
            item = evidence_by_id.get(evidence_id) or {}
            source_id = item.get("source_id")
            if source_id and source_id not in used_source_ids:
                used_source_ids.append(source_id)
            finding = _clean(item.get("finding"))
            if finding:
                output.append(finding + (f"（限制：{_clean(item.get('limitations'))}）" if item.get("limitations") else ""))
        return output

    argument_titles = {
        item.get("argument_id"): _clean(item.get("title"))
        for side in ("A", "B") for item in (data.get("arguments", {}).get(side) or [])
    }
    sides: dict[str, Any] = {}
    for side in ("A", "B"):
        arguments = []
        for item in _active(data.get("arguments", {}).get(side) or []):
            for source_id in item.get("material_source_ids") or []:
                if source_id in source_by_id and source_id not in used_source_ids:
                    used_source_ids.append(source_id)
            arguments.append({
                "title": _clean(item.get("title")), "claim": _clean(item.get("claim")),
                "what_must_be_proved": _clean(item.get("burden")),
                "reasoning": [_clean(value) for value in item.get("warrant") or [] if _clean(value)],
                "criterion": _clean(item.get("criterion")),
                "original_insight": _clean(item.get("original_contribution")),
                "evidence": cite_evidence(item.get("evidence_ids") or []),
                "strategic_value": _clean(item.get("impact")), "boundary": _clean(item.get("scope")),
                "vulnerabilities": [_clean(value) for value in item.get("vulnerabilities") or [] if _clean(value)],
                "defenses": [_clean(value) for value in item.get("defense") or [] if _clean(value)],
            })
        rebuttals = []
        for item in _active(data.get("rebuttals", {}).get(side) or []):
            rebuttals.append({
                "target": argument_titles.get(item.get("target_argument_id"), "对方相关论点"),
                "opponent_case": _clean(item.get("reconstruction")), "answer": _clean(item.get("attack")),
                "why_it_matters": _clean(item.get("why_it_matters")),
                "likely_reply": _clean(item.get("likely_response")),
                "current_assessment": _clean(item.get("current_effect")),
                "evidence": cite_evidence(item.get("evidence_ids") or []),
            })
        sides[side] = {"arguments": arguments, "rebuttals": rebuttals}

    sources = []
    for index, source_id in enumerate(used_source_ids, 1):
        source = source_by_id[source_id]
        sources.append({"number": index, "title": _clean(source.get("title")), "url": str(source.get("url") or "")})
    # Add stable citation numbers only after the source set is fixed.
    source_number = {source_id: index + 1 for index, source_id in enumerate(used_source_ids)}
    for side in ("A", "B"):
        source_arguments = _active(data.get("arguments", {}).get(side) or [])
        for output, original in zip(sides[side]["arguments"], source_arguments):
            output["helpful_materials"] = [
                f"[{source_number[source_id]}] {_clean(source_by_id[source_id].get('title'))}"
                for source_id in original.get("material_source_ids") or [] if source_id in source_number
            ]

    session = data.get("session") or {}
    packet = {
        "question": _clean(session.get("question")),
        "affirmative_position": _clean(session.get("position_a")),
        "negative_position": _clean(session.get("position_b")),
        "affirmative_material": sides["A"], "negative_material": sides["B"],
        "sources": sources,
    }
    return packet, sources


def _fallback_report(packet: dict[str, Any]) -> dict[str, Any]:
    """Produce a clean usable report even if the final editor request fails."""

    def side(key: str, position_key: str) -> dict[str, Any]:
        material = packet[key]
        arguments = []
        for item in material["arguments"]:
            support = list(item.get("evidence") or []) + list(item.get("helpful_materials") or [])
            arguments.append({
                "title": item["title"], "claim": item["claim"],
                "reasoning": item.get("reasoning") or [item.get("what_must_be_proved") or item["claim"]],
                "support": support, "strategic_value": item.get("strategic_value") or "该论点用于建立本方的比较优势。",
                "boundary": item.get("boundary") or "需结合题目定义和具体场景使用。",
                "challenge": "；".join(item.get("vulnerabilities") or []) or "需要防止对方质疑前提或影响权重。",
                "response": "；".join(item.get("defenses") or []) or "应回到完整证明链和双方比较标准作答。",
            })
        rebuttals = [{
            "target": item["target"], "opponent_case": item["opponent_case"],
            "answer": item["answer"], "impact": item["why_it_matters"],
        } for item in material["rebuttals"]]
        thesis = arguments[0]["claim"] if arguments else packet[position_key]
        return {"position": packet[position_key], "case_thesis": thesis, "arguments": arguments, "rebuttals": rebuttals}

    affirmative = side("affirmative_material", "affirmative_position")
    negative = side("negative_material", "negative_position")
    return {
        "title": packet["question"],
        "opening_summary": [
            f"本题要求比较“{packet['affirmative_position']}”与“{packet['negative_position']}”哪一种判断更有说服力。",
            "阅读时应重点检验双方的概念界定、因果链是否完整，以及各项影响在题设范围内谁更重要。",
        ],
        "motion": {"core_question": packet["question"], "definitions": [], "decision_rule": "比较双方论证在题设范围内的解释力、可信度与影响权重。", "burdens": {"affirmative": [packet["affirmative_position"]], "negative": [packet["negative_position"]]}},
        "sides": {"affirmative": affirmative, "negative": negative},
        "clashes": [],
        "preparation": {
            "affirmative": {"opening_order": [item["title"] for item in affirmative["arguments"]], "rebuttal_priorities": [item["target"] for item in affirmative["rebuttals"]], "cross_examination": []},
            "negative": {"opening_order": [item["title"] for item in negative["arguments"]], "rebuttal_priorities": [item["target"] for item in negative["rebuttals"]], "cross_examination": []},
        },
        "limitations": ["终稿编辑请求未能完成，本报告已使用清洗后的当前成果自动编排；论证内容仍完整保留。"],
    }


def _valid_report(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    if isinstance(value.get("markdown"), str):
        markdown = value["markdown"].strip()
        required_sections = (
            "## 先读结论", "## 这道题究竟在争什么", "## 正方", "## 反方",
            "## 真正决定比赛的交锋", "## 怎样把研究转成赛场表达", "## 使用前仍需注意",
        )
        return (
            4_000 <= len(markdown) <= 16_000
            and markdown.startswith("#")
            and all(section in markdown for section in required_sections)
        )
    return all(key in value for key in (
        "title", "opening_summary", "motion", "sides", "clashes", "preparation", "limitations"
    )) and all(key in value.get("sides", {}) for key in ("affirmative", "negative"))


def _remove_internal_labels(text: str, data: dict[str, Any]) -> str:
    """Translate engine-only identifiers that a final editor may copy verbatim."""

    replacements: dict[str, str] = {}
    for side in ("A", "B"):
        for item in data.get("arguments", {}).get(side) or []:
            internal_id = str(item.get("argument_id") or "").strip()
            title = _clean(item.get("title"))
            if internal_id:
                replacements[internal_id] = f"“{title}”" if title else "相关论点"
        for item in data.get("rebuttals", {}).get(side) or []:
            internal_id = str(item.get("rebuttal_id") or "").strip()
            if internal_id:
                replacements[internal_id] = "相关驳论"
        for item in data.get("maps", {}).get(side) or []:
            internal_id = str(item.get("map_id") or "").strip()
            if internal_id:
                replacements[internal_id] = "相关研究限制"
        for item in data.get("units", {}).get(side) or []:
            internal_id = str(item.get("unit_id") or "").strip()
            if internal_id:
                replacements[internal_id] = "本方整体立论"
    for internal_id in sorted(replacements, key=len, reverse=True):
        text = text.replace(internal_id, replacements[internal_id])
    return re.sub(
        r"(?i)\b(?:arg|map|reb|ru|mut)_[a-z0-9_-]+\b",
        "相关论证",
        text,
    )


async def compile_reader_report(data: dict[str, Any], llm: LLMPort) -> tuple[dict[str, Any], dict[str, Any]]:
    """Ask a neutral final editor to rewrite the current state, with a safe fallback."""

    packet, sources = build_editorial_packet(data)
    prompt = files("cre.prompts").joinpath("report_editor.md").read_text(encoding="utf-8")
    try:
        turn = await llm.run([
            {"role": "system", "content": prompt},
            {"role": "user", "content": "以下是终稿素材包。只使用其中内容，直接输出完整 Markdown 成稿；不要输出 JSON、代码围栏或编辑说明。\n\n" + json.dumps(packet, ensure_ascii=False)},
        ], [])
        text = re.sub(r"^```(?:markdown|md)?\s*|\s*```$", "", turn.text.strip(), flags=re.I)
        report = {"title": packet["question"], "markdown": text}
        if not _valid_report(report):
            raise ValueError("final editor did not return the complete report contract")
        if report.get("markdown"):
            report["markdown"] = _remove_internal_labels(report["markdown"], data)
            source_lines = ["", "## 来源目录", ""]
            if not sources:
                source_lines.append("这份报告的核心内容由逻辑推演形成，没有外部来源进入最终论证。")
            for source in sources:
                source_lines.append(
                    f"{source['number']}. **{source['title'] or f'来源 {source['number']}'}**"
                    + (f"  \n   {source['url']}" if source.get("url") else "")
                )
            report["markdown"] = report["markdown"].strip() + "\n" + "\n".join(source_lines) + "\n"
        report["sources"] = sources
        return report, {"mode": "model_edited", "input_tokens": turn.usage.input_tokens, "output_tokens": turn.usage.output_tokens, "error": ""}
    except Exception as exc:
        report = _fallback_report(packet)
        report["sources"] = sources
        return report, {"mode": "deterministic_fallback", "input_tokens": 0, "output_tokens": 0, "error": str(exc)[:500]}
