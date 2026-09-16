"""Pioneer test: the LLM source is a human-model reasoning pass, hard-coded.

The engine (runtime / state machine / mutation log / semantic diff / actions)
runs for real; only the LLM turns are scripted from the model author's actual
research decisions, and search returns mock placeholder sources.

Run with:  python examples/pioneer_test.py
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from cre.adapters import InMemoryStore
from cre.engine import MutationLog, Runtime, build_semantic_diff, now_iso
from cre.models import Party, ResearchBudget, ResearchSession, SessionStatus
from cre.ports.llm import LLMTurn, ToolCall
from cre.ports.search import SearchResult, SourceDocument

QUESTION = "表情包在丰富还是虚泛我们的表达？"

# ---------------------------------------------------------------- mock search

SOURCES = {
    "survey": SearchResult(
        title="表情包使用功能分类调查报告",
        url="https://mock.example/survey-func",
        snippet="对 3000 名 18-35 岁用户的问卷：表情包高频用于情绪表达（72%）、语气缓和（58%）、身份标记（41%）。",
    ),
    "nonverbal": SearchResult(
        title="Revisiting nonverbal cues in CMC",
        url="https://mock.example/nonverbal-cmc",
        snippet="文本媒介缺失的非语言线索可被图形符号部分补偿，提升亲密感与幽默传递。",
    ),
    "meme": [
        SearchResult(
            title="模因传播与表达同质化",
            url="https://mock.example/meme-homogenization",
            snippet="热门梗模板的批量复用使表达趋同，个体风格被模板收编。",
        ),
        SearchResult(
            title="数字沟通中的语义稀释假说",
            url="https://mock.example/semantic-dilution",
            snippet="有论者提出高频表情包替代具体词汇组织，可能弱化精确表达能力。",
        ),
    ],
    "measure": [
        SearchResult(
            title="表达质量的操作化测量：综述",
            url="https://mock.example/measurement",
            snippet="'表达丰富度'缺乏统一操作化定义，多数研究使用自我报告。",
        ),
        SearchResult(
            title="语用学视角下的表情符号资源",
            url="https://mock.example/pragmatics",
            snippet="表情符号承担元语用功能：标记反讽、软化请求、管理对话节奏。",
        ),
    ],
}


class MockSearch:
    async def search(self, query: str, n: int = 5):
        # Runtime intentionally expands both positions concurrently. Keep this
        # scripted fixture's stable source ids deterministic without weakening
        # the production engine's parallel execution.
        if "同质" in query or "模因" in query or "测量" in query or "操作化" in query:
            await asyncio.sleep(0.02)
        if "测量" in query or "操作化" in query:
            return list(SOURCES["measure"])
        if "同质" in query or "模因" in query or "稀释" in query:
            return list(SOURCES["meme"])
        if "非语言" in query or "线索" in query:
            return [SOURCES["nonverbal"]]
        return [SOURCES["survey"]]

    async def read(self, url: str) -> SourceDocument:
        all_results = [SOURCES["survey"], SOURCES["nonverbal"], *SOURCES["meme"], *SOURCES["measure"]]
        result = next(item for item in all_results if item.url == url)
        return SourceDocument(
            content=(
                f"演示用已展开材料：{result.title}\n\n{result.snippet}\n\n"
                "正式运行时，此处必须是实际打开并读取的论文、报告、数据集或原始文本正文，"
                "而不是搜索结果摘要。这个演示段落补足可检查正文长度，用来验证短页面会被"
                "拒绝、正常正文会被接受的运行时边界。材料仍需说明命题、推理用途、可能反例、"
                "适用场景与不能推出的结论，避免把一句来源摘要直接包装成完整的辩论论据。"
                "对于价值判断和概念论证，来源只提供启发；对于经验性承重前提，才需要进一步"
                "核对方法、样本、测量、限制与原始出处。为了让测试覆盖真实网页的正文门槛，"
                "这里还明确记录材料如何改变论证、它支持哪一步、最强反驳是什么，以及为何"
                "不能把局部观察外推成普遍结论。"
            ),
            metadata={"demo_full_text": True},
        )


# ------------------------------------------------- scripted LLM (the "source")

UNIT_A1 = """\
## 正方第一版立场研究骨架

Status: tentative

Assigned standpoint:
表情包丰富了我们的表达。

Proposition interpretation:
暂将“丰富”理解为增加纯文字交流能够传递的有效信息类型，而不是要求表情包提升所有人的
长期词汇能力。候选标准包括信息维度、表达可达性和语用效果。

Prior-work landscape:
- 使用功能研究关注情绪表达、语气缓和和身份标记。
- CMC 理论关注纯文字缺失非语言线索后的补偿机制。
- 现有材料以自报与相关研究为主，因果证据不足。

Candidate viewpoints:
1. 线索带宽：图形符号补充文字难以稳定编码的情绪、反讽和语气。
2. 表达门槛：低语言组织能力或高压力场景中的用户获得额外表达资源。
3. 身份资源：共享梗图可能形成群体内部的文化和身份表达。

Evidence:
- 使用功能调查（src_0001）：自报频率数据
- 非语言线索补偿研究（src_0002）

Agent synthesis:
前两类材料可以组合成“线索带宽假说”：表情包可能通过补充元语用信息丰富文本渠道。
这是 Agent 推论，不是来源已经完成的因果证明。

Remaining uncertainty:
功能使用频率不等于表达质量提升；“丰富”的操作化仍不稳定；需要实验、纵向证据以及
互补效应与语言替代效应的分场景比较。"""

UNIT_A1_NARROWED = """\
## 正方立场研究骨架（因果表述收窄后）

Status: tentative

Assigned standpoint:
表情包丰富了我们的表达。

Proposition interpretation:
“丰富”暂指增加文本交流中的有效信息类型、表达可达性和语用效果，不等于已经证明长期
语言能力提高。

Current candidate viewpoints:
1. 线索带宽：表情符号可能补充情绪、反讽和语气信息。
2. 表达门槛：可能为部分用户或场景提供低成本表达资源。
3. 身份资源：可能承载共享文化与群体身份。

