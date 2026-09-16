const state = { data: null, running: false, modelConfig: null, providers: [], providerModels: {}, currentJob: null, pollTimer: null, polling: false };
const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
const esc = (value = "") => String(value).replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;").replaceAll('"', "&quot;").replaceAll("'", "&#039;");

const viewNames = {
  overview: "当前成果", research: "双方立论", issues: "攻防要点",
  sources: "证据与来源", report: "成果报告", history: "推演历史", settings: "模型 API"
};

function toast(message) {
  const el = $("#toast"); el.textContent = message; el.classList.add("show");
  setTimeout(() => el.classList.remove("show"), 2200);
}

function switchView(name) {
  $$(".page").forEach(page => page.classList.toggle("active", page.id === `view-${name}`));
  $$(".side-nav button").forEach(button => button.classList.toggle("active", button.dataset.view === name));
  $("#crumb").textContent = viewNames[name]; window.scrollTo({ top: 0, behavior: "smooth" });
}

function heading(kicker, title, description, extra = "") {
  return `<div class="page-heading"><div><span class="page-kicker">${kicker}</span><h1>${title}</h1><p>${description}</p></div>${extra}</div>`;
}

function partyMeta(party) {
  return party === "A"
    ? { name: "正方", tone: "a", position: state.data.session.position_a }
    : { name: "反方", tone: "b", position: state.data.session.position_b };
}

function argumentSupport(argument) {
  const evidenceCount = (argument.evidence_ids || []).length;
  const needs = argument.evidence_need || [];
  if (argument.support_type === "reasoning") {
    return { short: "自主逻辑论证", detail: "主要依靠定义、推理、比较与反例成立，无需用引用装饰。", ready: true };
  }
  if (evidenceCount) {
    return { short: `${evidenceCount} 项事实证据`, detail: "包含事实前提，已绑定经过检查的证据记录。", ready: true };
  }
  return { short: `${needs.length || 1} 项事实前提待核验`, detail: "论证方向已形成，但其中的事实前提尚未完成证据核验。", ready: false };
}

function argumentSummary(argument, party, compact = false) {
  const meta = partyMeta(party);
  const support = argumentSupport(argument);
  const ready = argument.status === "defensible" && support.ready;
  return `<button class="argument-card ${meta.tone} ${compact ? "compact" : ""}" data-argument="${esc(argument.argument_id)}" data-party="${party}">
    <div class="card-meta"><span>${meta.name} · 论点 ${argument.argument_id.split("_").at(-1).replace(/^0+/, "")}</span><span class="status-pill">${ready ? "基础可辩护" : "仍在修建"}</span></div>
    <h3>${esc(argument.title)}</h3><p class="argument-claim">${esc(argument.claim)}</p>
    ${compact ? "" : `<div class="argument-foot"><span>${argument.warrant.length} 步机制</span><span>${esc(support.short)}</span><span>v${argument.version}</span></div>`}
  </button>`;
}

function bindArgumentCards() {
  $$('[data-argument]').forEach(button => button.addEventListener("click", () => openArgument(button.dataset.party, button.dataset.argument)));
}

function renderOverview(data) {
  const side = party => data.arguments[party].map(argument => argumentSummary(argument, party, true)).join("");
  const plans = data.plans || {};
  const planPreview = ["A", "B"].map(party => {
    const plan = plans[party];
    if (!plan) return "";
    const meta = partyMeta(party);
    const forecast = plan.estimated_remaining_actions < 0 ? "暂不确定" : `${plan.estimated_remaining_actions} 个行动`;
    return `<article><small>${meta.name} · ${esc(plan.phase)} · v${plan.version}</small><h3>${esc(plan.strategy)}</h3><p>${esc(plan.progress_assessment)}</p><p><strong>剩余：</strong>${esc(plan.remaining_work || "无")}</p><span>${plan.status === "ready_to_conclude" ? "已完成退出审计" : `预计还需 ${forecast}`}</span></article>`;
  }).join("");
  // 首页必须同时呈现双方造成的压力，避免先后顺序让一方垄断“关键攻防”。
  const topRebuttals = [data.rebuttals.A[0], data.rebuttals.B[0]].filter(Boolean);
  $("#overviewResults").innerHTML = `
    <section class="result-section current-result">
      <div class="result-header"><div><span class="page-kicker">CURRENT CASES</span><h2>双方当前有效成果</h2><p>这里只保留经过基础互驳和修复后的当前版本。讨论过程与旧文本已移至“推演历史”。</p></div><span class="stable-chip">✓ 基础论证已形成</span></div>
      <div class="case-overview">
        <section class="case-side a"><header><span class="side-tag">A</span><div><small>正方立场</small><strong>${esc(data.session.position_a)}</strong></div></header>${side("A")}<button class="case-more" data-jump="research">查看正方完整证明链 →</button></section>
        <div class="versus"><span>立</span><i></i><b>VS</b><i></i><span>驳</span></div>
        <section class="case-side b"><header><span class="side-tag">B</span><div><small>反方立场</small><strong>${esc(data.session.position_b)}</strong></div></header>${side("B")}<button class="case-more" data-jump="research">查看反方完整证明链 →</button></section>
      </div>
      <div class="clash-preview"><div><span class="page-kicker">KEY CLASHES</span><h3>当前最重要的攻防</h3></div>${topRebuttals.map(item => `<button data-jump="issues"><strong>${esc(item.title)}</strong><span>${esc(item.current_effect || item.why_it_matters)}</span><i>→</i></button>`).join("")}</div>
      ${planPreview ? `<section class="history-section"><h2>模型自主规划</h2><p>这是模型根据当前辩题持续改写的行动判断，不是引擎预设的固定清单。</p><div class="evidence-list">${planPreview}</div></section>` : ""}
      <div class="result-evidence-note"><span>${data.metrics.arguments}</span> 条当前论证 · <span>${data.metrics.rebuttals}</span> 条有效驳论 · <span>${data.metrics.evidence}</span> 项已检查证据记录 · <span>${data.metrics.sources}</span> 个来源</div>
    </section>`;
  $("#overviewResults").classList.remove("hidden"); bindArgumentCards();
  $$('[data-jump]').forEach(button => button.addEventListener("click", () => switchView(button.dataset.jump)));
}

function renderResearch(data) {
  $("#researchContent").innerHTML = heading("POSITION CASES", "双方如何把自己的论立住", "每一方只代表一个鲜明立场。论点不是资料标题，而是由证明责任、机制、证据、比较影响和适用边界共同组成的可检验结构。") + `
    <div class="dual-board case-board">${["A", "B"].map(party => {
      const meta = partyMeta(party);
      return `<section class="party-board ${meta.tone}"><header class="party-head"><span class="side-tag">${party}</span><div><h2>${meta.name}当前立论</h2><p>${esc(meta.position)}</p></div></header><div class="board-section"><p class="board-section-title">CURRENT ARGUMENTS · 当前有效论点</p>${data.arguments[party].map(argument => argumentSummary(argument, party)).join("")}</div></section>`;
    }).join("")}</div>`;
  bindArgumentCards();
}

