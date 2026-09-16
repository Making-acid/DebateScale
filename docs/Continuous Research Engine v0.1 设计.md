# Continuous Research Engine v0.1 设计

> 本文保留为 v0.1 历史基线。当前研究方法与 Pass 契约见《Continuous Research Engine v0.2 设计.md》。

## 0. 一句话定义

> **Continuous Research Engine 是一个以 Research Pass 为核心计算单位的双研究主体系统：第一次独立广泛开图，随后双方通过高预算自主 Deep Research、Semantic Diff、Issue 和共享来源不断重定向下一份研究预算，直到双方在最新完整状态下都无法提出值得再启动一个完整 Pass 的重要研究任务。**

它不是"两个 Agent 轮流搜网页"，也不是"多 Agent 辩论"。它追求的是：**长研究、广覆盖、深挖掘、强纠错、可持续积累**，但外层循环尽量少——真正大量的 search / read / reasoning 都发生在一次 Research Pass 内部。

---

## 1. 三个时间尺度（绝不能混）

```text
微观：Tool Call
      search / read / browser / code / MCP
      模型自己决定，Runtime 不干预研究策略

中观：Research Pass
      一次完整自主研究，最重要的计算单位

宏观：Research Cycle
      A、B 各完成一次 Pass，引擎推进与收敛的单位
```

Runtime **不调度一次次搜索**，只负责把一次 Pass 交给谁。

---

## 2. 两个完整研究主体

A 和 B 完全对称，都拥有完整的 Deep Research 能力（搜索、网页阅读、论文/数据库、MCP/Tools、文件、代码、推理、引用追踪、反证搜索、分支探索）。

不存在 `A = researcher, B = critic`，而是 `A = researcher, B = researcher`。

核心原则：

> **能力共享，世界共享，视角不共享。**

Source Pool 可以共享，但 Blackboard、Research Map、研究轨迹分别独立。双 Agent 的价值来自两条真正独立研究路径的碰撞，而不是把一个 Research Agent 拆成两个半功能模块。

---

## 3. 时间结构（非对称）

### 3.1 Step 1：Expansion Pass（纯展开）

A/B **互相不可见**，各自独立完成一次高预算 Deep Research。

目标不是"什么最正确"，而是**尽可能看见问题空间**，最大化重要方向的召回率。主动寻找：定义、背景、历史、机制、不同群体、不同学科、不同地区、已有研究、争议、反例、关键来源、未知问题、潜在研究方向。

第一步回答的问题是：**"这个问题里面到底有什么？"**

### 3.2 First Collision（补图，非攻击）

Expansion 完成后，两边第一次读取对方成果。最重要的事是**补图**：

```text
B 发现 A 没想到的重要方向 → A 加入自己的 Research Map
B 找到重要论文        → 进入共享 Source Pool
B 出现明确证据错误    → A 创建 Issue
A 与 B 观点不同       → 什么都不一定需要做
```

必须坚持：**Difference ≠ Error**。双方得出不同判断，并不自动产生工单。

### 3.3 Step 2~N：Continuous Research Cycle

研究哲学从"还有什么"变为：

> **在现在已经知道这么多以后，下一整份研究预算最值得花在哪里？**

不是平均探索所有方向，而是根据当前状态动态分配算力。高重要性 + 低覆盖 + 高不确定的方向优先；结论稳定、覆盖度极高的方向不再重复投入。

**时序：串行交替 + 轮换先手。**

```text
Cycle 1: A Pass → commit → B 读 A 的 Semantic Diff → B Pass → commit
Cycle 2: B Pass → commit → A 读 B 的 Semantic Diff → A Pass → commit
```

后一方立刻利用对方最新发现，又不让某一方永远拥有固定后手优势。这里的"交替"不是辩论式的必须回应：对方 Diff 只是本轮输入之一，Agent 可以判断"这些变化不重要，我继续自己的路线"。

---

## 4. 三个持久认知层

