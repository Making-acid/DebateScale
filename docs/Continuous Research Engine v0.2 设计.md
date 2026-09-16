# Continuous Research Engine v0.2 设计

## 0. 一句话定义

Continuous Research Engine 是辩题工作流中的第一个主要认知引擎。它在系统刚接收到辩题时，让两个分别处于正反立场的完整研究主体独立完成广泛、深入、可追溯且包含自主综合的研究，再通过低强度交叉审查修正错误、解释分歧，最终形成可供用户和后续认知引擎使用的正反立场研究基础。

它回答的不是“谁赢”，也不是“怎样击败对方”，而是：

```text
这道辩题涉及什么？
前人已经知道和讨论了什么？
站在正反两个立场上，分别有哪些可用知识、观点、标准和论证路径？
哪些内容可靠，哪些仍然未知？
双方为什么会得到不同结论？
```

核心原则：

> 立场固定，论路开放；搜索优先，对抗克制；允许差异，强制纠错。

---

## 1. 在产品中的位置

```text
接收辩题
   ↓
Continuous Research Engine
   ↓
正反双方研究基础 + 共享来源池 + 分歧地图
   ↓
循环对抗引擎 / 核验引擎 / 模拟辩论引擎 / 人类 Review
```

本引擎是基础研究插件，不承担后续循环对抗引擎的职责。

### 本引擎负责

- 理解并拆解陌生辩题
- 广泛发现信息空间
- 深挖重要来源与证据链
- 整理前人理论、事实、案例和观点
- 在固定立场下形成自主综合和候选观点
- 记录证据限制、不利材料和未知问题
- 通过双方互审修正明确错误
- 解释并保留无法由事实检查直接消除的分歧

### 本引擎不负责

- 让双方互相说服
- 对每个观点发动递归攻击
- 追求极限思想实验
- 判断最终比赛输赢
- 为了制造对抗而创建 Issue
- 强行把价值分歧合并成共识

---

## 2. 两个位置固定的完整研究主体

A、B 分别获得明确的正反立场。立场是研究条件，不是等待 Agent 自己发现的研究结论。

```text
Researcher A
  assigned standpoint: 正方命题

Researcher B
  assigned standpoint: 反方命题
```

每个 Agent 的主要问题是：

> 在我被分配的立场下，这道辩题有哪些可以使用的知识、理论、事实、价值标准、观点和论证路径？

立场固定不意味着论证固定。Agent 可以：

- 提出多套相互竞争的己方观点
- 改变定义和评价标准
- 放弃薄弱论据
- 收缩主张的适用范围
- 吸收不利证据并重新解释
- 提出尚待验证的新假说

但 Agent 不应退回中立总结，也不应隐瞒与己方不利的可靠材料。

---

## 3. 两种深度

### 3.1 信息空间的广度

广度不是网页数量，而是重要维度的覆盖率。通用维度包括：

- 概念、定义和语言用法
- 历史背景和已有争论
- 理论传统和不同学科
- 现实机制和因果结构
- 主体、群体和利益相关者
- 场景、地区和人口差异
- 短期、长期和二阶影响
- 已有研究、数据和关键来源
- 政策、制度和实践案例
- 反例、异常和边界条件
- 现有正反观点
- 未知问题和测量困难

研究维度应随辩题类型变化。

#### 价值辩题

优先扩展概念解释、伦理或哲学传统、评价标准、文化经验、典型情境、群体价值冲突和边界案例。不要为了数字而搜索数字。

#### 政策辩题

优先扩展现状基线、政策目标、执行机制、法律制度、国内外案例、成本、激励、替代方案、利益相关者、风险、可执行性和短长期效果。

#### 因果或事实辩题

优先扩展变量定义、测量方式、因果机制、实验与观察证据、混杂因素、异质性、时间顺序、复现和证据冲突。

### 3.2 信息挖掘的深度

本引擎所说的深度，首先是对信息和来源挖得足够深：

```text
搜索结果
→ 二手材料
→ 原始论文、报告、数据或文本
→ 方法、样本、口径和时间
→ 实际结论
→ 适用边界
→ 未被证明的部分
→ 对当前辩题的意义
```

Source Discovery 只提供线索。重要 Claim 在进入稳定认知前，必须尽量完成 Source Investigation。

---

## 4. AI 的自主综合责任

系统不能只复述前人。每个 Agent 必须明确区分三个层次：

```text
Source Statement   来源明确说了什么
Agent Inference    Agent 从一个或多个来源中推导出什么
New Hypothesis     Agent 提出的、仍需要检验的新假说
```