function renderIssues(data) {
  const items = [...data.rebuttals.A.map(x => ({...x, owner: "A"})), ...data.rebuttals.B.map(x => ({...x, owner: "B"}))];
  $("#issuesContent").innerHTML = heading("CURRENT REBUTTALS", "双方如何驳斥对方", "这里只展示仍具有解释价值的驳论，并把内部目标编号转写成人能直接理解的攻防。旧版本上的工作记录请在“推演历史”中查看。") + `
    <div class="rebuttal-list">${items.map(item => {
      const target = data.arguments[item.target_agent].find(x => x.argument_id === item.target_argument_id);
      return `<article class="rebuttal-card ${item.owner.toLowerCase()}">
        <header><span class="side-tag">${item.owner}</span><div><small>${item.owner === "A" ? "正方" : "反方"}驳斥${item.target_agent === "A" ? "正方" : "反方"} · 针对「${esc(target?.title || item.target_argument_id)}」</small><h2>${esc(item.title)}</h2></div><span class="attack-type">${esc(item.attack_type)}</span></header>
        <div class="rebuttal-grid"><div><label>对方实际主张</label><p>${esc(item.reconstruction)}</p></div><div><label>攻击发生在哪里</label><p>${esc(item.attack)}</p></div><div><label>为什么足以影响论点</label><p>${esc(item.why_it_matters)}</p></div><div><label>目前产生的效果</label><p>${esc(item.current_effect || "等待对方处理")}</p></div></div>
      </article>`;
    }).join("")}</div>`;
}

function renderSources(data) {
  const sourceById = Object.fromEntries(data.sources.map(source => [source.source_id, source]));
  const evidence = [...data.evidence.A.map(x => ({...x, owner: "A"})), ...data.evidence.B.map(x => ({...x, owner: "B"}))];
  const materialUses = ["A", "B"].flatMap(owner => data.arguments[owner].flatMap(argument =>
    (argument.material_source_ids || []).map(sourceId => ({ owner, argument, source: sourceById[sourceId] }))
  )).filter(item => item.source);
  $("#sourcesContent").innerHTML = heading("EVIDENCE & LEADS", "证据与论点启发分开看", "事实证据负责证明可核验前提；往届辩论、公共讨论与类比材料只负责启发或检验论证。二者不会混作同一种权威背书。", `<span class="stable-chip">${evidence.length} 项证据 · ${materialUses.length} 项启发</span>`) + `
    <div class="evidence-list">${evidence.map(item => {
      const source = sourceById[item.source_id] || {};
      const argument = data.arguments[item.owner].find(x => x.argument_id === item.argument_id);
      return `<article class="evidence-card"><header><span class="source-id">${esc(item.evidence_id)}</span><div><small>${item.owner} 方用于「${esc(argument?.title || "综合判断")}」</small><h3>${esc(item.proposition)}</h3></div><span class="relation ${item.relation}">${item.relation === "supports" ? "支持" : item.relation === "limits" ? "限制" : "反证"}</span></header><div class="evidence-body"><p><strong>材料发现：</strong>${esc(item.finding)}</p><p><strong>方法：</strong>${esc(item.method)}</p><p><strong>局限：</strong>${esc(item.limitations)}</p><p><strong>来源脉络：</strong>${esc(item.provenance)}</p></div><footer><span>${esc(source.title)}</span><a href="${esc(source.url)}" target="_blank" rel="noopener">原始位置 ↗</a></footer></article>`;
    }).join("") || "<p>本轮没有需要外部事实证据的论点。</p>"}</div>
    <section class="history-section"><h2>帮助形成论点的材料</h2><p>这些材料提供了观点、例子或攻击线索；最终论证仍由模型自行重建并负责其逻辑。</p><div class="evidence-list">${materialUses.map(item => `<article class="evidence-card"><header><span class="source-id">${item.owner} 方</span><div><small>用于启发或检验「${esc(item.argument.title)}」</small><h3>${esc(item.source.title)}</h3></div></header><div class="evidence-body"><p>${esc(item.source.content || "该材料被用于论点发现；其观点不自动视为事实。")}</p></div><footer><span>论点材料，不是事实背书</span><a href="${esc(item.source.url)}" target="_blank" rel="noopener">原始位置 ↗</a></footer></article>`).join("") || "<p>当前论点尚未显式绑定启发材料。</p>"}</div></section>`;
}

function renderHistory(data) {
  const revisionBlocks = Object.entries(data.argument_revisions).filter(([, versions]) => versions.length > 1).map(([id, versions]) => {
    const party = id.includes("_a_") ? "A" : "B";
    return `<details class="history-block"><summary><span>${party} 方 · ${esc(versions.at(-1).title)}</span><b>${versions.length} 个版本</b></summary><div>${versions.map(version => `<article><small>版本 v${version.version} · ${version.status}</small><h3>${esc(version.claim)}</h3><p><strong>适用边界：</strong>${esc(version.scope || "尚未明确")}</p>${version.defense.length ? `<p><strong>新增防守：</strong>${version.defense.map(esc).join("；")}</p>` : ""}</article>`).join("")}</div></details>`;
  }).join("");
  const planBlocks = Object.entries(data.plan_revisions || {}).map(([party, versions]) => `<details class="history-block"><summary><span>${party} 方 · 自主计划演化</span><b>${versions.length} 个版本</b></summary><div>${versions.map(plan => `<article><small>${esc(plan.phase)} · v${plan.version} · ${plan.status}</small><h3>${esc(plan.strategy)}</h3><p>${esc(plan.progress_assessment)}</p><p><strong>剩余工作：</strong>${esc(plan.remaining_work)}</p><p><strong>改动原因：</strong>${esc(plan.change_reason)}</p></article>`).join("")}</div></details>`).join("");
  $("#historyContent").innerHTML = heading("AUDIT TRAIL", "推演与版本历史", "这里保存双方当时看见的论证版本、机器协作记录以及修改结果。它用于追溯，不占据当前成果的主要阅读空间。") + `
    <section class="history-section"><h2>自主计划演化</h2>${planBlocks || "<p>旧研究没有持久化规划记录。</p>"}</section>
    <section class="history-section"><h2>论证版本演化</h2>${revisionBlocks || "<p>当前没有多版本论证。</p>"}</section>
    <section class="history-section"><h2>内部修复记录</h2>${data.issues.map(issue => `<details class="history-block"><summary><span>${issue.from_agent} → ${issue.to_agent} · ${esc(issue.title)}</span><b>${issue.state === "closed" ? "已处理" : "待处理"}</b></summary><div><article><p>${esc(issue.body)}</p><small>内部目标：${esc(issue.target.type)} / ${esc(issue.target.id)} · 处理结果 ${esc(issue.resolution || "未定")}</small></article></div></details>`).join("") || "<p>无内部修复记录。</p>"}</section>
    <section class="history-section"><h2>运行阶段</h2>${data.passes.map(pass => `<details class="history-block"><summary><span>Pass ${pass.number} · ${pass.agent} 方 · ${esc(pass.phase)}</span><b>${pass.changes.length} 项变更</b></summary><div><article><h3>${esc(pass.summary)}</h3><p>${esc(pass.why_stop)}</p><ul>${pass.changes.map(change => `<li>${esc(change.what_changed || change.action)}</li>`).join("")}</ul></article></div></details>`).join("")}</section>`;
}