```text
Research Map          → 面向未来："还有什么值得研究？"
Research Unit         → 面向现在："我现在知道 / 认为些什么？"
Source Pool           → 面向底层："这些认识建立在哪些资料上？"
```

### 4.1 Research Map

记录研究空间和未来研究方向，面向未来。条目形如：

```text
短期情绪噪声
coverage: medium
uncertainty: high
importance: high
status: active
```

### 4.2 Research Unit / Blackboard

面向现在，是最关键的**中尺度认知表示**。不能是一句话一个 atomic claim，也不能是一篇五万字报告，而是一块能够独立理解、修改、引用、互审的完整认知。

```text
## 短期好感变化存在解释噪声

Status: tentative
Confidence: medium

Finding:
……

Evidence:
……

Implication:
……

Remaining uncertainty:
……
```

Blackboard 是 A/B 各自独立、对方只读的集合：

```text
A：自己可读写，B 只读
B：自己可读写，A 只读
```

Research Unit 是"研究之后留下什么"的基本单位。

### 4.3 Source Pool（共享）

保存来源、元数据、原文、发现者、被哪些 Unit 引用。A 找到论文后 B 不必重新搜索，原始材料进入共享池。

> **Source 共享，Interpretation 不共享。**

B 读同一篇论文后仍可以判断"A 错读了"并挂 Issue。

---

## 5. 临时工作区（Temporary Workspace）

研究过程中的混乱状态（临时假设、失败搜索、奇怪线索、半成品解释、未验证来源、冲突笔记）**不进持久状态**。区分：

```text
Temporary Research Workspace  → 研究中的混乱状态
Persistent State              → 经过筛选的稳定认识
```

一句话：**研究过程可以脏，提交必须干净。** 临时工作区是 Agent 自己的 scratch 文件，Runtime 只给文件系统、不解析。

---

## 6. Engine Action 集（最小控制面）

Engine Action 只处理**持久状态变化**。`search / read / browser / code` 都是 Pass 内部 Tool Call，不是 Engine Action。

```text
update_unit
update_map
create_issue
respond_issue
close_issue
conclude_pass
```

原则：**Tools 改变模型知道什么，Actions 改变引擎保存什么。**

Source 由工具层自动登记进共享 Source Pool，Unit 只引用 source_id。

---

## 7. Semantic Diff 与 mutation log

`what_changed + why` 属于 mutation log（一次更新事件本身），不属于 Unit 的 frontmatter。

三种东西职责彻底分开：

```text
Unit         → 当前认知状态（现在是什么）
mutation log → 这次认知怎么变、为什么变（怎么变的）
Git          → 原始文字历史（字面怎么变的）
```

**mutation log 是引擎的真相源**（append-only），Blackboard 文件、Semantic Diff、Issue Archive 全是它的投影。

B 不默认读 A 的完整 Blackboard，更不默认吞 Raw Git Diff。B 主要看到的是聚合后的 Semantic Diff：

```text
A Pass #3

ru_a_0017:
  claim narrowed
  why: new longitudinal evidence

map_009:
  reopened
  why: opponent issue exposed uncertainty

issue_014:
  created
```

> Git Diff 保存文字变化，Semantic Diff 保存认知变化。后者才是另一个 Research Agent 真正关心的。

Semantic Diff 为主，Raw Git Diff 兜底（要核查具体措辞时按需查看）。

---

## 8. Issue 互审协议

A/B 正常通信只有三种介质：**Blackboard、Semantic Diff、Issue**。

对方真正有问题时才挂工单。Issue 有三种作用：**纠错、暴露合理分歧、生成新的 Research Task**。被指出的一方可以不立刻辩解，而是把"验证 X→Y 因果关系"写回 Research Map——Issue 本身就是研究空间的生成器。

### 8.1 生命周期与关闭原因分离

```text
state: open | closed
resolution: resolved | withdrawn | clarified | unresolved | disagreement | superseded
```

`state=closed + resolution=disagreement` = 工单不需要继续处理，但双方并未达成一致。**关闭不删除。**