允许的自主综合包括：

- 连接不同学科中的相似机制
- 将已有理论应用到当前辩题
- 发现材料之间真正的冲突或范围差异
- 识别隐藏变量和遗漏群体
- 提出新的分类方式
- 组合成前人未直接提出的候选观点
- 从证据缺口反推出新的研究任务

自主综合必须保留推理来源和不确定性，不能冒充已有事实。

---

## 5. Pass One 是完整 Deep Research

Pass One 不再被定义为简短的 Expansion。它是每个 Agent 独立完成的一次高预算、端到端、带立场条件的 Deep Research。

### 5.1 初始研究骨架

搜索前先形成一版可推翻的 Position Research Skeleton：

```text
Assigned Standpoint
Proposition Interpretation
Debate Type
Definitions and Comparison Worlds
Candidate Standards and Burdens
Candidate Viewpoint Families
Possible Mechanisms
Stakeholders / Contexts / Time Horizons
Evidence Needs
Known Risks and Counterevidence
```

骨架是搜索的起点，不是最终答案。

### 5.2 广泛勘探

使用简短、宽泛、相互区分的查询发现信息地形。目标是找到概念、研究传统、关键术语、代表性来源、已知争议和潜在分支，而不是立即锁定第一条看起来可用的路线。

### 5.3 动态问题图

Research Map 的每个条目都应是可执行的“观点到证据”问题，而不是主题标签。

```text
title
question
supports_or_tests
required_evidence
current_coverage
possible_failure
next_queries
```

新搜索结果可以新增、合并、关闭、拆分或降低一个分支的优先级。

### 5.4 选择性深挖

广泛勘探后，Agent 选择最重要、覆盖最低、最可能改变研究骨架的分支进行来源调查。不是每个方向平均投入。

### 5.5 搜索与综合交替

每批重要信息后必须回答：

```text
这改变了什么？
它确认、修改、限制、拆分还是删除了骨架中的什么？
它产生了什么新问题？
下一次搜索为什么值得做？
```

搜索结果必须持续修改研究对象。禁止到最后才把大量互不关联的笔记拼成总结。

### 5.6 反证与边界检查

Agent 必须主动寻找会削弱己方候选观点的证据、替代解释和边界条件。这是质量控制，不是要求 Agent 放弃立场或输出“双方都有道理”。

### 5.7 Pass One 提交物

每个 Agent 至少提交：

1. 一份完整的立场研究骨架
2. 前人工作地图
3. 可用知识和重要来源
4. 候选定义与评价标准
5. 候选观点和论证路径
6. 不利证据与适用边界
7. Agent 自主推论与待验证假说
8. 可执行的后续 Research Map
9. 完整 Pass Conclusion

---

## 6. 持久状态的使用方式

v0.2 不新增庞大的本体结构，继续使用现有实体，但改变其工作契约。

### Research Unit

至少一个 Unit 必须充当持续修订的整体立场研究骨架。其他 Unit 用于值得独立保存、引用和互审的知识块。

Unit 不是搜索笔记。它应说明 Finding、Evidence、Implication、Limitations、Relation to Standpoint 和 Remaining Uncertainty。

### Research Map

Map 是动态研究问题图。每个方向必须说明它服务或检验哪个候选观点，需要什么证据，以及什么发现会让它关闭、收缩或转向。

### Source Pool

共享原始材料和来源元数据。共享 Source，不共享 Interpretation。

### Issue

Issue 用于明确错误和需要核查的具体问题，不用于记录所有立场差异。

### Mutation Log 与 Semantic Diff

继续记录认知状态怎样变化。Semantic Diff 是变化摘要；在 Collision 阶段，双方还必须能够查看对方完整的 Pass One Unit 和相关 Source，不能只靠 Diff 猜测对方论证。

---

## 7. Collision 是低强度交叉审查

Pass One 完成后，双方第一次读取对方成果。目标是补盲、纠错和解释差异，不是互相说服。

### 7.1 可纠正错误

包括事实错误、来源误读、来源无法追溯、相关性冒充因果性、结论超过证据范围、内部矛盾和无效推理。

处理：创建定向 Issue，核查，进行小范围修改，关闭并保留记录。

### 7.2 未解决的经验性冲突

双方可能依据不同方法、群体、场景或时间尺度的可信材料得出不同结论。此时生成新的 Research Map 任务并保留 Unresolved，不提前判定一方错误。

### 7.3 真正的规范性分歧