Evidence:
- 使用功能调查（src_0001）：自报频率数据
- 非语言线索补偿研究（src_0002）

Revision:
接受 issue_0001。现有证据只允许保留相关性的“线索带宽假说”，不能表述为表情包已经
导致表达能力或表达效果提高。

Remaining uncertainty:
因果方向、长期影响、互补与替代的场景边界、“丰富”的客观测量仍未解决。"""

UNIT_B1 = """\
## 反方第一版立场研究骨架

Status: tentative

Assigned standpoint:
表情包虚泛了我们的表达。

Proposition interpretation:
暂将“虚泛”理解为表达越来越依赖可复用模板，导致语义精确性、个体差异和主动语言组织
下降。候选标准包括表达精确度、原创性和长期表达能力。

Prior-work landscape:
- 模因研究讨论模板复制和表达同质化。
- 语义稀释观点认为低成本符号可能替代更精细的语言组织。
- 当前材料尚不足以证明短期使用会造成长期能力退化。

Candidate viewpoints:
1. 模板收编：热门梗使不同人的表达趋同。
2. 替代效应：低成本现成符号减少主动组织语言的需求。
3. 语义压缩：依赖共享语境的模板可能牺牲对陌生人的精确可解释性。

Evidence:
- 模因同质化研究（src_0003）
- 语义稀释假说（src_0004）

Agent synthesis:
“虚泛”可能不是表情包本身信息量低，而是模板在高频、惯用场景中替代个体化语言组织。
这是待验证的场景化替代假说。

Remaining uncertainty:
替代还是互补可能分场景；需要行为数据、长期证据和表达质量的操作化标准。"""

UNIT_B1_NARROWED = """\
## 同质化与模板收编

Status: tentative

Finding:
批量复用的热门梗模板使表达趋同，个体风格被模板收编；"发表情"常替代组织自己的语言。
结合对方的线索补偿视角反思：替换效应最可能出现在低语境亲密对话（惯用梗密集）中，
而在陌生人间破冰场景，表情包更可能作为低风险破冰资源（互补）。

Evidence:
- 模因同质化研究（src_0003）
- 语义稀释假说（src_0004）

Implication:
场景限定版替换假说：同质化效应在亲密惯用对话中最显著。

Remaining uncertainty: 两类场景的边界与占比缺乏行为数据。"""

UNIT_B2 = """\
## 表达质量的测量困境

Status: tentative

Finding:
"表达丰富度"缺乏统一操作化定义，多数研究用自我报告；语用学视角认为表情符号
承担元语用功能（反讽标记、请求软化、节奏管理）。

Evidence:
- 测量综述（src_0005）
- 元语用研究（src_0006）

Implication:
丰富 vs 虚泛之争可能部分源于测量框架不同——需先解决"什么叫表达变好"。

