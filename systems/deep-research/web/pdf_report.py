"""Generate a polished, standalone PDF from CRE's current public result."""

from __future__ import annotations

from html import escape
from io import BytesIO
import re
from typing import Any

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.platypus import (
    KeepTogether,
    ListFlowable,
    ListItem,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
)


FONT = "STSong-Light"
pdfmetrics.registerFont(UnicodeCIDFont(FONT))


def _clean(value: Any) -> str:
    return " ".join(str(value or "").split())


def _p(value: Any) -> str:
    return escape(_clean(value))


def _build_reader_pdf(data: dict[str, Any]) -> bytes:
    report = data["reader_report"]
    output = BytesIO()
    document = SimpleDocTemplate(
        output, pagesize=A4, rightMargin=22 * mm, leftMargin=22 * mm,
        topMargin=22 * mm, bottomMargin=20 * mm,
        title=_clean(report.get("title")) + " - 研究总报告", author="论衡研究引擎",
    )
    base = getSampleStyleSheet()
    body = ParagraphStyle("ReaderBodyCN", parent=base["BodyText"], fontName=FONT, fontSize=10.5, leading=18, textColor=colors.HexColor("#252a30"), wordWrap="CJK", spaceAfter=8)
    title = ParagraphStyle("ReaderTitleCN", parent=body, fontSize=24, leading=34, alignment=TA_CENTER, textColor=colors.HexColor("#173c35"), spaceAfter=18)
    subtitle = ParagraphStyle("ReaderSubtitleCN", parent=body, fontSize=12, leading=21, alignment=TA_CENTER, textColor=colors.HexColor("#59645f"), spaceAfter=20)
    h1 = ParagraphStyle("ReaderH1CN", parent=body, fontSize=17, leading=25, textColor=colors.HexColor("#173c35"), spaceBefore=16, spaceAfter=12)
    h2 = ParagraphStyle("ReaderH2CN", parent=body, fontSize=13, leading=21, textColor=colors.HexColor("#315c55"), spaceBefore=11, spaceAfter=7)
    label = ParagraphStyle("ReaderLabelCN", parent=body, fontSize=10, leading=17, textColor=colors.HexColor("#315c55"), spaceBefore=5, spaceAfter=2)
    note = ParagraphStyle("ReaderNoteCN", parent=body, fontSize=9.5, leading=16, textColor=colors.HexColor("#59645f"), leftIndent=8, rightIndent=8, borderColor=colors.HexColor("#dbe5e1"), borderWidth=0.7, borderPadding=8, backColor=colors.HexColor("#f4f7f6"), spaceAfter=12)
    source_style = ParagraphStyle("ReaderSourceCN", parent=body, fontSize=8.8, leading=14, textColor=colors.HexColor("#44504c"), wordWrap="CJK")

    if report.get("markdown"):
        def inline(value: str) -> str:
            rendered = escape(value)
            rendered = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", rendered)
            rendered = re.sub(
                r"\[([^\]]+)\]\((https?://[^)]+)\)",
                r"<link href='\2' color='#276b91'>\1</link>", rendered,
            )
            return rendered

        story: list[Any] = []
        first_heading = True
        for raw in str(report["markdown"]).splitlines():
            line = raw.strip()
            if not line or line == "---":
                continue
            heading = re.match(r"^(#{1,4})\s+(.+)$", line)
            if heading:
                level = len(heading.group(1))
                text = inline(heading.group(2))
                if level == 1:
                    if not first_heading:
                        story.append(PageBreak())
                    story.extend([Spacer(1, 10 * mm), Paragraph(text, title)])
                    first_heading = False
                elif level == 2:
                    story.append(Paragraph(text, h1))
                else:
                    story.append(Paragraph(text, h2))
                continue
            if line.startswith("> "):
                story.append(Paragraph(inline(line[2:]), note))
                continue
            bullet = re.match(r"^[-*]\s+(.+)$", line)
            numbered = re.match(r"^\d+\.\s+(.+)$", line)
            if bullet:
                story.append(Paragraph("• " + inline(bullet.group(1)), body))
            elif numbered:
                story.append(Paragraph(inline(line), body))
            else:
                story.append(Paragraph(inline(line), body))

        def page_footer(canvas, doc):
            canvas.saveState(); canvas.setFont(FONT, 8); canvas.setFillColor(colors.HexColor("#75807c"))
            canvas.drawString(22 * mm, 10 * mm, "论衡 · 双边辩题研究总报告")
            canvas.drawRightString(A4[0] - 22 * mm, 10 * mm, f"第 {doc.page} 页"); canvas.restoreState()

        document.build(story, onFirstPage=page_footer, onLaterPages=page_footer)
        return output.getvalue()

    story: list[Any] = [
        Spacer(1, 22 * mm), Paragraph("双边辩题研究总报告", title),
        Paragraph(_p(report.get("title")), subtitle),
        Paragraph("本报告在研究完成后经过独立终稿编辑。运行轨迹、内部标签、历史版本和模型工作描述均未收入正文。", note),
        Paragraph("一、先读结论", h1),
    ]
    for paragraph in report.get("opening_summary") or []:
        story.append(Paragraph(_p(paragraph), body))

    motion = report.get("motion") or {}
    story.extend([Paragraph("二、这道题究竟在争什么", h1), Paragraph(_p(motion.get("core_question")), body)])
    if motion.get("definitions"):
        story.extend([Paragraph("需要先说清的概念", label), ListFlowable([ListItem(Paragraph(_p(item), body)) for item in motion["definitions"]], bulletType="bullet", leftIndent=17)])
    if motion.get("decision_rule"):
        story.extend([Paragraph("判断胜负的标准", label), Paragraph(_p(motion["decision_rule"]), body)])
    for key, name in (("affirmative", "正方必须完成的证明"), ("negative", "反方必须完成的证明")):
        items = (motion.get("burdens") or {}).get(key) or []
        if items:
            story.extend([Paragraph(name, label), ListFlowable([ListItem(Paragraph(_p(item), body)) for item in items], bulletType="bullet", leftIndent=17)])

    for key, side_name, chapter in (("affirmative", "正方", "三"), ("negative", "反方", "四")):
        side = (report.get("sides") or {}).get(key) or {}
        story.extend([PageBreak(), Paragraph(f"{chapter}、{side_name}如何把立场立住", h1), Paragraph(f"<b>立场：</b>{_p(side.get('position'))}", note), Paragraph(_p(side.get("case_thesis")), body)])
        for index, argument in enumerate(side.get("arguments") or [], 1):
            block: list[Any] = [Paragraph(f"{index}. {_p(argument.get('title'))}", h2), Paragraph(_p(argument.get("claim")), body)]
            reasoning = argument.get("reasoning") or []
            if reasoning:
                block.extend([Paragraph("完整证明链", label), ListFlowable([ListItem(Paragraph(_p(item), body)) for item in reasoning], bulletType="1", start="1", leftIndent=17)])
            support = argument.get("support") or []
            if support:
                block.extend([Paragraph("可用材料", label), ListFlowable([ListItem(Paragraph(_p(item), body)) for item in support], bulletType="bullet", leftIndent=17)])
            for field, field_name in (("strategic_value", "为什么影响胜负"), ("boundary", "这套论证的边界"), ("challenge", "对方最强的质疑"), ("response", "本方应如何回应")):
                if argument.get(field):
                    block.extend([Paragraph(field_name, label), Paragraph(_p(argument[field]), body)])
            story.append(KeepTogether(block[:2]))
            story.extend(block[2:])
        rebuttals = side.get("rebuttals") or []
        if rebuttals:
            story.append(Paragraph(f"{side_name}的优先反驳", h2))
        for index, item in enumerate(rebuttals, 1):
            story.extend([
                Paragraph(f"{index}. 回应“{_p(item.get('target'))}”", h2),
                Paragraph(f"<b>先准确理解对方：</b>{_p(item.get('opponent_case'))}", body),
                Paragraph(f"<b>本方回答：</b>{_p(item.get('answer'))}", body),
                Paragraph(f"<b>这为什么重要：</b>{_p(item.get('impact'))}", body),
            ])

    story.extend([PageBreak(), Paragraph("五、真正决定比赛的交锋", h1)])
    for index, clash in enumerate(report.get("clashes") or [], 1):
        story.extend([
            Paragraph(f"{index}. {_p(clash.get('question'))}", h2),
            Paragraph(f"<b>正方的答案：</b>{_p(clash.get('affirmative_answer'))}", body),
            Paragraph(f"<b>反方的答案：</b>{_p(clash.get('negative_answer'))}", body),
            Paragraph(f"<b>裁判应检验：</b>{_p(clash.get('deciding_test'))}", note),
        ])
    story.append(Paragraph("六、怎样把研究转成赛场表达", h1))
    for key, side_name in (("affirmative", "正方"), ("negative", "反方")):
        prep = (report.get("preparation") or {}).get(key) or {}
        story.append(Paragraph(side_name, h2))
        for field, field_name, ordered in (("opening_order", "立论展开顺序", True), ("rebuttal_priorities", "优先处理的攻防", False), ("cross_examination", "可用于盘问的问题", False)):
            items = prep.get(field) or []
            if items:
                story.extend([Paragraph(field_name, label), ListFlowable([ListItem(Paragraph(_p(item), body)) for item in items], bulletType="1" if ordered else "bullet", leftIndent=17)])
    if report.get("limitations"):
        story.extend([Paragraph("七、使用前仍需注意", h1), ListFlowable([ListItem(Paragraph(_p(item), body)) for item in report["limitations"]], bulletType="bullet", leftIndent=17)])
    story.append(Paragraph("八、来源目录", h1))
    if not report.get("sources"):
        story.append(Paragraph("这份报告的核心内容由逻辑推演形成，没有外部来源进入最终论证。", body))
    for source in report.get("sources") or []:
        text = f"<b>[{int(source.get('number') or 0)}] {_p(source.get('title'))}</b>"
        if source.get("url"):
            url = escape(str(source["url"]), quote=True)
            text += f"<br/><link href='{url}' color='#276b91'>{url}</link>"
        story.append(Paragraph(text, source_style))

    def page_footer(canvas, doc):
        canvas.saveState(); canvas.setFont(FONT, 8); canvas.setFillColor(colors.HexColor("#75807c"))
        canvas.drawString(22 * mm, 10 * mm, "论衡 · 双边辩题研究总报告")
        canvas.drawRightString(A4[0] - 22 * mm, 10 * mm, f"第 {doc.page} 页"); canvas.restoreState()

    document.build(story, onFirstPage=page_footer, onLaterPages=page_footer)
    return output.getvalue()