function openArgument(party, argumentId) {
  const argument = state.data.arguments[party].find(item => item.argument_id === argumentId);
  const evidenceById = Object.fromEntries(state.data.evidence[party].map(item => [item.evidence_id, item]));
  const sourceById = Object.fromEntries(state.data.sources.map(item => [item.source_id, item]));
  const support = argumentSupport(argument);
  $("#dialogContent").innerHTML = `<h1>${esc(argument.title)}</h1><div class="dialog-meta">${partyMeta(party).name}当前论点 · ${esc(argument.argument_id)} · v${argument.version} · ${argument.status === "defensible" && support.ready ? "基础可辩护" : "仍在修建"}</div>
    <div class="argument-detail"><section><label>论证性质</label><p><strong>${esc(support.short)}</strong> · ${esc(support.detail)}</p>${(argument.evidence_need || []).length ? `<ul>${argument.evidence_need.map(item => `<li>${esc(item)}</li>`).join("")}</ul>` : ""}</section><section><label>核心主张</label><p class="lead-claim">${esc(argument.claim)}</p></section><div class="detail-pair"><section><label>证明责任</label><p>${esc(argument.burden)}</p></section><section><label>胜负判准</label><p>${esc(argument.criterion || "由整体立论共同承担")}</p></section></div><section><label>证明机制</label><ol>${argument.warrant.map(step => `<li>${esc(step)}</li>`).join("")}</ol></section><section><label>自己的推进</label><p>${esc(argument.original_contribution || "当前是基础论点，尚未明确记录超出常规立论的推进。")}</p></section><section><label>比较性影响</label><p>${esc(argument.impact)}</p></section><section><label>适用边界</label><p>${esc(argument.scope)}</p></section><div class="detail-pair"><section><label>已知脆弱点</label><ul>${argument.vulnerabilities.map(item => `<li>${esc(item)}</li>`).join("") || "<li>暂无记录</li>"}</ul></section><section><label>目前防守</label><ul>${argument.defense.map(item => `<li>${esc(item)}</li>`).join("") || "<li>暂无记录</li>"}</ul></section></div><section><label>事实证据</label>${argument.evidence_ids.map(id => `<div class="mini-evidence"><strong>${esc(id)}</strong><span>${esc(evidenceById[id]?.finding || "证据记录")}</span></div>`).join("") || `<p>${argument.support_type === "reasoning" ? "本论点不依赖外部事实前提。" : "尚未绑定经过检查的事实证据。"}</p>`}</section><section><label>论点启发材料</label>${(argument.material_source_ids || []).map(id => { const source = sourceById[id] || {}; return `<div class="mini-evidence"><strong>${esc(source.title || id)}</strong><span>${esc(source.content || "帮助形成或检验本论点，不作为事实背书。")}</span></div>`; }).join("") || "<p>本论点由模型自主推演形成，尚未显式绑定外部启发材料。</p>"}</section></div>`;
  $("#detailDialog").showModal();
}

function renderAll(data) {
  state.data = data; renderOverview(data); renderResearch(data); renderIssues(data); renderSources(data); renderHistory(data); renderReport();
  $("#issueBadge").textContent = data.metrics.rebuttals; $("#exportButton").disabled = false;
  loadResearchList();
}

function setPhase(index) {
  $$(".phase").forEach((item, i) => { item.classList.toggle("active", i === index); item.classList.toggle("done", i < index); item.querySelector("i").textContent = i < index ? "✓" : String(i + 1); });
  $$(".phase-line").forEach((line, i) => line.classList.toggle("done", i < index));
}

const phaseIndexes = { queued: 0, expansion: 0, collision: 1, continuous: 2, stability: 3, complete: 4 };

const eventKindNames = {
  pass: "研究阶段", model: "模型决策", decision: "行动计划", search: "网页搜索",
  read: "来源深读", argument: "立论更新", evidence: "证据登记", map: "研究地图",
  rebuttal: "驳论更新", gate: "质量检查", budget: "预算状态", failure: "运行错误",
  state: "状态更新", tool: "研究工具", unit: "研究整合", plan: "自主规划", create_issue: "纠错问题",
  respond_issue: "问题回应", close_issue: "问题关闭", context: "上下文整理"
};

function formatNumber(value) {
  const number = Number(value || 0);
  return number >= 1000 ? `${(number / 1000).toFixed(number >= 10000 ? 0 : 1)}k` : String(number);
}

function budgetMeter(party, budget) {
  if (!budget) return `<article class="budget-card ${party.toLowerCase()}"><span class="side-tag">${party}</span><div><strong>${party === "A" ? "正方" : "反方"}尚未开始</strong><small>等待本方第一个模型行动</small></div></article>`;
  const researchPct = Math.min(100, Math.round(100 * budget.research_calls / Math.max(1, budget.research_call_limit)));
  const tokenPct = Math.min(100, Math.round(100 * budget.tokens / Math.max(1, budget.token_limit)));
  return `<article class="budget-card ${party.toLowerCase()}">
    <div class="budget-title"><span class="side-tag">${party}</span><strong>${party === "A" ? "正方" : "反方"}当前 Pass</strong><small>${budget.research_exhausted ? "外部研究额度已满" : "运行中"}</small></div>
    <div class="budget-row"><span>有效搜索与深读</span><b>${budget.research_calls} / ${budget.research_call_limit}</b><i><em style="width:${researchPct}%"></em></i></div>
    <div class="budget-row"><span>失败缓冲</span><b>${budget.failed_calls} / ${budget.failed_call_limit}</b></div>
    <div class="budget-row"><span>模型轮次</span><b>${budget.model_turns} / ${budget.model_turn_limit}</b></div>
    <div class="budget-row"><span>累计 Token</span><b>${formatNumber(budget.tokens)} / ${formatNumber(budget.token_limit)}</b><i><em style="width:${tokenPct}%"></em></i></div>
    <div class="budget-row"><span>上轮实际输入 / 输出</span><b>${formatNumber(budget.last_input_tokens)} / ${formatNumber(budget.last_output_tokens)}</b></div>
    <div class="budget-row"><span>当前输入估算</span><b>约 ${formatNumber(budget.estimated_context_tokens)} Token</b></div>
    <div class="budget-row muted"><span>滚动上下文</span><b>${budget.context_compactions || 0} 次压缩</b></div>
    <div class="budget-row muted"><span>本地论证整理</span><b>${budget.state_actions} 次 · 不占研究调用</b></div>
  </article>`;
}

function renderProcess(job) {
  const events = Array.isArray(job.events) ? job.events : [];
  const budgets = job.budgets || {};
  $("#processCount").textContent = events.length ? `${events.length} 条行动记录` : "等待行动";
  $("#processBudgets").innerHTML = budgetMeter("A", budgets.A) + budgetMeter("B", budgets.B);
  const visible = events.slice(-120).reverse();
  $("#processEvents").innerHTML = visible.length ? visible.map(event => {
    const party = event.agent === "A" || event.agent === "B" ? event.agent : "";
    const details = (event.details || []).filter(item => item?.value).map(item => `<div><span>${esc(item.label)}</span><p>${esc(item.value)}</p></div>`).join("");
    const time = event.time ? new Date(event.time).toLocaleTimeString("zh-CN", { hour12: false }) : "";
    return `<article class="process-event ${esc(event.status || "working")}">
      <div class="event-rail"><i></i></div>
      <div class="event-main"><header>${party ? `<span class="event-party ${party.toLowerCase()}">${party} 方</span>` : ""}<span>${esc(eventKindNames[event.kind] || event.kind || "研究行动")}</span><time>${esc(time)}</time></header><h4>${esc(event.title || "研究行动")}</h4><p>${esc(event.summary || "")}</p>${details ? `<div class="event-details">${details}</div>` : ""}</div>
    </article>`;
  }).join("") : `<div class="process-empty">模型启动后，搜索目的、查询策略、来源深读和论点更新会依次出现在这里。</div>`;
}