Remaining uncertainty: 客观行为数据研究稀缺。"""


class PioneerLLM:
    """Scripted turns keyed by (mode, agent, per-key call index)."""

    def __init__(self):
        self._count: dict[tuple[str, str], int] = {}

    def _detect(self, messages):
        system = messages[0]["content"]
        agent = "A" if "Position Advocate A" in system else "B"
        if "EXPANSION" in system:
            mode = "expansion"
        elif "COLLISION" in system:
            mode = "collision"
        elif "STABILITY CHECK" in system:
            mode = "stability_check"
        else:
            mode = "continuous"
        return mode, agent

    async def run(self, messages, tools=None):
        mode, agent = self._detect(messages)
        names = {item.get("function", {}).get("name") for item in (tools or [])}
        plan_args = {
            "phase": mode,
            "question_interpretation": "根据本方立场解释表达丰富或虚泛的胜负边界",
            "winning_condition": "形成可比较、可防守且承认适用边界的论证",
            "strategy": "根据当前黑板选择最能改变论证的下一项行动",
            "route_hypotheses": ["语用功能", "长期替代或互补"],
            "next_actions": [{
                "action": "推进脚本中的下一项研究行动", "purpose": "形成持久成果",
                "expected_gain": "关闭当前阶段缺口", "stop_or_pivot_if": "结果不改变论证",
            }],
            "stopping_conditions": ["当前阶段的结构化交付已完成"],
            "completed": [], "abandoned": [], "remaining_work": "执行当前阶段",
            "progress_assessment": "已完成自主规划", "estimated_remaining_actions": 3,
            "status": "active", "change_reason": "进入新的研究阶段",
        }
        if names == {"update_plan"}:
            return LLMTurn(tool_calls=[ToolCall("plan", "update_plan", plan_args)])
        key = (mode, agent)
        n = self._count.get(key, 0)
        self._count[key] = n + 1
        turn = self._turn(mode, agent, n)
        if any(call.name == "conclude_pass" for call in turn.tool_calls):
            plan_args.update(
                status="ready_to_conclude", next_actions=[], remaining_work="无",
                completed=["当前阶段"], progress_assessment="退出审计通过",
                estimated_remaining_actions=0, change_reason="阶段目标已经满足",
            )
            turn.tool_calls.insert(0, ToolCall("plan-ready", "update_plan", plan_args))
        return turn

    def _turn(self, mode, agent, n):
        # ---------------------------------------------------------- expansion
        if mode == "expansion" and agent == "A":
            if n == 0:
                return LLMTurn(tool_calls=[
                    ToolCall(id="a-e-s1", name="search",
                             arguments={"query": "表情包 使用功能 调查", "n": 3,
                                        "search_mode": "argument_discovery",
                                        "discovery_kind": "exact_motion"}),
                ])
            if n == 1:
                return LLMTurn(tool_calls=[
                    ToolCall(id="a-e-s2", name="search",
                             arguments={"query": "非语言线索 计算机中介沟通", "n": 3}),
                ])
            return LLMTurn(tool_calls=[
                ToolCall(id="a-e-read1", name="read_source", arguments={"source_id": "src_0001"}),
                ToolCall(id="a-e-read2", name="read_source", arguments={"source_id": "src_0002"}),
                ToolCall(id="a-e-a1d", name="update_argument", arguments={
                    "title": "线索带宽：表情包增加文字难以承载的信息维度",
                    "claim": "在纯文字沟通中，表情包补充语气、情绪与反讽线索，因此扩展了可有效传递的信息类型。",
                    "burden": "证明这种新增线索能够改善意义传递，而不只是增加装饰。",
                    "criterion": "表达是否让沟通者能够更准确、低成本地传递原本难以传递的意义。",
                    "warrant": ["纯文字会损失部分非语言线索", "表情符号能够编码并恢复其中一部分线索", "可传递意义维度增加构成表达资源的丰富"],
                    "impact": "降低语气误判，并让情绪与反讽更容易被对方识别。",
                    "scope": "主要适用于缺少面对面线索的日常数字沟通，不推出长期语言能力提升。",
                    "vulnerabilities": ["现有材料以相关和自报研究为主"], "status": "draft",
                    "what_changed": "建立核心论点：线索带宽",
                }),
                ToolCall(id="a-e-a2d", name="update_argument", arguments={
                    "title": "表达可达性：降低参与表达的能力与情绪门槛",
                    "claim": "表情包为难以即时组织复杂语言的人提供低成本表达入口。",
                    "burden": "证明降低门槛带来的是新增表达，而非简单偷懒。",
                    "criterion": "更多主体能否表达此前难以表达的状态。",
                    "warrant": ["语言组织能力与情绪状态限制部分人的即时表达", "共享图像模板提供可调用的表达资源", "原本沉默或含混的主体因此能够参与沟通"],
                    "impact": "扩大表达参与，并缓和高压力对话中的沟通阻塞。",
                    "scope": "适用于即时、情绪性和低正式度沟通。",
                    "vulnerabilities": ["需要区分降低门槛与替代语言"], "status": "draft",
                    "what_changed": "建立核心论点：表达可达性",
                }),
                ToolCall(id="a-e-a3d", name="update_argument", arguments={
                    "title": "文化表达：共享模因形成身份与关系语言",
                    "claim": "共享表情包能够承载群体记忆、身份暗号和关系定位，增加文化表达层次。",
                    "burden": "证明模板复用仍可承载情境化意义，而非只造成同质化。",
                    "criterion": "表达资源是否能够传递身份、关系和文化语境。",
                    "warrant": ["表达不仅传递命题信息，也传递身份与关系", "模因意义会在具体社群和语境中被重新编码", "这种语境化调用构成新的文化表达资源"],
                    "impact": "增强群体认同和高语境沟通效率。",
                    "scope": "依赖共享文化，对跨文化沟通不作强主张。",
                    "vulnerabilities": ["模板化可能压缩个体差异"], "status": "draft",
                    "what_changed": "建立核心论点：文化身份资源",
                }),
                ToolCall(id="a-e-e1", name="record_evidence", arguments={
                    "source_id": "src_0001", "argument_id": "arg_a_0001",
                    "proposition": "用户将表情包用于情绪、语气和身份表达",
                    "finding": "调查中的主要自报功能包括情绪表达、语气缓和与身份标记。",
                    "method": "3000名18-35岁用户问卷", "limitations": "自报、相关性、年龄范围有限",
                    "provenance": "演示调查摘要，正式运行必须回溯完整报告", "status": "examined",
                    "what_changed": "记录功能分类证据",
                }),
                ToolCall(id="a-e-e2", name="record_evidence", arguments={
                    "source_id": "src_0002", "argument_id": "arg_a_0001",
                    "proposition": "图形符号可以补偿文本媒介缺失的非语言线索",
                    "finding": "研究将图形符号与亲密感、幽默和语气传递联系起来。",
                    "method": "计算机中介沟通研究", "limitations": "不能直接推出长期能力变化",
                    "provenance": "演示论文摘要，正式运行必须阅读原文", "status": "examined",
                    "what_changed": "记录线索补偿证据",
                }),
                ToolCall(id="a-e-e3", name="record_evidence", arguments={
                    "source_id": "src_0001", "argument_id": "arg_a_0002",
                    "proposition": "语气缓和是表情包的高频使用功能",
                    "finding": "58%的受访者报告使用表情包缓和语气。",
                    "method": "问卷中的功能频率项目", "limitations": "未直接测量沉默者是否增加表达",
                    "provenance": "演示调查摘要", "status": "examined",
                    "what_changed": "记录可达性的间接证据",
                }),
                ToolCall(id="a-e-a1", name="update_argument", arguments={"argument_id": "arg_a_0001", "evidence_ids": ["ev_a_0001", "ev_a_0002"], "what_changed": "绑定已检查证据"}),
                ToolCall(id="a-e-a2", name="update_argument", arguments={"argument_id": "arg_a_0002", "evidence_ids": ["ev_a_0003"], "what_changed": "绑定已检查证据"}),
                ToolCall(id="a-e-a3", name="update_argument", arguments={"argument_id": "arg_a_0003", "evidence_ids": ["ev_a_0001"], "what_changed": "绑定已检查证据"}),
                ToolCall(id="a-e-u1", name="update_unit", arguments={
                    "content": UNIT_A1, "status": "tentative",
                    "source_ids": ["src_0001", "src_0002"],
                    "what_changed": "initial unit: 功能分类与线索补偿",
                    "why": "expansion recall",
                }),
                ToolCall(id="a-e-m1", name="update_map", arguments={
                    "title": "表情包是否降低词汇精确性（语义稀释）",
                    "status": "resolved", "importance": "high",
                    "coverage": "low", "uncertainty": "high",
                    "note": "检验反方替代效应；需要词汇选择、语言组织或长期变化的行为/纵向证据；若只有自报相关性则不能证明能力下降",
                    "what_changed": "opened during expansion",
                }),
                ToolCall(id="a-e-m2", name="update_map", arguments={
                    "title": "跨文化/跨语言差异", "status": "resolved",
                    "importance": "medium", "coverage": "low", "uncertainty": "high",
                    "note": "检验线索带宽与身份资源是否依赖共享文化；需要跨语言误读率、语用功能和群体差异证据",
                    "what_changed": "opened during expansion",
                }),
                ToolCall(id="a-e-m3", name="update_map", arguments={
                    "title": "表达'丰富度'如何操作化测量", "status": "resolved",
                    "importance": "high", "coverage": "low", "uncertainty": "high",
                    "note": "服务全部正方候选观点；需要区分信息维度、精确度、可达性、原创性与长期能力，自报频率不能替代质量测量",
                    "what_changed": "opened during expansion",
                }),
                ToolCall(id="a-e-c", name="conclude_pass", arguments={
                    "summary": "形成正方第一版立场研究骨架，并把三个关键缺口转成证据任务",
                    "attempted": "拆解丰富的候选标准；检索使用功能与非语言线索；形成线索带宽、表达门槛、身份资源三类候选观点",
                    "changed": "建立整体研究骨架；区分来源结论与 Agent 的线索带宽假说；生成 3 个观点到证据的 Map 任务",
                    "remaining_unknowns": "语义稀释假说的实证证据；表达质量测量方法",
                    "why_stop": "扩展阶段预算内已覆盖主要维度",
                    "next_pass": "围绕语义稀释假说找实证",
                    "no_high_value_direction": False,
                }),
            ])

        if mode == "expansion" and agent == "B":
            if n == 0:
                return LLMTurn(tool_calls=[
                    ToolCall(id="b-e-s1", name="search",
                             arguments={"query": "表达 同质化 模因 模板", "n": 3,
                                        "search_mode": "argument_discovery",
                                        "discovery_kind": "exact_motion"}),
                ])
            if n == 1:
                return LLMTurn(tool_calls=[
                    ToolCall(id="b-e-s2", name="search",
                             arguments={"query": "表达质量 测量 操作化", "n": 3}),
                ])
            return LLMTurn(tool_calls=[
                ToolCall(id="b-e-read1", name="read_source", arguments={"source_id": "src_0003"}),
                ToolCall(id="b-e-read2", name="read_source", arguments={"source_id": "src_0004"}),
                ToolCall(id="b-e-read3", name="read_source", arguments={"source_id": "src_0005"}),
                ToolCall(id="b-e-a1d", name="update_argument", arguments={
                    "title": "模板替代：现成反应压缩自主语言组织",
                    "claim": "当表情包从辅助文字变成替代文字时，表达趋向现成模板而非个人化组织。",
                    "burden": "证明替代效应在重要场景中稳定存在，而非只是一种表达偏好。",
                    "criterion": "表达是否保留精确组织意义和形成个人表达的能力。",
                    "warrant": ["热门模板提供低成本现成反应", "高频调用会替代针对具体情境组织语言", "意义被压缩进少量公共模板使表达趋同"],
                    "impact": "降低表达精确度和个体差异，使复杂感受被粗粒度反应取代。",
                    "scope": "主要针对惯用梗密集并替代文本的场景。",
                    "vulnerabilities": ["需要区分互补使用与替代使用"], "status": "draft",
                    "what_changed": "建立核心论点：模板替代",
                }),
                ToolCall(id="b-e-a2d", name="update_argument", arguments={
                    "title": "语义依赖：表达越来越依赖圈层共享背景",
                    "claim": "表情包意义高度依赖特定语境与圈层，使表达在圈外更含混、更易误读。",
                    "burden": "证明这种语境依赖总体造成表达损失，而不只是形成新文化。",
                    "criterion": "表达能否稳定、准确地被目标受众理解。",
                    "warrant": ["模因意义依赖来源、用法和社群记忆", "不同群体缺少相同解码背景", "同一表情在跨群体传播时产生误读与意义漂移"],
                    "impact": "削弱跨群体沟通的清晰性，并扩大语境壁垒。",
                    "scope": "跨年龄、跨文化和陌生人沟通场景。",
                    "vulnerabilities": ["圈层内部可能反而提高效率"], "status": "draft",
                    "what_changed": "建立核心论点：语境依赖",
                }),
                ToolCall(id="b-e-a3d", name="update_argument", arguments={
                    "title": "评价错置：即时互动顺滑不等于表达变得丰富",
                    "claim": "表情包可能提升互动顺滑度，但这不足以证明表达内容的精确性、原创性或复杂度增加。",
                    "burden": "证明辩题中的丰富应评价表达质量，而非单纯使用便利。",
                    "criterion": "能够承载的自主、精确和复杂意义是否增加。",
                    "warrant": ["互动愉悦与表达质量是不同测量对象", "现有研究多测自报感受和使用频率", "缺少质量指标时不能从好用推出丰富"],
                    "impact": "阻止正方用沟通便利替代对表达丰富性的证明。",
                    "scope": "适用于评价正方证据和判准，不否认表情包具有语用功能。",
                    "vulnerabilities": ["需要提出可操作的表达质量标准"], "status": "draft",
                    "what_changed": "建立核心论点：评价错置",
                }),
                ToolCall(id="b-e-e1", name="record_evidence", arguments={
                    "source_id": "src_0003", "argument_id": "arg_b_0001",
                    "proposition": "热门梗模板的复用可能使表达趋同",
                    "finding": "材料提出模板批量复用与个体风格收编之间的关系。",
                    "method": "模因传播分析", "limitations": "演示摘要未提供效应量与因果识别",
                    "provenance": "演示来源摘要", "status": "examined", "what_changed": "记录同质化证据",
                }),
                ToolCall(id="b-e-e2", name="record_evidence", arguments={
                    "source_id": "src_0005", "argument_id": "arg_b_0003",
                    "proposition": "表达丰富度缺少统一操作化定义",
                    "finding": "综述发现多数研究依赖自报指标。", "method": "测量综述",
                    "limitations": "不能单独证明表情包使表达虚泛", "provenance": "演示综述摘要",
                    "status": "examined", "what_changed": "记录测量缺口证据",
                }),
                ToolCall(id="b-e-e3", name="record_evidence", arguments={
                    "source_id": "src_0004", "argument_id": "arg_b_0002",
                    "proposition": "高频表情包可能替代具体词汇组织",
                    "finding": "材料提出语义稀释假说。", "method": "理论论证",
                    "limitations": "目前是待验证假说", "provenance": "演示来源摘要",
                    "status": "examined", "what_changed": "记录语义稀释假说",
                }),
                ToolCall(id="b-e-a1", name="update_argument", arguments={"argument_id": "arg_b_0001", "evidence_ids": ["ev_b_0001", "ev_b_0003"], "what_changed": "绑定已检查证据"}),
                ToolCall(id="b-e-a2", name="update_argument", arguments={"argument_id": "arg_b_0002", "evidence_ids": ["ev_b_0003"], "what_changed": "绑定已检查证据"}),
                ToolCall(id="b-e-a3", name="update_argument", arguments={"argument_id": "arg_b_0003", "evidence_ids": ["ev_b_0002"], "what_changed": "绑定已检查证据"}),
                ToolCall(id="b-e-u1", name="update_unit", arguments={
                    "content": UNIT_B1, "status": "tentative",
                    "source_ids": ["src_0003", "src_0004"],
                    "what_changed": "initial unit: 同质化与替代效应",
                    "why": "expansion recall",
                }),
                ToolCall(id="b-e-u2", name="update_unit", arguments={
                    "content": UNIT_B2, "status": "tentative",
                    "source_ids": ["src_0005", "src_0006"],
                    "what_changed": "initial unit: 测量困境与元语用功能",
                    "why": "expansion recall",
                }),
                ToolCall(id="b-e-m1", name="update_map", arguments={
                    "title": "互补 vs 替代：分场景的使用效果", "status": "resolved",
                    "importance": "high", "coverage": "low", "uncertainty": "high",
                    "note": "检验反方的场景化替代假说；需要比较亲密惯用对话、陌生人破冰、正式沟通中的行为结果",
                    "what_changed": "opened during expansion",
                }),
                ToolCall(id="b-e-m2", name="update_map", arguments={
                    "title": "AI 生成表情包对表达的影响", "status": "resolved",
                    "importance": "medium", "coverage": "low", "uncertainty": "high",
                    "note": "检验模板化是否因生成式个性化而减弱或加剧；需要比较固定模板与个性生成内容",
                    "what_changed": "opened during expansion",
                }),
                ToolCall(id="b-e-c", name="conclude_pass", arguments={
                    "summary": "形成反方第一版立场研究骨架，并单独整理表达质量的测量问题",
                    "attempted": "拆解虚泛的候选标准；检索同质化、语义稀释和表达测量；形成模板收编、替代效应、语义压缩三类候选观点",
                    "changed": "建立整体研究骨架 + 测量专题 Unit；把场景化替代和生成式个性化转成证据任务",
                    "remaining_unknowns": "分场景效果证据；客观行为数据",
                    "why_stop": "扩展阶段预算内已覆盖主要维度",
                    "next_pass": "读对方结果后补图",
                    "no_high_value_direction": False,
                }),
            ])

        # ---------------------------------------------------------- collision
        if mode == "collision" and agent == "A":
            return LLMTurn(tool_calls=[
                ToolCall(id="a-cl-r1", name="update_rebuttal", arguments={
                    "target_agent": "B", "target_argument_id": "arg_b_0001",
                    "title": "模板被使用，不等于文字组织被替代",
                    "reconstruction": "反方认为现成表情模板降低组织语言的成本，因而会替代自主表达并造成同质化。",
                    "attack_type": "机制与范围",
                    "attack": "反方目前只有模板复用现象，没有证明多数使用属于替代而非文字的补充；在表情与文字共现时，同一事实也可能支持表达资源增加。",
                    "why_it_matters": "如果不能识别替代发生的比例和场景，反方无法从局部风险推出表情包总体使表达虚泛。",
                    "likely_response": "反方可以把论点收窄到惯用梗密集、表情替代文本的特定场景。",
                    "current_effect": "迫使反方限定场景，不能维持一般性结论。", "status": "active",
                    "what_changed": "形成针对模板替代论的基础驳论",
                }),
                ToolCall(id="a-cl-r2", name="update_rebuttal", arguments={
                    "target_agent": "B", "target_argument_id": "arg_b_0003",
                    "title": "表达丰富不能被缩减为词汇复杂度",
                    "reconstruction": "反方认为互动顺滑与表达质量不同，只有精确、原创和复杂意义增加才算丰富。",
                    "attack_type": "判准",
                    "attack": "表达还承担情绪、关系和语气管理；若反方排除这些功能，它实际上先用狭窄定义删掉了表情包新增的表达维度。",
                    "why_it_matters": "反方的评价标准若不包含语用信息，就无法公平比较纯文字与多模态表达。",
                    "likely_response": "反方会承认语用功能，但主张模板化造成的损失更大。",
                    "current_effect": "要求反方进行净效果比较，不能只质疑正方测量。", "status": "active",
                    "what_changed": "形成针对表达质量判准的驳论",
                }),
                ToolCall(id="a-cl-r3", name="update_rebuttal", arguments={
                    "target_agent": "B", "target_argument_id": "arg_b_0002",
                    "title": "圈层外误读不是圈层内身份表达的反例",
                    "reconstruction": "反方认为表情包依赖共享背景，跨群体容易误读。",
                    "attack_type": "范围与比较",
                    "attack": "跨群体误读是共享语境的边界，不足以抹掉圈层内部新增的关系和身份信息。",
                    "why_it_matters": "反方需要比较新增内部表达与外部误读，不能把局部边界当总体否定。",
                    "likely_response": "反方可以限定其主张为跨圈层沟通。",
                    "current_effect": "迫使反方限定适用场景。", "status": "active",
                    "what_changed": "覆盖反方第三条当前论点",
                }),
                ToolCall(id="a-cl-m1", name="update_map", arguments={
                    "title": "互补 vs 替代：分场景的使用效果", "status": "active",
                    "importance": "high", "coverage": "low", "uncertainty": "high",
                    "note": "adopted from B's expansion（补图）",
                    "what_changed": "adopted direction from B",
                    "why": "B 提出的互补/替代区分是我缺失的重要维度",
                }),
                ToolCall(id="a-cl-c", name="conclude_pass", arguments={
                    "summary": "补图：采纳 B 的'互补 vs 替代'方向；无对方证据错误，不挂工单",
                    "attempted": "逐条核对 B 的 units/maps 与来源",
                    "changed": "+1 map direction",
                    "remaining_unknowns": "不变",
                    "why_stop": "补图完成，本轮无其他高增益动作",
                    "next_pass": "在自己的地图上分配研究预算",
                    "no_high_value_direction": False,
                }),
            ])

        if mode == "collision" and agent == "B":
            return LLMTurn(tool_calls=[
                ToolCall(id="b-cl-r1", name="update_rebuttal", arguments={
                    "target_agent": "A", "target_argument_id": "arg_a_0001",
                    "title": "线索增加尚未证明表达因此更丰富",
                    "reconstruction": "正方认为表情包恢复文字缺失的语气和情绪线索，因此增加可传递的信息维度。",
                    "attack_type": "证据强度与推论",
                    "attack": "正方材料主要证明用户会这样使用及主观感受，尚未证明接收者更准确理解，更不能推出长期表达能力改善。",
                    "why_it_matters": "若实际理解没有改善，新增符号只是意图而不是有效表达；正方核心机制缺少结果变量。",
                    "likely_response": "正方可以放弃长期能力主张，并把丰富限定为当次沟通中的线索资源。",
                    "current_effect": "击中因果表述，要求正方收窄并补充理解准确率证据。", "status": "active",
                    "what_changed": "形成针对线索带宽论的基础驳论",
                }),
                ToolCall(id="b-cl-r2", name="update_rebuttal", arguments={
                    "target_agent": "A", "target_argument_id": "arg_a_0002",
                    "title": "降低门槛也可能意味着回避精确表达",
                    "reconstruction": "正方认为现成图像降低语言组织与情绪表达门槛，让更多人参与沟通。",
                    "attack_type": "替代解释",
                    "attack": "同一低成本机制既可能帮助原本沉默的人表达，也可能让本可精确表达的人选择模糊模板；正方没有区分新增表达与表达降级。",
                    "why_it_matters": "如果替代效应大于参与增量，低门槛不能证明总体丰富。",
                    "likely_response": "正方需要限定受益人群，并证明互补使用而非替代使用占主导。",
                    "current_effect": "迫使正方把可达性论从普遍主张收窄为特定主体与场景。", "status": "active",
                    "what_changed": "形成针对表达可达性论的基础驳论",
                }),
                ToolCall(id="b-cl-r3", name="update_rebuttal", arguments={
                    "target_agent": "A", "target_argument_id": "arg_a_0003",
                    "title": "共享梗的身份效率依赖排他语境",
                    "reconstruction": "正方认为共享模因承载关系与群体身份。",
                    "attack_type": "范围与净效应",
                    "attack": "圈层内的高效身份暗号同时提高圈层外误读成本，不能直接推出总体表达丰富。",
                    "why_it_matters": "正方必须限定受众与比较世界，不能以圈内收益替代公共表达质量。",
                    "likely_response": "正方可承认共享语境限制并收窄论点。",
                    "current_effect": "迫使正方注明文化边界。", "status": "active",
                    "what_changed": "覆盖正方第三条当前论点",
                }),
                ToolCall(id="b-cl-i1", name="create_issue", arguments={
                    "to": "A",
                    "target": {"type": "unit", "id": "ru_a_0001", "section": "Implication"},
                    "priority": "medium",
                    "title": "线索补偿→表达丰富是相关性不是因果",
                    "body": "src_0001/src_0002 均为相关/自报证据，A 的 Implication "
                            "'扩展了线索通道'偏因果表述；建议收窄或补实验证据。",
                    "what_changed": "filed: causal wording on correlational evidence",
                }),
                ToolCall(id="b-cl-m1", name="update_map", arguments={
                    "title": "跨文化/跨语言差异", "status": "active",
                    "importance": "medium", "coverage": "low", "uncertainty": "high",
                    "note": "adopted from A's expansion（补图）",
                    "what_changed": "adopted direction from A",
                }),
                ToolCall(id="b-cl-c", name="conclude_pass", arguments={
                    "summary": "发现 A 的一处因果表述问题并挂工单；补图跨文化方向",
                    "attempted": "核对 A 的证据类型与结论强度",
                    "changed": "+1 issue +1 map direction",
                    "remaining_unknowns": "不变",
                    "why_stop": "补图与互审完成",
                    "next_pass": "等待 A 回应；继续自己的方向",
                    "no_high_value_direction": False,
                }),
            ])

        # --------------------------------------------------------- continuous
        if mode == "continuous" and agent == "A" and n == 0:  # cycle 1
            return LLMTurn(tool_calls=[
                ToolCall(id="a-c1-r1", name="respond_issue", arguments={
                    "issue_id": "issue_0001",
                    "response": "接受。已将 unit 收窄为线索带宽假说并明确非因果；"
                                "因果检验写入研究地图（X→Y 因果检验方向）。",
                    "what_changed": "responded: accepted, claim narrowed",
                    "why": "issue 成立，表述确实过强",
                }),
                ToolCall(id="a-c1-u1", name="update_unit", arguments={
                    "unit_id": "ru_a_0001",
                    "content": UNIT_A1_NARROWED, "status": "tentative",
                    "what_changed": "claim narrowed: 因果表述→相关假说",
                    "why": "issue_0001",
                }),
                ToolCall(id="a-c1-a1", name="update_argument", arguments={
                    "argument_id": "arg_a_0001",
                    "claim": "在缺少面对面线索的具体数字沟通中，表情包可以补充语气、情绪与反讽线索，扩展当次沟通可调用的表达资源。",
                    "scope": "只主张当次数字沟通中的线索资源，不主张长期语言能力或所有场景中的理解改善。",
                    "defense": ["接受相关性证据不能支持长期因果结论", "以信息维度和语用功能而非词汇能力作为比较标准"],
                    "what_changed": "回应反方后收窄因果与适用范围",
                    "why": "反方正确指出结果变量和因果证据不足",
                }),
                ToolCall(id="a-c1-m1", name="update_map", arguments={
                    "title": "X→Y 因果检验：表情包使用→表达质量变化的实验/纵向证据",
                    "status": "active", "importance": "high",
                    "coverage": "low", "uncertainty": "high",
                    "what_changed": "opened from issue_0001",
                    "why": "issue 指出的因果缺口需要专门研究",
                }),
                ToolCall(id="a-c1-m2", name="update_map", arguments={
                    "map_id": "map_a_0001", "status": "resolved",
                    "what_changed": "subsumed by 互补 vs 替代 direction",
                    "why": "与 B 的方向重叠，合并避免重复投入",
                }),
                ToolCall(id="a-c1-m3", name="update_map", arguments={
                    "map_id": "map_a_0003", "status": "dormant",
                    "what_changed": "parked: B 的 unit ru_b_0002 已覆盖该方向",
                    "why": "避免重复；留待 H review 决定是否合并",
                }),
                ToolCall(id="a-c1-c", name="conclude_pass", arguments={
                    "summary": "回应 issue 并收窄 claim；本轮解决'表述过强'问题",
                    "attempted": "复查 src_0001/src_0002 的证据类型",
                    "changed": "unit 收窄 + 开启因果检验方向 + 合并/暂停两个重复方向",
                    "remaining_unknowns": "因果方向的实验证据",
                    "why_stop": "本 Pass 预算内目标已达成",
                    "next_pass": "寻找实验/纵向证据",
                    "no_high_value_direction": False,
                }),
            ])

        if mode == "continuous" and agent == "B" and n == 0:  # cycle 1
            return LLMTurn(tool_calls=[
                ToolCall(id="b-c1-x1", name="close_issue", arguments={
                    "issue_id": "issue_0001", "resolution": "clarified",
                    "what_changed": "A 已收窄表述并开启因果检验方向",
                    "why": "回应充分",
                }),
                ToolCall(id="b-c1-u1", name="update_unit", arguments={
                    "unit_id": "ru_b_0001",
                    "content": UNIT_B1_NARROWED, "status": "tentative",
                    "what_changed": "claim narrowed: 加场景限定",
                    "why": "结合 A 的线索补偿视角反思同质化的适用边界",
                }),
                ToolCall(id="b-c1-a1", name="update_argument", arguments={
                    "argument_id": "arg_b_0001",
                    "claim": "在惯用梗密集且表情替代具体文本的场景中，现成模板压缩个人化语言组织，使表达趋同。",
                    "scope": "限定于亲密关系中的惯用梗密集、表情替代文字等高替代场景；不否认陌生人破冰中的互补价值。",
                    "defense": ["不再从模板存在直接推出一般性表达退化", "通过互补/替代的场景区分维护反方核心风险"],
                    "what_changed": "回应正方后把模板替代论收窄到高替代场景",
                    "why": "正方指出模板使用与文字替代之间缺少普遍性证明",
                }),
                ToolCall(id="b-c1-c", name="conclude_pass", arguments={
                    "summary": "关闭 issue（clarified）；收窄同质化 claim 至场景限定版",
                    "attempted": "用 A 的视角反审自己的同质化 claim",
                    "changed": "issue 关闭 + unit 收窄",
                    "remaining_unknowns": "两类场景的边界与占比",
                    "why_stop": "本轮互审带来的修正已完成",
                    "next_pass": "检验互补 vs 替代的分场景证据",
                    "no_high_value_direction": False,
                }),
            ])

        if mode == "continuous" and agent == "B" and n >= 1:  # cycle 2 repair/converge
            return LLMTurn(tool_calls=[
                ToolCall(id="b-c2-m1", name="update_map", arguments={
                    "map_id": "map_b_0001", "status": "resolved",
                    "what_changed": "resolved through scoped claim",
                    "why": "不再用未知总体占比支撑一般性结论，核心论点限定在高替代场景",
                }),
                ToolCall(id="b-c2-a1", name="update_argument", arguments={"argument_id": "arg_b_0001", "status": "defensible", "what_changed": "通过普通互驳后达到基础可辩护状态"}),
                ToolCall(id="b-c2-a2", name="update_argument", arguments={"argument_id": "arg_b_0002", "status": "defensible", "defense": ["承认圈层内部效率，比较重点限定为跨群体可理解性"], "what_changed": "明确最强反例与比较范围"}),
                ToolCall(id="b-c2-a3", name="update_argument", arguments={"argument_id": "arg_b_0003", "status": "defensible", "defense": ["承认语用功能存在，但要求正方证明其足以满足辩题中的丰富"], "what_changed": "形成判准防守"}),
                ToolCall(id="b-c2-c", name="conclude_pass", arguments={
                    "summary": "三条反方核心论点完成普通互驳后的收窄与防守",
                    "attempted": "逐条检查定义、机制、证据、范围和正方最强回应",
                    "changed": "模板替代论限定场景；语境依赖和评价错置论补充防守",
                    "remaining_unknowns": "真实总体中的场景占比需要新的外部行为数据，但不再承担当前限定论点的证明",
                    "why_stop": "当前基础立论的关键证明链完整，普通反驳已处理",
                    "next_pass": "进入更高强度思想实验前由用户审阅基础立论",
                    "no_high_value_direction": True,
                }),
            ])

        if mode == "continuous" and agent == "A" and n >= 1:  # cycle 2 repair/converge
            return LLMTurn(tool_calls=[
                ToolCall(id="a-c2-m0", name="update_map", arguments={
                    "map_id": "map_a_0004", "status": "resolved",
                    "what_changed": "resolved through explicit complement/substitution boundary",
                    "why": "双方论点已经按互补与替代场景分别收窄",
                }),
                ToolCall(id="a-c2-m1", name="update_map", arguments={
                    "map_id": "map_a_0005", "status": "resolved",
                    "what_changed": "removed from current burden by narrowing claim",
                    "why": "当前论点不再声称长期因果能力提升",
                }),
                ToolCall(id="a-c2-m2", name="update_map", arguments={"map_id": "map_a_0003", "status": "resolved", "what_changed": "resolved by adopting multidimensional expression criterion", "why": "当前立论明确区分信息维度、可达性与长期能力"}),
                ToolCall(id="a-c2-a1", name="update_argument", arguments={"argument_id": "arg_a_0001", "status": "defensible", "what_changed": "收窄后通过基础因果与判准攻击"}),
                ToolCall(id="a-c2-a2", name="update_argument", arguments={"argument_id": "arg_a_0002", "status": "defensible", "scope": "只主张对即时组织困难者及高压力、低正式度场景带来新增表达，不推出所有用户总体改善。", "defense": ["区分新增表达与对既有精确表达的替代"], "what_changed": "按反方替代解释收窄受益主体"}),
                ToolCall(id="a-c2-a3", name="update_argument", arguments={"argument_id": "arg_a_0003", "status": "defensible", "defense": ["承认跨文化误读风险，把论点限定于共享语境内的文化表达"], "what_changed": "明确共享文化边界"}),
                ToolCall(id="a-c2-c", name="conclude_pass", arguments={
                    "summary": "三条正方核心论点完成普通互驳后的收窄与防守",
                    "attempted": "逐条处理反方对因果、替代解释和文化边界的攻击",
                    "changed": "线索带宽取消长期因果主张；可达性限定受益主体；文化表达限定共享语境",
                    "remaining_unknowns": "长期能力效果与总体净效应需要新的现实实验，但不再作为当前立论前提",
                    "why_stop": "当前基础立论的关键证明链完整，普通反驳已处理",
                    "next_pass": "进入更高强度思想实验前由用户审阅基础立论",
                    "no_high_value_direction": True,
                }),
            ])

        # ----------------------------------------------------- stability check
        if mode == "stability_check":
            return LLMTurn(tool_calls=[
                ToolCall(id=f"{agent}-st", name="answer_stability", arguments={
                    "has_direction": False,
                    "direction": "当前基础立论已完成；只有超出当前主张的长期实验问题仍未知",
                }),
            ])

        raise AssertionError(f"unscripted turn: {mode} {agent} #{n}")


# ------------------------------------------------------- state-change tracker

class TrackingStore(InMemoryStore):
    def __init__(self):
        super().__init__()
        self.timeline = []

    async def save_session(self, session):
        self.timeline.append(
            (now_iso(), session.status.value, session.current_cycle, session.next_agent.value)
        )
        await super().save_session(session)


# ------------------------------------------------------------------- run/demo

async def main():
    store = TrackingStore()
    progress_events = []
    session = ResearchSession(
        session_id="pioneer",
        question=QUESTION,
        position_a="表情包丰富了我们的表达",
        position_b="表情包虚泛了我们的表达",
        status=SessionStatus.CREATED,
        budget=ResearchBudget(
            argument_first_gate=False,
            min_sources_per_agent=0,
            min_examined_sources_per_agent=0,
            min_core_arguments_per_agent=3,
            min_rebuttals_per_agent=2,
            max_cycles=2,
        ),
    )
    await store.save_session(session)

    runtime = Runtime(
        store=store, llm=PioneerLLM(), search=MockSearch(),
        progress_callback=progress_events.append,
    )
    try:
        result = await runtime.run("pioneer")
    except Exception:
        print("\n--- last runtime events before failure ---")
        diagnostic_events = [
            event for event in progress_events
            if (event.get("event") or {}).get("kind")
            in {"search", "read", "gate", "early_stop", "budget"}
        ]
        selected_events = (
            diagnostic_events
            if len(diagnostic_events) <= 30
            else diagnostic_events[:15] + diagnostic_events[-15:]
        )
        for event in selected_events:
            activity = event.get("event") or {}
            print(
                f"  {event.get('phase')} {activity.get('agent', '-')} "
                f"{activity.get('title', event.get('message', ''))}: "
                f"{activity.get('summary', '')}"
            )
        raise

    print("=" * 70)
    print(f"FINAL STATUS: {result.status.value}  cycles={result.current_cycle}  "
          f"next_agent={result.next_agent.value}")
    print("=" * 70)

    print("\n--- state timeline (status / cycle / next) ---")
    for t, s, c, nx in store.timeline:
        print(f"  {t}  {s:<20} cycle={c} next={nx}")

    log = MutationLog(store, "pioneer")
    mutations = await log.list()
    print(f"\n--- mutation log ({len(mutations)} mutations) ---")
    for m in mutations:
        tgt = f" -> {m.target.id}" if m.target else ""
        extra = ""
        if m.action.value == "conclude_pass":
            extra = f"  [no_high_value={m.payload.get('no_high_value_direction')}]"
        print(f"  #{m.seq:02d} pass{m.pass_no} {m.agent.value} "
              f"{m.action.value:<14}{tgt}{extra}")

    for pno, who, label in [(4, Party.B, "B's collision pass (as read by A)"),
                            (5, Party.A, "A's cycle-1 pass (as read by B)")]:
        print(f"\n--- semantic diff: {label} ---")
        print(build_semantic_diff(await log.list(pno), who, pno))

    print("--- units ---")
    for a in (Party.A, Party.B):
        for u in await store.list_units("pioneer", a):
            first = next(l for l in u.content.splitlines() if l.strip())
            print(f"  {a.value} {u.unit_id} [{u.status.value}] sources={u.source_ids}")
            print(f"      {first}")

    print("\n--- map entries ---")
    for a in (Party.A, Party.B):
        for e in await store.list_map_entries("pioneer", a):
            print(f"  {a.value} {e.map_id} [{e.status.value}] imp={e.importance} "
                  f"cov={e.coverage} unc={e.uncertainty}  {e.title}")

    print("\n--- issues ---")
    for i in await store.list_issues("pioneer"):
        print(f"  {i.issue_id} {i.from_agent.value}->{i.to_agent.value} "
              f"[{i.state.value}/{i.resolution.value if i.resolution else '-'}] "
              f"p={i.priority} target={i.target.type.value}:{i.target.id}"
              f"{'#' + i.target.section if i.target.section else ''}")
        print(f"      {i.title}")

    print("\n--- shared sources ---")
    for s in await store.list_sources("pioneer"):
        print(f"  {s.source_id} {s.title}  {s.url}")


if __name__ == "__main__":
    asyncio.run(main())