def build_pdf_report(data: dict[str, Any]) -> bytes:
    """Return a readable A4 PDF; internal ids and mutation history are omitted."""

    if data.get("reader_report"):
        return _build_reader_pdf(data)

    output = BytesIO()
    document = SimpleDocTemplate(
        output,
        pagesize=A4,
        rightMargin=22 * mm,
        leftMargin=22 * mm,
        topMargin=22 * mm,
        bottomMargin=20 * mm,
        title=_clean(data.get("session", {}).get("question")) + " - 研究总报告",
        author="论衡研究引擎",
    )
    base = getSampleStyleSheet()
    body = ParagraphStyle("BodyCN", parent=base["BodyText"], fontName=FONT, fontSize=10.5, leading=18, textColor=colors.HexColor("#252a30"), wordWrap="CJK", spaceAfter=7)
    title = ParagraphStyle("TitleCN", parent=body, fontSize=24, leading=34, alignment=TA_CENTER, textColor=colors.HexColor("#173c35"), spaceAfter=18)
    subtitle = ParagraphStyle("SubtitleCN", parent=body, fontSize=12, leading=21, alignment=TA_CENTER, textColor=colors.HexColor("#59645f"), spaceAfter=20)
    h1 = ParagraphStyle("H1CN", parent=body, fontSize=17, leading=25, textColor=colors.HexColor("#173c35"), spaceBefore=16, spaceAfter=12, borderWidth=0, borderPadding=0)
    h2 = ParagraphStyle("H2CN", parent=body, fontSize=13, leading=21, textColor=colors.HexColor("#315c55"), spaceBefore=11, spaceAfter=7)
    label = ParagraphStyle("LabelCN", parent=body, fontSize=10, leading=17, textColor=colors.HexColor("#315c55"), spaceBefore=4, spaceAfter=2)
    note = ParagraphStyle("NoteCN", parent=body, fontSize=9.5, leading=16, textColor=colors.HexColor("#59645f"), leftIndent=8, rightIndent=8, borderColor=colors.HexColor("#dbe5e1"), borderWidth=0.7, borderPadding=8, backColor=colors.HexColor("#f4f7f6"), spaceAfter=12)
    source_style = ParagraphStyle("SourceCN", parent=body, fontSize=8.8, leading=14, textColor=colors.HexColor("#44504c"), wordWrap="CJK")

    session = data.get("session") or {}
    all_sources = data.get("sources") or []
    evidence = data.get("evidence") or {}
    arguments = data.get("arguments") or {}
    rebuttals = data.get("rebuttals") or {}
    argument_by_id = {item.get("argument_id"): item for side in ("A", "B") for item in arguments.get(side, [])}
    evidence_by_id = {
        item.get("evidence_id"): item
        for side in ("A", "B") for item in evidence.get(side, [])
    }
    used_source_ids: set[str] = set()
    for side in ("A", "B"):
        for argument in arguments.get(side, []):
            used_source_ids.update(argument.get("material_source_ids") or [])
            for evidence_id in argument.get("evidence_ids") or []:
                item = evidence_by_id.get(evidence_id) or {}
                if item.get("source_id"):
                    used_source_ids.add(item["source_id"])
        for rebuttal in rebuttals.get(side, []):
            for evidence_id in rebuttal.get("evidence_ids") or []:
                item = evidence_by_id.get(evidence_id) or {}
                if item.get("source_id"):
                    used_source_ids.add(item["source_id"])
    sources = [item for item in all_sources if item.get("source_id") in used_source_ids]
    source_by_id = {item.get("source_id"): (index + 1, item) for index, item in enumerate(sources)}

    def citations(ids: list[str] | None) -> str:
        numbers = [str(source_by_id[item][0]) for item in (ids or []) if item in source_by_id]
        return " [" + ", ".join(numbers) + "]" if numbers else ""

    def evidence_citations(ids: list[str] | None) -> str:
        return citations([
            evidence_by_id[item].get("source_id")
            for item in (ids or []) if item in evidence_by_id
        ])

    story: list[Any] = [
        Spacer(1, 24 * mm),
        Paragraph("双边辩题研究总报告", title),
        Paragraph(_p(session.get("question")), subtitle),
        Paragraph("这是一份经过清洗的用户报告。模型对话、内部编号、版本记录、工单与运行过程均未收入正文。", note),
        Spacer(1, 12 * mm),
        Paragraph("报告摘要", h1),
        Paragraph(f"<b>正方立场：</b>{_p(session.get('position_a'))}", body),
        Paragraph(f"<b>反方立场：</b>{_p(session.get('position_b'))}", body),
        Paragraph(f"本轮形成 {sum(len(arguments.get(side, [])) for side in ('A', 'B'))} 个核心论点、{sum(len(rebuttals.get(side, [])) for side in ('A', 'B'))} 个主要攻防点，并有 {len(sources)} 个来源实际进入成果。", body),
        Paragraph("双方的关键分歧集中在核心概念的界定、比较标准的选择，以及不同影响在具体场景中的权重。正文按主张、证明链、证据、适用边界和交锋关系重新组织。", body),
    ]

    for side, side_name, chapter in (("A", "正方", "一"), ("B", "反方", "二")):
        story.extend([PageBreak(), Paragraph(f"{chapter}、{side_name}完整立论", h1), Paragraph(f"<b>立场：</b>{_p(session.get('position_a' if side == 'A' else 'position_b'))}", note)])
        for index, argument in enumerate(arguments.get(side, []), 1):
            block: list[Any] = [
                Paragraph(f"{index}. {_p(argument.get('title'))}", h2),
                Paragraph("核心主张", label), Paragraph(_p(argument.get("claim")), body),
                Paragraph("需要证明什么", label), Paragraph(_p(argument.get("burden")), body),
            ]
            support_type = argument.get("support_type") or "mixed"
            if support_type == "reasoning":
                support_label = "自主逻辑论证：主要依靠定义、推理、比较与反例成立，无需用引用装饰。"
            elif argument.get("evidence_ids"):
                support_label = "事实与逻辑混合论证：事实前提已绑定经过检查的证据。"
            else:
                support_label = "尚在修建：论证包含尚未完成核验的事实前提。"
            block.extend([Paragraph("论证性质", label), Paragraph(_p(support_label), body)])
            if support_type != "reasoning" and not argument.get("evidence_ids"):
                needs = argument.get("evidence_need") or ["该论点含有事实性前提，但尚未明确完成核验。"]
                block.extend([
                    Paragraph("尚待核验的事实前提", label),
                    ListFlowable(
                        [ListItem(Paragraph(_p(item), body)) for item in needs],
                        bulletType="bullet", leftIndent=17,
                    ),
                ])
            if argument.get("criterion"):
                block.extend([Paragraph("判断标准", label), Paragraph(_p(argument.get("criterion")), body)])
            if argument.get("original_contribution"):
                block.extend([
                    Paragraph("本论点自己的推进", label),
                    Paragraph(_p(argument.get("original_contribution")), body),
                ])
            warrants = argument.get("warrant") or []
            if warrants:
                block.extend([Paragraph("论证链条", label), ListFlowable([ListItem(Paragraph(_p(step), body)) for step in warrants], bulletType="1", start="1", leftIndent=17)])
            evidence_items = []
            evidence_ids = set(argument.get("evidence_ids") or [])
            for item in evidence.get(side, []):
                if item.get("evidence_id") not in evidence_ids:
                    continue
                text = _p(item.get("finding")) + citations([item.get("source_id")])
                if item.get("limitations"):
                    text += f"<br/><font color='#66706c'>适用限制：{_p(item.get('limitations'))}</font>"
                evidence_items.append(ListItem(Paragraph(text, body)))
            if evidence_items:
                block.extend([Paragraph("证据支持", label), ListFlowable(evidence_items, bulletType="bullet", leftIndent=17)])
            material_items = []
            for source_id in argument.get("material_source_ids") or []:
                source = source_by_id.get(source_id)
                if source:
                    material_items.append(ListItem(Paragraph(
                        _p(source[1].get("title")) + citations([source_id]), body
                    )))
            if material_items:
                block.extend([
                    Paragraph("帮助形成或检验本论点的材料（不作为事实背书）", label),
                    ListFlowable(material_items, bulletType="bullet", leftIndent=17),
                ])
            block.extend([Paragraph("比较意义", label), Paragraph(_p(argument.get("impact")), body), Paragraph("适用边界", label), Paragraph(_p(argument.get("scope")), body)])
            vulnerabilities = argument.get("vulnerabilities") or []
            defenses = argument.get("defense") or []
            if vulnerabilities:
                block.extend([Paragraph("需要主动防守的薄弱处", label), ListFlowable([ListItem(Paragraph(_p(item), body)) for item in vulnerabilities], bulletType="bullet", leftIndent=17)])
            if defenses:
                block.extend([Paragraph("目前可采用的防守", label), ListFlowable([ListItem(Paragraph(_p(item), body)) for item in defenses], bulletType="bullet", leftIndent=17)])
            story.append(KeepTogether(block[:4]))
            story.extend(block[4:])

    story.extend([PageBreak(), Paragraph("三、双方核心交锋", h1), Paragraph("以下只呈现已经与对方当前立论对齐的有效攻防，不呈现模型原始讨论。", note)])
    for side, side_name in (("A", "正方"), ("B", "反方")):
        story.append(Paragraph(f"{side_name}对对方的主要回应", h2))
        items = rebuttals.get(side, [])
        if not items:
            story.append(Paragraph("当前尚无形成完整结构的回应。", body))
        for index, item in enumerate(items, 1):
            target = argument_by_id.get(item.get("target_argument_id")) or {}
            story.extend([
                Paragraph(f"{index}. {_p(item.get('title'))}", h2),
                Paragraph(f"<b>回应对象：</b>{_p(target.get('title'))}", body),
                Paragraph(f"<b>对方主张的准确重述：</b>{_p(item.get('reconstruction'))}", body),
                Paragraph(f"<b>主要反驳：</b>{_p(item.get('attack'))}", body),
                Paragraph(f"<b>为什么影响胜负：</b>{_p(item.get('why_it_matters'))}{evidence_citations(item.get('evidence_ids'))}", body),
            ])
            if item.get("likely_response"):
                story.append(Paragraph(f"<b>对方可能的修复：</b>{_p(item.get('likely_response'))}", body))
            if item.get("current_effect"):
                story.append(Paragraph(f"<b>当前攻防结论：</b>{_p(item.get('current_effect'))}", note))

    story.extend([Paragraph("四、阅读与使用边界", h1), ListFlowable([
        ListItem(Paragraph("这些结论是立场条件下的可辩护论证，不是替代裁判判断的唯一答案。", body)),
        ListItem(Paragraph("证据应结合研究对象、方法和适用范围使用，不应把相关关系自动写成因果关系。", body)),
        ListItem(Paragraph("已经暴露但尚未完全修复的薄弱处，应优先纳入后续备赛。", body)),
    ], bulletType="bullet", leftIndent=17), Paragraph("五、来源目录", h1)])
    if not sources:
        story.append(Paragraph("当前成果主要由逻辑推演形成，没有需要列入正文的外部来源。", body))
    for index, source in enumerate(sources, 1):
        text = f"<b>[{index}] {_p(source.get('title') or f'来源 {index}')}</b>"
        if source.get("url"):
            url = escape(str(source["url"]), quote=True)
            text += f"<br/><link href='{url}' color='#276b91'>{url}</link>"
        story.append(Paragraph(text, source_style))

    def page_footer(canvas, doc):
        canvas.saveState()
        canvas.setFont(FONT, 8)
        canvas.setFillColor(colors.HexColor("#75807c"))
        canvas.drawString(22 * mm, 10 * mm, "论衡 · 双边辩题研究总报告")
        canvas.drawRightString(A4[0] - 22 * mm, 10 * mm, f"第 {doc.page} 页")
        canvas.restoreState()

    document.build(story, onFirstPage=page_footer, onLaterPages=page_footer)
    return output.getvalue()