function showRunning(job) {
  state.currentJob = job.id; state.running = true;
  if (job.status !== "failed") $("#resumeDepthWrap").classList.add("hidden");
  $("#launchCard").classList.add("hidden"); $("#runPanel").classList.remove("hidden");
  $("#runTitle").textContent = job.status === "queued" ? "研究正在排队" : "研究正在展开";
  $("#runTime").textContent = job.message || "双方模型正在工作";
  setPhase(phaseIndexes[job.phase] ?? 0);
  renderProcess(job);
  $("#runButton").disabled = true;
  $("#retryButton").classList.add("hidden");
}

async function apiJson(url, options) {
  const response = await fetch(url, options);
  const result = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(result.error || `服务返回 ${response.status}`);
  return result;
}

async function pollResearch() {
  if (!state.currentJob || state.polling) return;
  state.polling = true;
  try {
    const job = await apiJson(`/api/research/${state.currentJob}/status`);
    showRunning(job); await loadResearchList();
    if (job.status === "complete") {
      clearInterval(state.pollTimer); state.pollTimer = null; state.running = false; setPhase(4);
      $("#runTitle").textContent = "深度研究完成"; $("#runTime").textContent = "双方立论、互驳与证据报告已经形成";
      const data = await apiJson(`/api/research/${state.currentJob}`); renderAll(data);
      setTimeout(() => $("#overviewResults").scrollIntoView({ behavior: "smooth", block: "start" }), 220);
    } else if (job.status === "failed") {
      clearInterval(state.pollTimer); state.pollTimer = null; state.running = false;
      $("#runTitle").textContent = "研究未完成"; $("#runTime").textContent = job.error || "模型或搜索服务发生错误";
      $("#runNote").textContent = "配置和已完成的研究不会丢失。修正连接后可以重新发起。";
      $("#questionInput").value = job.question || $("#questionInput").value;
      $("#resumeDepthInput").value = job.request?.depth === "standard" ? "standard" : "deep";
      $("#resumeDepthWrap").classList.toggle("hidden", !job.resumable);
      $("#retryButton").classList.toggle("hidden", !job.resumable);
      $("#runButton").disabled = false; await loadResearchList();
    }
  } catch (error) { $("#runTime").textContent = `暂时无法读取进度：${error.message}`; }
  finally { state.polling = false; }
}

async function runResearch() {
  if (state.running) return;
  if (!state.modelConfig?.ready) { switchView("settings"); toast("请先完成模型 API 配置"); return; }
  const question = $("#questionInput").value.trim();
  if (question.length < 4) { toast("请先填写一个完整辩题"); $("#questionInput").focus(); return; }
  const button = $("#runButton"); button.disabled = true; button.textContent = "正在创建研究…";
  try {
    const job = await apiJson("/api/research/run", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ question, position_a: $("#positionAInput").value.trim(), position_b: $("#positionBInput").value.trim(), depth: $("#depthInput").value }) });
    showRunning(job); await loadResearchList(); await pollResearch();
    state.pollTimer = setInterval(pollResearch, 2500);
  } catch (error) { toast(error.message); button.disabled = false; button.innerHTML = "开始双边研究 <span>→</span>"; }
}

async function resumeResearch() {
  if (!state.currentJob || state.running) return;
  const button = $("#retryButton"); button.disabled = true; button.textContent = "正在恢复…";
  try {
    const job = await apiJson(`/api/research/${state.currentJob}/resume`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ depth: $("#resumeDepthInput").value })
    });
    $("#resumeDepthWrap").classList.add("hidden");
    showRunning(job); await loadResearchList(); await pollResearch();
    state.pollTimer = setInterval(pollResearch, 2500);
  } catch (error) {
    toast(error.message); button.disabled = false; button.textContent = "从检查点继续研究";
  }
}

async function openSavedResearch(sessionId, status) {
  state.currentJob = sessionId;
  if (["queued", "running"].includes(status)) {
    await pollResearch();
    if (!state.pollTimer) state.pollTimer = setInterval(pollResearch, 2500);
    switchView("overview"); return;
  }
  if (status === "failed") { await pollResearch(); switchView("overview"); return; }
  const data = await apiJson(`/api/research/${sessionId}`); renderAll(data); switchView("overview");
}

async function loadResearchList() {
  const result = await apiJson("/api/researches");
  const items = result.items || [];
  $("#researchList").innerHTML = items.length ? items.map(item => `<div class="research-row ${item.id === state.currentJob ? "active" : ""}"><button class="research-item" data-research-id="${esc(item.id)}" data-status="${esc(item.status)}"><span class="status-dot ${esc(item.status)}"></span><span><strong>${esc(item.question || "未命名辩题")}</strong><small>${item.status === "complete" ? `${item.metrics?.sources || 0} 个来源 · 已完成` : item.status === "failed" ? "运行失败 · 点击查看" : esc(item.message || "研究中")}</small></span></button>${["queued", "running"].includes(item.status) ? "" : `<button class="delete-research" type="button" data-delete-research="${esc(item.id)}" data-question="${esc(item.question || "未命名辩题")}" aria-label="删除这条历史" title="删除这条历史">×</button>`}</div>`).join("") : `<div class="research-row active"><div class="research-item"><span class="status-dot"></span><span><strong>尚未开始研究</strong><small>新建辩题后将保存在这里</small></span></div></div>`;
  const failedCount = items.filter(item => item.status === "failed").length;
  $("#failedCount").textContent = failedCount;
  $("#clearFailedButton").classList.toggle("hidden", failedCount === 0);
  $$('[data-research-id]').forEach(button => button.addEventListener("click", () => openSavedResearch(button.dataset.researchId, button.dataset.status).catch(error => toast(error.message))));
  $$('[data-delete-research]').forEach(button => button.addEventListener("click", () => deleteResearch(button.dataset.deleteResearch, button.dataset.question)));
}

async function deleteResearch(sessionId, question) {
  if (!confirm(`删除「${question}」的历史记录？\n\n记录会移入这台电脑的本地回收区，不会立即永久销毁。`)) return;
  try {
    await apiJson(`/api/research/${sessionId}`, { method: "DELETE" });
    if (state.currentJob === sessionId) resetNewResearch();
    await loadResearchList(); toast("历史记录已移入本地回收区");
  } catch (error) { toast(error.message); }
}

async function clearFailedResearches() {
  const count = Number($("#failedCount").textContent || 0);
  if (!count || !confirm(`清理全部 ${count} 条失败记录？\n\n记录会移入这台电脑的本地回收区。`)) return;
  const button = $("#clearFailedButton"); button.disabled = true;
  const selectedWasFailed = state.currentJob && $(`[data-research-id="${state.currentJob}"]`)?.dataset.status === "failed";
  try {
    const result = await apiJson("/api/researches/failed", { method: "DELETE" });
    if (selectedWasFailed) resetNewResearch();
    await loadResearchList(); toast(`已清理 ${result.deleted} 条失败记录`);
  } catch (error) { toast(error.message); }
  finally { button.disabled = false; }
}