### 8.2 target 多态引用

```text
target:
  type: unit | map | source | issue | blackboard
  id: ru_a_0017
  section: implication
```

统一成一个结构化引用，指向新实体类型时无需改 schema。

### 8.3 Issue Archive → Pattern Library

关闭的 Issue 记录"我们曾经怎样想错、怎样被纠正"，长期积累成 Failure / Reasoning Pattern Library，未来用 RAG 按需召回。**错误的 Issue 也保留**——系统既知道"人容易怎样犯错"，也知道"Critic 容易怎样错误地以为别人犯错"。

---

## 9. Pass 终止：硬预算 + 软收敛 + Exit Audit

### 9.1 硬预算（Runtime）

Runtime 给 token / 时间 / tool call / 成本等**硬上限**，防止失控。

### 9.2 软收敛（Agent）

预算以内，Agent 自己判断当前 Pass 的边际信息增益是否明显下降，主动 `conclude_pass`。但 conclude 不能只是"我觉得差不多了"，必须附 **Pass Conclusion**：这轮试图解决什么、实际改变了什么、还剩哪些重要未知、为什么本 Pass 不值得继续追、下一 Pass 最值得研究什么。

`conclude_pass` 只意味着"这份预算我没有明显值得继续花的地方"，**绝不意味着整个研究完成**。

### 9.3 Exit Audit（硬闸门）

结束前 Agent 必须进行一次短检查（conclude_pass 的必答字段）：有没有重要方向没碰？关键 claim 是否只靠弱来源？多个来源是否实为同一原始出处？重要冲突是否没解释？有没有把"没搜到"写成"不存在"？

本质是：**在结束前主动试图找到一个继续研究的理由。找得到就别结束，找不到才 conclude。**

---

## 10. 状态机

```text
CREATED
   → EXPANSION        (A/B 并行开图)
   → COLLISION        (补图，非攻击)
   → CONTINUOUS       (Cycle 交替 + 轮换先手)
        ↺ 每个 Cycle：A Pass → commit → B 读 Semantic Diff → B Pass → commit
   → CANDIDATE_STABLE (双方 conclude_pass 均无高价值方向 + 无高优先 Issue/Map branch)
   → STABILITY_CHECK  (轻量：A/B 看全局后回答"能否指出一个值得开一整 Pass 的任务")
        ├─ 有 → 写回 Research Map → 回 CONTINUOUS
        └─ 无 → STABLE_FOR_REVIEW
   → HUMAN_REVIEW     (H→A / H→B 挂 Issue → Continue 回 CONTINUOUS；Accept → SNAPSHOT)
```

区分三组终止概念：

```text
conclude_pass    = "我这一个 Pass 该收手了"
CANDIDATE_STABLE = "双方都认为没有值得再开下一 Pass 的高价值方向"
STABLE_FOR_REVIEW = 经 stability_check 确认后的交还用户状态（非 FINISHED FOREVER）
```

---

## 11. Human-between-loops

模型高速研究时用户不插进去（内部状态混乱）。正确节奏：

```text
Research Cycle → A/B 内部研究互审 → 状态稳定 → 全部暂停 → 用户 Review → Continue
```

用户看到：A/B 稳定 Blackboard、主要变化、未解决问题、当前分歧、Issues、新来源。然后可挂 `[H→A]` / `[H→B]` 工单，再 Continue。这是 **Human-between-loops**，不是 Human-in-the-loop。

---

## 12. 字段冻结（v0.1 接口，非认知本体论）

frontmatter 只放 **Runtime 必须稳定读取的控制字段**；Finding / Evidence / Implication 等认知内容留在 Markdown 正文，不把 Blackboard 做成 YAML 填表系统。

```text
Research Unit
  unit_id
  status
  source_ids

Research Map
  map_id
  status
  importance     ← Agent-facing metadata
  coverage       ← Agent-facing metadata
  uncertainty    ← Agent-facing metadata

Issue
  issue_id
  from
  to
  target         → {type, id, section}
  priority
  state          → open | closed
  resolution     → resolved | withdrawn | clarified | unresolved | disagreement | superseded
```