双方可以承认相同事实，却因为定义、评价标准、价值排序或风险偏好不同而得出不同结论。记录双方共享事实和精确分叉点，不在本引擎中强制解决。

### 7.4 互补差异

对方发现了自己遗漏的重要维度、概念或来源。相关内容进入自己的研究骨架、Map 或共享 Source Pool。

原则：

```text
Difference != Error
Error should be corrected
Empirical uncertainty should be researched
Normative disagreement should be explained and preserved
```

---

## 8. Continuous Pass

Pass Two 以后，每个 Pass 仍然是完整研究预算，而不是一次搜索动作。Agent 根据当前整体骨架、Research Map、对方最新变化和收到的 Issue，选择最值得投入的一条或一组相关任务。

Pass 的工作可以是：

- 深挖关键证据链
- 解决经验性冲突
- 核查对方指出的错误
- 检验自主综合出的新假说
- 补充遗漏群体或场景
- 重构一组候选观点
- 追踪原始来源
- 关闭已经充分回答的问题

对方的变化只是研究输入之一。研究仍然是本引擎的中心活动。

---

## 9. Pass Conclusion 契约

每个 Pass 必须提交：

```text
summary
attempted
changed
remaining_unknowns
why_stop
next_pass
no_high_value_direction
```

其中 changed 必须描述整体研究骨架如何变化，不能只报告“搜索了哪些网站”。

Pass One 在没有提交至少一个整体 Research Unit 和一个可执行 Research Map 前不能结束。

---

## 10. 稳定条件

进入 STABLE_FOR_REVIEW 不意味着辩题已经解决，只意味着当前搜索型引擎没有明显值得再开启完整 Pass 的高价值研究任务。

稳定前应满足：

- 主要信息空间已经覆盖
- 高价值观点拥有可用来源链
- 重要来源已尽量追到原始材料
- 双方各有一份连贯的立场研究骨架
- 可纠正错误已经处理或明确挂起
- 经验性冲突已经解释或转成研究问题
- 规范性分歧已经标出精确分叉点
- 剩余未知明确可见

稳定状态应向后续引擎提供：

```text
Shared Topic Map
Position Research Package A
Position Research Package B
Shared Source Pool
Correction / Issue Archive
Unresolved Empirical Questions
Normative Disagreement Map
```

---

## 11. Runtime 与 Skill 的边界

Runtime 继续只执行机械责任：

- 分配固定立场
- 分配和限制 Pass 预算
- 暴露工具
- 保存 Unit、Map、Source、Issue 和 Mutation
- 在 Collision 提供对方完整成果
- 检查 Pass 是否满足结构性提交要求
- 切换状态

Skill 与 LLM 负责：

- 判断辩题类型
- 决定研究维度
- 生成和修订研究骨架
- 选择查询和来源
- 判断信息重要性
- 形成自主综合
- 分类具体分歧
- 判断下一份研究预算投向

Runtime 不判断什么观点重要、哪个价值标准正确，也不试图消除立场差异。

---

## 12. v0.1 到 v0.2 的关键变化

```text
v0.1: Expansion 主要追求方向召回
v0.2: Pass One 是立场化、端到端的完整 Deep Research

v0.1: Research Map 容易成为主题清单
v0.2: Map 必须表达观点与证据之间的可执行研究问题

v0.1: Unit 可以成为分散发现
v0.2: 至少一个 Unit 必须维护持续修订的整体研究骨架

v0.1: 双方身份是同题独立 Researcher
v0.2: 双方拥有明确固定立场，但研究和纠错优先于对抗

v0.1: Collision 主要读取 Semantic Diff 并补图
v0.2: Collision 读取完整成果，将差异分为错误、经验冲突、规范分歧和互补发现

v0.1: conclude_pass 最低只需 summary 和稳定信号
v0.2: conclude_pass 必须完整报告研究、认知变化、未知、停止原因和下一 Pass
```

---

## 13. 方法参考

本版本吸收但不照搬以下系统经验：

- OpenAI Deep Research：长程、多步、可回退并根据新信息调整的研究轨迹
- STORM：在正式输出前发现多视角、提出问题、检索并组织结构
- MindSearch：根据搜索结果动态生长的子问题图
- Anthropic Research：明确任务目标、交付格式、工具和边界；先宽后窄；搜索与思考交替
- Test-Time Diffusion Deep Researcher：以持续修订的草稿或骨架反向驱动下一轮检索

本引擎的独特组合是：固定正反立场、独立完整研究、共享来源、独立解释、低强度纠错，以及对经验冲突和价值分歧的长期保留。