function resetNewResearch() {
  if (state.running && !confirm("当前研究会继续在后台运行。是否回到新建辩题页面？")) return;
  if (state.pollTimer) { clearInterval(state.pollTimer); state.pollTimer = null; }
  state.data = null; state.currentJob = null; $("#questionInput").value = ""; $("#positionAInput").value = ""; $("#positionBInput").value = "";
  renderProcess({ events: [], budgets: {} });
  $("#launchCard").classList.remove("hidden"); $("#runPanel").classList.add("hidden"); $("#overviewResults").classList.add("hidden"); $("#exportButton").disabled = true;
  const button = $("#runButton"); button.disabled = false; button.innerHTML = "开始双边研究 <span>→</span>"; switchView("overview"); $("#questionInput").focus();
}

function reportMarkdown() {
  const d = state.data;
  if (d.reader_report) return readerReportMarkdown(d.reader_report);
  const allSources = d.sources || [];
  const evidenceById = Object.fromEntries(
    ["A", "B"].flatMap(party => (d.evidence[party] || []).map(item => [item.evidence_id, item]))
  );
  const usedSourceIds = new Set();
  for (const party of ["A", "B"]) {
    for (const argument of d.arguments[party] || []) {
      for (const sourceId of argument.material_source_ids || []) usedSourceIds.add(sourceId);
      for (const evidenceId of argument.evidence_ids || []) {
        if (evidenceById[evidenceId]?.source_id) usedSourceIds.add(evidenceById[evidenceId].source_id);
      }
    }
    for (const rebuttal of d.rebuttals[party] || []) {
      for (const evidenceId of rebuttal.evidence_ids || []) {
        if (evidenceById[evidenceId]?.source_id) usedSourceIds.add(evidenceById[evidenceId].source_id);
      }
    }
  }
  const sources = allSources.filter(source => usedSourceIds.has(source.source_id));
  const sourceById = Object.fromEntries(sources.map((source, index) => [source.source_id, { ...source, number: index + 1 }]));
  const argumentById = Object.fromEntries(
    ["A", "B"].flatMap(party => (d.arguments[party] || []).map(argument => [argument.argument_id, argument]))
  );
  const cite = ids => (ids || []).map(id => sourceById[id] ? `[${sourceById[id].number}]` : "").filter(Boolean).join(" ");
  const citeEvidence = ids => cite((ids || []).map(id => evidenceById[id]?.source_id).filter(Boolean));
  const clean = value => String(value || "").replace(/\s+/g, " ").trim();
  const lines = [
    "# 双边辩题研究总报告", "",
    `> **辩题：** ${clean(d.session.question)}`, "",
    "本报告已将模型运行记录、内部工单、对象编号和版本信息移除，只保留可供备赛直接阅读和使用的当前有效成果。", "",
    "## 一、报告摘要", "",
    `- **正方立场：** ${clean(d.session.position_a)}`,
    `- **反方立场：** ${clean(d.session.position_b)}`,
    `- **当前成果规模：** ${(d.arguments.A || []).length + (d.arguments.B || []).length} 个核心论点、${(d.rebuttals.A || []).length + (d.rebuttals.B || []).length} 个主要攻防点、${sources.length} 个实际进入成果的来源。`, "",
    "双方真正的分歧不只是对事实作出相反判断，而在于如何界定题目中的核心概念、采用什么比较标准，以及哪些影响应当在特定场景下获得更高权重。以下内容按“主张—证明—证据—边界—攻防”重新整理。", ""
  ];

  for (const party of ["A", "B"]) {
    const sideName = partyMeta(party).name;
    const position = clean(d.session[`position_${party.toLowerCase()}`]);
    lines.push(`## ${party === "A" ? "二" : "三"}、${sideName}完整立论`, "", `**立场：${position}**`, "");
    for (const [index, argument] of (d.arguments[party] || []).entries()) {
      lines.push(`### ${index + 1}. ${clean(argument.title)}`, "", `**核心主张**  `, clean(argument.claim), "", `**需要证明什么**  `, clean(argument.burden), "");
      const support = argumentSupport(argument);
      lines.push(`**论证性质：** ${clean(support.short)}  `, clean(support.detail), "");
      if (argument.support_type !== "reasoning" && !(argument.evidence_ids || []).length) {
        lines.push("**⚠ 尚待核验的事实前提**", "", ...((argument.evidence_need || []).length ? argument.evidence_need : ["该论点含有事实性前提，但尚未明确完成核验。"] ).map(item => `- ${clean(item)}`), "");
      }
      if (argument.criterion) lines.push(`**判断标准**  `, clean(argument.criterion), "");
      if (argument.original_contribution) lines.push(`**本论点自己的推进**  `, clean(argument.original_contribution), "");
      lines.push("**论证链条**", "");
      (argument.warrant || []).forEach((step, stepIndex) => lines.push(`${stepIndex + 1}. ${clean(step)}`));
      lines.push("");
      if ((argument.evidence_ids || []).length) {
        lines.push("**证据支持**", "");
        for (const evidenceId of argument.evidence_ids) {
          const evidence = (d.evidence[party] || []).find(item => item.evidence_id === evidenceId);
          if (!evidence) continue;
          lines.push(`- ${clean(evidence.finding)} ${cite([evidence.source_id])}`);
          if (evidence.limitations) lines.push(`  - 适用限制：${clean(evidence.limitations)}`);
        }
        lines.push("");
      }
      if ((argument.material_source_ids || []).length) {
        lines.push("**帮助形成或检验本论点的材料（不作为事实背书）**", "");
        for (const sourceId of argument.material_source_ids) {
          const source = sourceById[sourceId];
          if (source) lines.push(`- ${clean(source.title)} ${cite([sourceId])}`);
        }
        lines.push("");
      }
      lines.push("**比较意义**  ", clean(argument.impact), "", "**适用边界**  ", clean(argument.scope), "");
      if ((argument.vulnerabilities || []).length) {
        lines.push("**需要主动防守的薄弱处**", "", ...(argument.vulnerabilities || []).map(item => `- ${clean(item)}`), "");
      }
      if ((argument.defense || []).length) {
        lines.push("**目前可采用的防守**", "", ...(argument.defense || []).map(item => `- ${clean(item)}`), "");
      }
    }
  }

  lines.push("## 四、双方核心交锋", "", "这里呈现的是已经与对方当前立论对齐的有效攻防，而不是模型之间的原始对话。", "");
  for (const party of ["A", "B"]) {
    const sideName = partyMeta(party).name;
    lines.push(`### ${sideName}对对方的主要回应`, "");
    const rebuttals = d.rebuttals[party] || [];
    if (!rebuttals.length) lines.push("当前尚无形成完整结构的回应。", "");
    rebuttals.forEach((rebuttal, index) => {
      const target = argumentById[rebuttal.target_argument_id];
      lines.push(`#### ${index + 1}. ${clean(rebuttal.title)}`, "");
      if (target) lines.push(`**回应对象：** ${clean(target.title)}`, "");
      lines.push(`**先准确理解对方：** ${clean(rebuttal.reconstruction)}`, "", `**主要反驳：** ${clean(rebuttal.attack)}`, "", `**为什么会影响胜负：** ${clean(rebuttal.why_it_matters)} ${citeEvidence(rebuttal.evidence_ids)}`, "");
      if (rebuttal.likely_response) lines.push(`**对方可能如何修复：** ${clean(rebuttal.likely_response)}`, "");
      if (rebuttal.current_effect) lines.push(`**当前攻防结论：** ${clean(rebuttal.current_effect)}`, "");
    });
  }

  lines.push("## 五、使用本报告时应保留的谨慎", "", "- 报告中的结论是立场条件下的可辩护论证，不是已经替代裁判判断的唯一答案。", "- 证据应结合其研究对象、方法和适用范围使用；不要把相关关系自动表述为因果关系。", "- 对方已经指出但尚未完全修复的薄弱处，应优先纳入进一步备赛，而不应在口头表达中隐藏。", "", "## 六、来源目录", "");
  if (!sources.length) lines.push("当前成果主要由逻辑推演形成，没有需要列入正文的外部来源。", "");
  sources.forEach((source, index) => {
    const title = clean(source.title) || `来源 ${index + 1}`;
    lines.push(`${index + 1}. **${title}**${source.url ? `  \n   ${source.url}` : ""}`);
  });
  lines.push("", "---", "", "本报告由论衡研究引擎根据双方当前有效立论、驳论与证据记录整理生成。内部推演历史可在工作台中另行查看。", "");
  return lines.join("\n");
}