**Agent-facing metadata**（importance / coverage / uncertainty / confidence 等）是 Agent 的语义判断，Runtime **只能保存、传递，不能拿它们写语义规则**。

`unit_id` 不可变（如 `ru_a_0017`），文件可重命名，Issue 永远指 unit_id 而非路径。`created_at / tags / version / updated_by` 等留待代码真正需要时再长。

> **现在冻结的是 v0.1 的接口，不是"研究认知究竟由什么组成"的终极本体论。**

---

## 13. Skill 层

Runtime 不判断"什么重要、什么可靠、Issue 是否成立、研究是否够深"。这些都在 Skill + LLM 里。

### 13.1 全程软准则（内化）

```text
- 先宽后窄：面对陌生区域先扇出看清信息空间，不过早锁定第一条路线
- search·think 交替：每批信息后重新判断"这改变了什么"，再决定下一步
- 重新 fan-out：新发现引出新概念时允许围绕它重新展开
- sunk cost = 0：允许放弃失败路线、回溯
- 高价值 claim 深查，低价值细节跳过
- 找最可能改变认知的证据，而非更多支持性证据
- 临时工作区：研究过程可以脏，提交必须干净
```

### 13.2 硬责任（Duty，需被 Exit Audit 检验）

```text
Provenance Duty               → 来源问责：
  对重要 claim，我现在引用的是"别人说原始证据是什么"，还是我真的看了原始证据？
  （来源发现 source discovery 与来源调查 source investigation 必须分开）

Adversarial Verification Duty → 对抗自检：
  主动寻找反证、替代解释、边界条件和来源冲突，
  不要寻找更多证据，寻找最可能改变当前认知状态的证据
```

### 13.3 硬闸门（Exit Audit）

结束前强制检验两个 Duty 是否尽到，并判断是否真的找不到高信息增益的下一动作。

### 13.4 Pass Mission（软计划）

Pass 开头生成软计划（本 Pass 目标 / 当前最值得调查 / 最可能改变判断的未知），**允许十分钟后全部推翻**，不写死完整步骤。

---

## 14. Runtime 职责边界

Runtime 只干机械工作：

```text
分配 Pass
保存文件
执行 Engine Action
维护权限（谁能写哪个 Blackboard）
登记 Source
生成 Semantic Diff
路由 Issue
Git commit
管理预算
切换状态
```

Runtime 不判断方向重要性、证据可靠性、Issue 成立与否、研究是否够深、下一步搜索什么。**真正的研究智能都在 Skill + LLM 里。**

---

## 15. 与普通 Deep Research 的本质差异

```text
普通 Deep Research：Research Pass → Report → End
本引擎：           Research Pass → 改变长期认知状态 → 另一研究者读变化 → 下一次 Pass
```

别人的优秀经验用来把**单次研究做强**；本引擎的核心创新在于**让强 Research Pass 不断累积、互相干扰、纠错、重新定向**，而不是每次从零开始写报告。

---

## 16. 实现切分（里程碑）

```text
M0  固化设计文档（本文档）
M1  数据模型：ResearchUnit / ResearchMapEntry / Issue / Source / Mutation / ResearchSession
    纯 dataclass/Pydantic，落地字段冻结
M2  端口定义：LLMPort / SearchPort / ToolPort / StorePort（Protocol 抽象，框架无关）
M3  Engine Action + mutation log：6 个 action、append-only mutation log、
    Blackboard 文件投影、Semantic Diff 聚合
M4  状态机 + 编排：完整状态机、交替 + 轮换先手、硬预算
M5  Skill 层：Deep Research Skill（Duty + Exit Audit）、Expansion Skill、决策 Skill
M6  验证：mock LLM 跑通完整周期（Expansion → Cycles → Stable）
```