function readerReportMarkdown(report) {
  if (report.markdown) return String(report.markdown).trim() + "\n";
  const clean = value => String(value || "").replace(/\s+/g, " ").trim();
  const list = (lines, title, items, ordered = false) => {
    if (!(items || []).length) return;
    lines.push(`**${title}**`, "");
    items.forEach((item, index) => lines.push(`${ordered ? `${index + 1}.` : "-"} ${clean(item)}`));
    lines.push("");
  };
  const lines = ["# 双边辩题研究总报告", "", `> **辩题：** ${clean(report.title)}`, ""];
  lines.push("## 一、先读结论", "");
  (report.opening_summary || []).forEach(paragraph => lines.push(clean(paragraph), ""));
  const motion = report.motion || {};
  lines.push("## 二、这道题究竟在争什么", "", clean(motion.core_question), "");
  list(lines, "需要先说清的概念", motion.definitions);
  if (motion.decision_rule) lines.push("**判断胜负的标准**", "", clean(motion.decision_rule), "");
  list(lines, "正方必须完成的证明", motion.burdens?.affirmative);
  list(lines, "反方必须完成的证明", motion.burdens?.negative);

  const renderSide = (side, sideName, number) => {
    if (!side) return;
    lines.push(`## ${number}、${sideName}如何把立场立住`, "", `**立场：** ${clean(side.position)}`, "", clean(side.case_thesis), "");
    (side.arguments || []).forEach((argument, index) => {
      lines.push(`### ${index + 1}. ${clean(argument.title)}`, "", clean(argument.claim), "");
      list(lines, "完整证明链", argument.reasoning, true);
      list(lines, "可用材料", argument.support);
      if (argument.strategic_value) lines.push("**为什么影响胜负**", "", clean(argument.strategic_value), "");
      if (argument.boundary) lines.push("**这套论证的边界**", "", clean(argument.boundary), "");
      if (argument.challenge) lines.push("**对方最强的质疑**", "", clean(argument.challenge), "");
      if (argument.response) lines.push("**本方应如何回应**", "", clean(argument.response), "");
    });
    if ((side.rebuttals || []).length) lines.push(`### ${sideName}的优先反驳`, "");
    (side.rebuttals || []).forEach((item, index) => {
      lines.push(`#### ${index + 1}. 回应“${clean(item.target)}”`, "", `**先准确理解对方：** ${clean(item.opponent_case)}`, "", `**本方回答：** ${clean(item.answer)}`, "", `**这为什么重要：** ${clean(item.impact)}`, "");
    });
  };
  renderSide(report.sides?.affirmative, "正方", "三");
  renderSide(report.sides?.negative, "反方", "四");

  lines.push("## 五、真正决定比赛的交锋", "");
  (report.clashes || []).forEach((clash, index) => {
    lines.push(`### ${index + 1}. ${clean(clash.question)}`, "", `**正方的答案：** ${clean(clash.affirmative_answer)}`, "", `**反方的答案：** ${clean(clash.negative_answer)}`, "", `**裁判应检验：** ${clean(clash.deciding_test)}`, "");
  });
  lines.push("## 六、怎样把研究转成赛场表达", "");
  for (const [key, name] of [["affirmative", "正方"], ["negative", "反方"]]) {
    const prep = report.preparation?.[key] || {};
    lines.push(`### ${name}`, "");
    list(lines, "立论展开顺序", prep.opening_order, true);
    list(lines, "优先处理的攻防", prep.rebuttal_priorities);
    list(lines, "可用于盘问的问题", prep.cross_examination);
  }
  if ((report.limitations || []).length) {
    lines.push("## 七、使用前仍需注意", "");
    (report.limitations || []).forEach(item => lines.push(`- ${clean(item)}`));
    lines.push("");
  }
  lines.push("## 八、来源目录", "");
  if (!(report.sources || []).length) lines.push("这份报告的核心内容由逻辑推演形成，没有外部来源进入最终论证。", "");
  (report.sources || []).forEach(source => lines.push(`${source.number}. **${clean(source.title) || `来源 ${source.number}`}**${source.url ? `  \n   ${source.url}` : ""}`));
  lines.push("", "---", "", "本报告已在研究完成后经过独立终稿编辑。运行轨迹、内部标签和历史版本不进入正文。", "");
  return lines.join("\n");
}

function reportHtml() {
  const markdown = reportMarkdown();
  const inline = raw => {
    let value = esc(raw);
    value = value.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
    value = value.replace(/(https?:\/\/[^\s<]+)/g, '<a href="$1" target="_blank" rel="noopener noreferrer">$1</a>');
    return value;
  };
  const body = [];
  const toc = [];
  let listType = null;
  const closeList = () => { if (listType) body.push(`</${listType}>`); listType = null; };
  for (const rawLine of markdown.split("\n")) {
    const line = rawLine.trim();
    if (!line) { closeList(); continue; }
    const heading = line.match(/^(#{1,4})\s+(.+)$/);
    if (heading) {
      closeList();
      const level = heading[1].length;
      const title = heading[2].replace(/\*\*/g, "");
      const id = `section-${toc.length + 1}`;
      body.push(`<h${level} id="${id}">${inline(heading[2])}</h${level}>`);
      if (level === 2) toc.push({ id, title });
      continue;
    }
    if (line === "---") { closeList(); body.push("<hr>"); continue; }
    if (line.startsWith("> ")) { closeList(); body.push(`<blockquote>${inline(line.slice(2))}</blockquote>`); continue; }
    const unordered = line.match(/^-\s+(.+)$/);
    const ordered = line.match(/^\d+\.\s+(.+)$/);
    if (unordered || ordered) {
      const wanted = ordered ? "ol" : "ul";
      if (listType !== wanted) { closeList(); listType = wanted; body.push(`<${wanted}>`); }
      body.push(`<li>${inline((unordered || ordered)[1])}</li>`);
      continue;
    }
    closeList();
    body.push(`<p>${inline(line)}</p>`);
  }
  closeList();
  const title = esc(String(state.data?.session?.question || "双边辩题研究总报告"));
  const tocHtml = toc.map(item => `<a href="#${item.id}">${esc(item.title)}</a>`).join("");
  return `<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>${title}｜研究总报告</title>
<style>
:root{color-scheme:light;--ink:#20252c;--muted:#68717d;--line:#dfe3e8;--paper:#fff;--accent:#315c55;--soft:#f3f6f5}*{box-sizing:border-box}html{scroll-behavior:smooth}body{margin:0;background:#edf0ef;color:var(--ink);font:16px/1.78 "Microsoft YaHei","PingFang SC",system-ui,sans-serif}.toolbar{position:sticky;top:0;z-index:5;display:flex;align-items:center;justify-content:space-between;padding:12px 24px;background:#192824;color:#fff;box-shadow:0 2px 12px #0002}.toolbar strong{font-size:15px}.toolbar button{border:0;border-radius:8px;padding:9px 16px;background:#fff;color:#203832;font-weight:700;cursor:pointer}.layout{display:grid;grid-template-columns:220px minmax(0,820px);gap:30px;max-width:1110px;margin:32px auto;padding:0 24px}.toc{position:sticky;top:82px;align-self:start;padding:18px;border:1px solid var(--line);border-radius:12px;background:#fff}.toc b{display:block;margin-bottom:10px;font-size:13px;color:var(--muted)}.toc a{display:block;padding:7px 0;color:#40504c;text-decoration:none;border-bottom:1px solid #eef0f1;font-size:14px}.toc a:hover{color:var(--accent)}main{min-width:0;padding:54px 64px;background:var(--paper);border:1px solid var(--line);border-radius:14px;box-shadow:0 12px 36px #26332e12}h1{margin:0 0 28px;font-family:Georgia,"Songti SC",serif;font-size:38px;line-height:1.3}h2{margin:52px 0 20px;padding-bottom:10px;border-bottom:2px solid var(--ink);font-size:25px}h3{margin:34px 0 15px;color:var(--accent);font-size:20px}h4{margin:26px 0 10px;font-size:17px}p{margin:10px 0}strong{font-weight:700}blockquote{margin:20px 0;padding:18px 22px;border-left:4px solid var(--accent);background:var(--soft);font-size:18px}ul,ol{padding-left:25px}li{margin:7px 0}a{color:#276b91;overflow-wrap:anywhere}hr{margin:44px 0;border:0;border-top:1px solid var(--line)}@media(max-width:820px){.layout{display:block;margin:0;padding:0}.toc{display:none}main{padding:32px 22px;border:0;border-radius:0}.toolbar{padding:10px 14px}h1{font-size:29px}}@media print{body{background:#fff;font-size:11pt}.toolbar,.toc{display:none}.layout{display:block;max-width:none;margin:0;padding:0}main{padding:0;border:0;box-shadow:none}h1{font-size:24pt}h2{break-after:avoid;page-break-after:avoid}h3,h4{break-after:avoid}a{color:inherit;text-decoration:none}}
</style></head><body><header class="toolbar"><strong>论衡 · 可阅读研究总报告</strong><button onclick="window.print()">打印 / 另存为 PDF</button></header><div class="layout"><nav class="toc"><b>报告目录</b>${tocHtml}</nav><main>${body.join("\n")}</main></div></body></html>`;
}

function downloadHtmlReport() {
  const url = URL.createObjectURL(new Blob([reportHtml()], { type: "text/html;charset=utf-8" }));
  const safeName = String(state.data?.session?.question || "双边辩题研究").replace(/[\\/:*?"<>|]/g, "").slice(0, 36);
  const link = document.createElement("a"); link.href = url; link.download = `${safeName}-研究总报告.html`; link.click(); URL.revokeObjectURL(url); toast("已导出可直接打开的研究总报告");
}

async function downloadPdfReport(button = $("#exportButton")) {
  if (!state.data) return;
  const original = button.textContent;
  button.disabled = true; button.textContent = "正在生成 PDF…";
  try {
    const response = await fetch("/api/report/pdf", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(state.data)
    });
    if (!response.ok) {
      const result = await response.json().catch(() => ({}));
      throw new Error(result.error || `PDF 服务返回 ${response.status}`);
    }
    const url = URL.createObjectURL(await response.blob());
    const safeName = String(state.data.session?.question || "双边辩题研究").replace(/[\\/:*?"<>|]/g, "").slice(0, 36);
    const link = document.createElement("a"); link.href = url; link.download = `${safeName}-研究总报告.pdf`; link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000); toast("PDF 报告已生成");
  } catch (error) { toast(`PDF 导出失败：${error.message}`); }
  finally { button.disabled = false; button.textContent = original; }
}

function renderReport() {
  $("#reportContent").innerHTML = `${heading("DELIVERABLE REPORT", "成果报告", "这里呈现的是已经清洗、重组并面向最终用户的报告，不包含模型对话和内部运行信息。", `<span class="config-state ready">可交付</span>`)}
    <div class="report-actions"><button class="primary-button" id="reportPdfButton">下载 PDF</button><button class="ghost-button" id="reportHtmlButton">下载独立 HTML</button></div>
    <div class="report-frame-wrap"><iframe id="reportFrame" title="研究总报告预览"></iframe></div>`;
  $("#reportFrame").srcdoc = reportHtml();
  $("#reportPdfButton").addEventListener("click", event => downloadPdfReport(event.currentTarget));
  $("#reportHtmlButton").addEventListener("click", downloadHtmlReport);
}

function modelSettingsPayload() {
  return {
    provider: $("#providerInput").value,
    protocol: $("#protocolInput").value,
    base_url: $("#baseUrlInput").value.trim(),
    api_key: $("#apiKeyInput").value.trim(),
    model_a: currentModel("A"),
    model_b: currentModel("B"),
    timeout_seconds: Number($("#timeoutInput").value)
  };
}

function showConnectionResult(kind, message) {
  const result = $("#connectionResult");
  result.className = `test-result ${kind}`;
  result.querySelector("span").textContent = message;
}

function applyModelConfig(config) {
  state.modelConfig = config;
  if (config.provider) $("#providerInput").value = config.provider === "openai-compatible" ? "generic-chat" : config.provider;
  $("#protocolInput").value = config.protocol || "auto";
  $("#baseUrlInput").value = config.base_url || "https://api.openai.com/v1";
  $("#modelAInput").value = config.model_a || "";
  $("#modelBInput").value = config.model_b || "";
  $("#timeoutInput").value = config.timeout_seconds || 120;
  $("#apiKeyInput").value = "";
  $("#apiKeyHint").textContent = config.has_api_key ? `已保存 ${config.api_key_hint}` : "尚未保存";
  $("#configState").textContent = config.ready ? "● 已就绪" : "待配置";
  $("#configState").classList.toggle("ready", config.ready);
  $("#settingsDot").classList.toggle("ready", config.ready);
  $(".engine-state small").textContent = config.ready ? "模型 API 已配置" : "等待配置模型 API";
}

function selectedProvider() {
  return (state.providers || []).find(item => item.id === $("#providerInput").value);
}

function currentModel(side) {
  const select = $(`#model${side}Select`);
  const input = $(`#model${side}Input`);
  return select && !select.classList.contains("hidden") ? select.value : input.value.trim();
}

function modelLabel(provider, model) {
  const note = provider?.model_notes?.[model];
  return note ? `${model} — ${note}` : model;
}

function updateModelCostHint() {
  const provider = selectedProvider();
  const model = $("#modelCatalogInput").value;
  const note = provider?.model_notes?.[model] || "该模型由供应商目录提供；实际可用性和额度以供应商为准。";
  $("#modelCostHint").textContent = note;
  $("#modelCostHint").classList.toggle("warning", /高消耗|训练/.test(note));
}

function renderModelChoices(provider, suppliedModels = null, preferredA = "", preferredB = "") {
  const models = [...new Set((suppliedModels || state.providerModels[provider.id] || provider.models || []).filter(Boolean))];
  const useSelects = models.length > 0 && !provider.id.startsWith("generic-") && !["azure-openai", "cloudflare"].includes(provider.id);
  const fallbackA = preferredA || (state.modelConfig?.provider === provider.id ? state.modelConfig.model_a : "") || provider.default_model || models[0] || "";
  const fallbackB = preferredB || (state.modelConfig?.provider === provider.id ? state.modelConfig.model_b : "") || fallbackA;
  for (const side of ["A", "B"]) {
    const select = $(`#model${side}Select`);
    const input = $(`#model${side}Input`);
    const preferred = side === "A" ? fallbackA : fallbackB;
    select.innerHTML = models.map(model => `<option value="${esc(model)}">${esc(modelLabel(provider, model))}</option>`).join("");
    if (models.includes(preferred)) select.value = preferred;
    select.classList.toggle("hidden", !useSelects); select.required = useSelects;
    input.classList.toggle("hidden", useSelects); input.required = !useSelects;
    if (!useSelects) input.value = preferred;
  }
  $("#modelCatalogInput").innerHTML = models.length
    ? models.map(model => `<option value="${esc(model)}">${esc(modelLabel(provider, model))}</option>`).join("")
    : `<option value="">该供应商需要手动填写模型或部署 ID</option>`;
  $("#modelCatalogInput").disabled = !models.length;
  $("#useCatalogModelButton").disabled = !models.length;
  $("#modelCatalogCount").textContent = models.length ? `共 ${models.length} 个` : "手动输入";
  if (models.includes(fallbackA)) $("#modelCatalogInput").value = fallbackA;
  updateModelCostHint();
}

function renderProvider(provider, overwrite = true) {
  if (!provider) return;
  $("#providerNote").textContent = provider.notes || `${provider.name} · ${provider.auth_mode === "none" ? "无需密钥" : "使用 API key"}`;
  const hasKeyForProvider = state.modelConfig?.has_api_key && state.modelConfig?.provider === provider.id;
  $("#apiKeyInput").required = provider.auth_mode !== "none" && !hasKeyForProvider;
  $("#apiKeyInput").placeholder = provider.auth_mode === "none" ? "本地服务无需密钥" : "粘贴供应商提供的 API key";
  if (overwrite) {
    $("#baseUrlInput").value = provider.base_url || "";
    $("#protocolInput").value = "auto";
    $("#modelAInput").value = provider.default_model || "";
    $("#modelBInput").value = provider.default_model || "";
  }
  renderModelChoices(provider, null, overwrite ? provider.default_model : "", overwrite ? provider.default_model : "");
}

async function loadProviders() {
  const response = await fetch("/api/providers");
  if (!response.ok) throw new Error("无法读取供应商目录");
  const data = await response.json();
  state.providers = data.providers;
  $("#providerInput").innerHTML = data.providers.map(item => `<option value="${esc(item.id)}">${esc(item.name)}</option>`).join("");
  const desired = state.modelConfig?.provider === "openai-compatible" ? "generic-chat" : (state.modelConfig?.provider || "openai");
  $("#providerInput").value = desired;
  renderProvider(selectedProvider(), false);
}

async function loadModelSettings() {
  const response = await fetch("/api/settings/model");
  if (!response.ok) throw new Error("无法读取模型设置");
  applyModelConfig(await response.json());
  await loadProviders();
}

async function saveModelSettings(event) {
  event.preventDefault();
  const button = $("#saveSettingsButton");
  button.disabled = true; button.textContent = "正在保存…";
  showConnectionResult("working", "正在将配置保存到本地服务端…");
  try {
    const payload = modelSettingsPayload();
    const response = await fetch("/api/settings/model", {
      method: "PUT", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || "保存失败");
    applyModelConfig(result);
    try {
      const catalog = await refreshModelCatalog({ silent: true, payload });
      showConnectionResult(catalog.missing_models?.length ? "warning" : "success", `设置已保存；${catalog.message} 模型目录已自动更新。`);
    } catch (catalogError) {
      showConnectionResult("warning", `设置已保存，但暂时无法读取完整模型目录：${catalogError.message} 可稍后点击“刷新模型目录”。`);
    }
    toast("模型 API 设置已保存");
  } catch (error) { showConnectionResult("error", error.message); }
  finally { button.disabled = false; button.textContent = "保存设置"; }
}

async function refreshModelCatalog({ silent = false, payload = null } = {}) {
  const settings = payload || modelSettingsPayload();
  if (!silent) showConnectionResult("working", "正在读取服务端完整模型列表，不会产生模型生成费用…");
  const response = await fetch("/api/settings/model/test", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify(settings)
  });
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || "连接失败");
  if (Array.isArray(result.models) && result.models.length) {
    const provider = selectedProvider();
    state.providerModels[provider.id] = result.models;
    renderModelChoices(provider, result.models, settings.model_a, settings.model_b);
  }
  return result;
}

async function testModelConnection() {
  const button = $("#testConnectionButton");
  button.disabled = true; button.textContent = "正在读取…";
  try {
    const result = await refreshModelCatalog();
    showConnectionResult(result.missing_models?.length ? "warning" : "success", `${result.message} 模型目录已更新。`);
  } catch (error) { showConnectionResult("error", error.message); }
  finally { button.disabled = false; button.textContent = "刷新模型目录"; }
}

$$('.side-nav button').forEach(button => button.addEventListener("click", () => { if (!state.data && !["overview", "settings"].includes(button.dataset.view)) { toast("请先完成或打开一项研究"); return; } switchView(button.dataset.view); }));
$("#runButton").addEventListener("click", runResearch);
$("#retryButton").addEventListener("click", resumeResearch);
$("#newTopicButton").addEventListener("click", resetNewResearch);
$("#clearFailedButton").addEventListener("click", clearFailedResearches);
$("#exportButton").addEventListener("click", event => downloadPdfReport(event.currentTarget));
$("#modelSettingsForm").addEventListener("submit", saveModelSettings);
$("#testConnectionButton").addEventListener("click", testModelConnection);
$("#providerInput").addEventListener("change", () => renderProvider(selectedProvider(), true));
$("#modelCatalogInput").addEventListener("change", updateModelCostHint);
$("#useCatalogModelButton").addEventListener("click", () => { const model = $("#modelCatalogInput").value; if (!model) return; const a = $("#modelASelect"), b = $("#modelBSelect"); if (!a.classList.contains("hidden")) { a.value = model; b.value = model; } else { $("#modelAInput").value = model; $("#modelBInput").value = model; } toast("已将所选模型设为双方模型"); });
$("#copyModelButton").addEventListener("click", () => { const model = currentModel("A"); if (!$("#modelBSelect").classList.contains("hidden")) $("#modelBSelect").value = model; else $("#modelBInput").value = model; toast("已将 A 方模型同步给 B 方"); });
$("#toggleSecret").addEventListener("click", () => { const input = $("#apiKeyInput"); input.type = input.type === "password" ? "text" : "password"; });
$(".dialog-close").addEventListener("click", () => $("#detailDialog").close());
$("#detailDialog").addEventListener("click", event => { if (event.target === $("#detailDialog")) $("#detailDialog").close(); });
Promise.all([loadModelSettings(), loadResearchList()]).catch(error => showConnectionResult("error", error.message));
