"""Runtime: the mechanical orchestrator.

The runtime drives the state machine and the agentic loop inside each pass, but
makes NO semantic judgment about what to research. It assembles context, runs the
model, executes tools / engine actions, and switches states.
"""

from __future__ import annotations

import asyncio
import copy
import json
import re
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse
from typing import Callable, Optional

from ..models import (
    EngineAction, Party, ResearchSession, RebuttalStatus, SessionStatus, Source,
)
from ..ports.llm import LLMPort, LLMTurn, ToolCall
from ..ports.search import SearchPort, SearchResult
from ..ports.transcription import TranscriptionPort
from ..prompt_loader import load_prompt, render_prompt
from ..ports.store import StorePort
from ..ports.tools import ToolPort
from ..skills import build_system_prompt
from .actions import apply_action
from .budget import PassBudget
from .mutation_log import MutationLog, now_iso
from .profiles import research_policy
from .semantic_diff import build_semantic_diff
from .state_machine import evaluate_candidate_stable
from .tool_schemas import (
    ENGINE_ACTION_NAMES,
    ENGINE_ACTION_TOOLS,
    read_source_tool_schema,
    search_tool_schema,
    stability_tool_schema,
    transcribe_source_tool_schema,
)


_PASS_CONCLUSION_FIELDS = {
    "summary",
    "attempted",
    "changed",
    "remaining_unknowns",
    "why_stop",
    "next_pass",
    "no_high_value_direction",
}

_ACTION_EVENT_LABELS = {
    "update_plan": "更新自主研究计划",
    "update_unit": "整合研究骨架",
    "update_map": "调整证明任务",
    "record_evidence": "登记已检查证据",
    "update_argument": "修建立论",
    "update_rebuttal": "形成驳论",
    "create_issue": "提出纠错问题",
    "respond_issue": "回应纠错问题",
    "close_issue": "关闭纠错问题",
    "conclude_pass": "申请结束当前 Pass",
}


class PassBudgetExhausted(RuntimeError):
    """A pass stopped mechanically before satisfying its quality contract."""


def _other(party: Party) -> Party:
    return Party.B if party is Party.A else Party.A


def _canonical_tool_name(requested: str, offered: set[str]) -> str:
    """Accept harmless provider casing/style changes, never an unoffered tool."""

    if requested in offered:
        return requested
    compact = re.sub(r"[^a-z0-9]", "", requested.lower())
    matches = [
        name for name in offered
        if re.sub(r"[^a-z0-9]", "", name.lower()) == compact
    ]
    return matches[0] if len(matches) == 1 else requested


def _resolve_existing_argument_id(
    payload: dict,
    arguments: list,
) -> str | None:
    """Resolve a model's human alias to one existing argument, conservatively.

    Continuous passes are revision-only.  Some providers still submit the
    memorable plan label (``B3-displacement``) or the argument title even when
    the tool schema enumerates opaque ids.  Treating that as a brand-new
    argument turns a harmless presentation mismatch into a retry loop.  We only
    translate when title matching or an explicit A/B ordinal identifies one
    existing argument unambiguously.
    """

    active = [item for item in arguments if item.status.value != "withdrawn"]
    by_id = {item.argument_id: item for item in active}
    requested = str(payload.get("argument_id") or "").strip()
    if requested in by_id:
        return requested

    def compact(value: object) -> str:
        return re.sub(r"[\W_]+", "", str(value or "").casefold())

    signals = [requested, payload.get("title"), payload.get("claim")]
    normalized_signals = [compact(value) for value in signals if compact(value)]
    exact_matches = {
        item.argument_id
        for item in active
        if compact(item.title) in normalized_signals
        or compact(item.argument_id) in normalized_signals
    }
    if len(exact_matches) == 1:
        return next(iter(exact_matches))

    contained_matches = {
        item.argument_id
        for item in active
        for signal in normalized_signals
        if min(len(compact(item.title)), len(signal)) >= 8
        and (
            compact(item.title) in signal
            or signal in compact(item.title)
        )
    }
    if len(contained_matches) == 1:
        return next(iter(contained_matches))

    ordinal = re.match(r"^[ab]\s*[-_]?\s*(\d{1,2})(?:\D|$)", requested.casefold())
    if ordinal:
        index = int(ordinal.group(1)) - 1
        if 0 <= index < len(active):
            return active[index].argument_id
    return None


class Runtime:
    def __init__(
        self,
        store: StorePort,
        llm: LLMPort,
        search: Optional[SearchPort] = None,
        tools: Optional[ToolPort] = None,
        prompt_builder: Optional[Callable[[str, Party, str, str], str]] = None,
        llm_b: Optional[LLMPort] = None,
        progress_callback: Optional[Callable[[dict], None]] = None,
        max_tool_result_chars: int = 12_000,
        transcriber: Optional[TranscriptionPort] = None,
    ):
        self.store = store
        self.llm = llm
        self.llm_b = llm_b or llm
        self.search = search
        self.tools = tools
        self.prompt_builder = prompt_builder or build_system_prompt
        self.progress_callback = progress_callback
        self.max_tool_result_chars = max(2_000, max_tool_result_chars)
        self.transcriber = transcriber
        self.log: Optional[MutationLog] = None
        self._pass_no = 0
        self._source_lock = asyncio.Lock()

    # ------------------------------------------------------------------ helpers

    def _next_pass_no(self) -> int:
        self._pass_no += 1
        return self._pass_no

    def _progress(self, phase: str, message: str, **extra) -> None:
        if self.progress_callback:
            self.progress_callback({"phase": phase, "message": message, **extra})

    def _activity(
        self,
        phase: str,
        message: str,
        *,
        agent: Party,
        pass_no: int,
        kind: str,
        title: str,
        status: str = "working",
        summary: str = "",
        details: Optional[list[dict[str, str]]] = None,
        budget: Optional[PassBudget] = None,
    ) -> None:
        """Publish an auditable action summary, never private chain-of-thought."""

        event = {
            "kind": kind,
            "title": title,
            "status": status,
            "summary": summary,
            "details": details or [],
            "agent": agent.value,
            "pass_no": pass_no,
            "phase": phase,
        }
        self._progress(
            phase,
            message,
            agent=agent.value,
            pass_no=pass_no,
            event=event,
            budget=budget.snapshot() if budget else None,
        )

    @staticmethod
    def _tool_result_failed(content: str) -> bool:
        lowered = content.lstrip().lower()
        return lowered.startswith(
            (
                "search failed",
                "search_gate:",
                "source read failed",
                "source read skipped",
                "source transcription failed",
                "source transcription skipped",
                "tool failed",
                "tool request rejected",
                "screening rejected",
                "error:",
                "(no results)",
            )
        )

    @staticmethod
    def _action_summary(name: str, args: dict) -> str:
        if name == "update_plan":
            return str(args.get("change_reason") or args.get("strategy") or "更新自主研究计划")
        if name == "update_argument":
            return str(args.get("title") or args.get("claim") or args.get("argument_id") or "更新论证")
        if name == "update_map":
            return str(args.get("title") or args.get("proof_obligation") or args.get("map_id") or "更新研究任务")
        if name == "record_evidence":
            return str(args.get("proposition") or args.get("source_id") or "登记证据")
        if name == "update_rebuttal":
            return str(args.get("title") or args.get("target_argument_id") or "更新驳论")
        if name in {"create_issue", "respond_issue", "close_issue"}:
            return str(args.get("title") or args.get("issue_id") or "更新纠错记录")
        if name == "update_unit":
            return str(args.get("what_changed") or args.get("unit_id") or "整合当前认识")
        if name == "conclude_pass":
            return str(args.get("summary") or "检查是否可以结束")
        return name

    def _pass_tools(self) -> list[dict]:
        tools: list[dict] = []
        if self.search is not None:
            tools.append(search_tool_schema())
            if callable(getattr(self.search, "read", None)):
                tools.append(read_source_tool_schema())
        if self.transcriber is not None:
            tools.append(transcribe_source_tool_schema())
        if self.tools is not None:
            tools.extend(self.tools.list_tools())
        return tools

    async def _case_frame_ready(self, session_id: str, agent: Party) -> bool:
        """Search is downstream of a finite initial case, never its substitute."""

        session = await self.store.load_session(session_id)
        if session is not None and not session.budget.argument_first_gate:
            return True
        arguments = await self.store.list_arguments(session_id, agent)
        framed = [
            item for item in arguments
            if item.status.value != "withdrawn"
            and all((item.title.strip(), item.claim.strip(), item.burden.strip(),
                     item.impact.strip(), item.scope.strip()))
            and len(item.warrant) >= 2
        ]
        return (
            len(framed) >= max(1, session.budget.min_core_arguments_per_agent)
        )

    async def _exact_motion_attempted(self, session_id: str, agent: Party) -> bool:
        """Recognize current and pre-v0.6 exact-motion search records."""

        session = await self.store.load_session(session_id)
        if (
            session is not None
            and agent.value in session.protocol_attempts.get("exact_motion", [])
        ):
            return True
        return any(
            source.discovered_by is agent
            and (
                source.metadata.get("discovery_kind") == "exact_motion"
                or any(
                    marker in str(source.metadata.get("screening_query", "")).casefold()
                    for marker in (
                        "辩论", "辩题", "辩论赛", "一辩", "辩稿",
                        "debate", "rebuttal", "transcript",
                    )
                )
            )
            for source in await self.store.list_sources(session_id)
        )

    async def _record_protocol_attempt(
        self, session: ResearchSession, key: str, agent: Party
    ) -> None:
        """Persist a required attempt even when an external search returns nothing."""

        completed = session.protocol_attempts.setdefault(key, [])
        if agent.value not in completed:
            completed.append(agent.value)
            session.updated_at = now_iso()
            await self.store.save_session(session)

    @staticmethod
    def _text_terms(value: str) -> set[str]:
        """Cheap multilingual terms for deterministic candidate screening."""

        lowered = value.casefold()
        terms = {
            token for token in re.findall(r"[a-z0-9][a-z0-9_-]{2,}", lowered)
            if token not in {"the", "and", "for", "with", "from", "this", "that", "study"}
        }
        for block in re.findall(r"[\u3400-\u9fff]{2,}", lowered):
            terms.add(block)
            terms.update(block[i:i + 2] for i in range(len(block) - 1))
        return terms

    @staticmethod
    def _canonical_url(value: str) -> str:
        parsed = urlparse(value.strip())
        if not parsed.scheme or not parsed.netloc:
            return value.strip()
        kept_query = [
            (key, item) for key, item in parse_qsl(parsed.query, keep_blank_values=True)
            if not key.casefold().startswith("utm_")
            and key.casefold() not in {"ref", "source", "campaign", "fbclid", "gclid"}
        ]
        return urlunparse((
            parsed.scheme.casefold(), parsed.netloc.casefold(),
            parsed.path.rstrip("/") or "/", "", urlencode(kept_query), "",
        ))

    def _screen_search_results(
        self,
        results: list[SearchResult],
        *,
        query: str,
        purpose: str,
        question: str,
        position: str,
        limit: int,
        existing_urls: set[str],
        search_mode: str = "argument_discovery",
        discovery_kind: str = "",
    ) -> tuple[list[SearchResult], int]:
        """Rank before persistence so obvious search noise never pollutes context."""

        intent_terms = self._text_terms(" ".join((query, purpose, question, position)))
        query_terms = self._text_terms(query)
        debate_only_terms = self._text_terms(
            "辩论 辩题 辩论赛 立论 辩稿 一辩 反方 正方 复盘 评委 "
            "debate speech rebuttal transcript round review"
        )
        topic_query_terms = query_terms - debate_only_terms
        ranked: list[tuple[float, SearchResult]] = []
        seen = set(existing_urls)
        seen_titles: set[str] = set()
        for result in results:
            canonical = self._canonical_url(result.url)
            title_key = re.sub(r"[^a-z0-9\u3400-\u9fff]+", "", result.title.casefold())
            if (
                not canonical
                or canonical in seen
                or (len(title_key) >= 12 and title_key in seen_titles)
            ):
                continue
            seen.add(canonical)
            if title_key:
                seen_titles.add(title_key)
            title_terms = self._text_terms(result.title)
            body_terms = self._text_terms(f"{result.title} {result.snippet} {urlparse(result.url).netloc}")
            title_overlap = len(query_terms & title_terms)
            topic_overlap = len(topic_query_terms & body_terms)
            intent_overlap = len(intent_terms & body_terms)
            score = (title_overlap * 0.22) + (intent_overlap * 0.06)
            combined = f"{result.title} {result.snippet}"
            hostname = urlparse(result.url).netloc.casefold()
            # Search-engine verticals and generated answer pages are navigation
            # surfaces, not actual material a human can revisit and evaluate.
            if hostname in {"image.so.com", "ai.so.com", "wenku.so.com"}:
                continue
            scholarly_host = any(marker in hostname for marker in (
                ".gov", ".edu", "doi.org", "crossref.org", "openalex.org",
                "pubmed", "plos.org", "frontiersin.org", "springer.com",
                "sciencedirect.com", "wiley.com", "cambridge.org", "oup.com",
            ))
            debate_host = any(marker in hostname for marker in (
                "bilibili.com", "youtube.com", "youtu.be", "zhihu.com",
                "reddit.com", "dcard.tw", "douban.com", "debatetimer",
            ))
            structured_access = result.metadata.get("access_tier") == "structured_api"
            stable_public_host = structured_access or any(
                hostname == marker or hostname.endswith("." + marker)
                for marker in (
                    "wikipedia.org", "wikimedia.org", "ncbi.nlm.nih.gov",
                    "crossref.org", "worldbank.org", "un.org", "who.int",
                    "oecd.org", "europa.eu", "gov.cn", "court.gov.cn",
                )
            ) or ".gov." in hostname or ".edu." in hostname or hostname.endswith((".gov", ".edu"))
            fragile_platform = any(marker in hostname for marker in (
                "bilibili.com", "youtube.com", "zhihu.com", "reddit.com",
                "docin.com", "doc88.com", "wenku.baidu.com", "book118.com",
            ))
            # Access stability is independent of epistemic authority. A forum
            # can still be excellent argument-discovery material, while a
            # structured API is preferred when two equally relevant candidates
            # can serve the same purpose.
            if structured_access:
                score += 0.16
            elif stable_public_host:
                score += 0.08
            if search_mode == "fact_verification" and scholarly_host:
                score += 0.18
            if search_mode == "argument_discovery" and debate_host:
                score += 0.22
            debate_markers = (
                "辩论", "辩题", "辩论赛", "立论", "辩稿", "一辩", "反方", "正方",
                "复盘", "评委", "debate", "speech", "rebuttal", "transcript",
            )
            if (
                search_mode == "argument_discovery"
                and any(marker in query.casefold() for marker in debate_markers)
                and not any(marker in combined.casefold() for marker in debate_markers)
            ):
                score -= 0.35
            if (
                search_mode == "argument_discovery"
                and discovery_kind == "exact_motion"
                and topic_query_terms
                and topic_overlap < 2
            ):
                score -= 0.7
            if re.search(r"[\u0600-\u06ff]", combined) and not re.search(r"[\u0600-\u06ff]", query):
                score -= 0.8
            if any(marker in combined.casefold() for marker in (
                "buy now", "coupon", "squishy toy", "car steering", "pinterest",
            )):
                score -= 0.45
            result.url = canonical
            result.metadata = dict(result.metadata)
            result.metadata.update({
                "screening_score": round(score, 3),
                "screening_query": query,
                "screening_purpose": purpose,
                "search_mode": search_mode,
                "discovery_kind": discovery_kind,
                "access_tier": result.metadata.get("access_tier") or (
                    "stable_public_web" if stable_public_host else
                    "fragile_platform" if fragile_platform else "ordinary_web"
                ),
                "expected_readability": (
                    "high" if structured_access else
                    "medium" if stable_public_host else
                    "low" if fragile_platform else "unknown"
                ),
                "content_access": (
                    "lead_only" if any(marker in hostname for marker in (
                        "bilibili.com", "youtube.com", "youtu.be", "douyin.com"
                    )) else "document"
                ),
            })
            ranked.append((score, result))
        ranked.sort(key=lambda pair: pair[0], reverse=True)
        accepted = [item for score, item in ranked if score >= 0.08][:limit]
        # Avoid a brittle empty set when snippets are sparse, but never admit a
        # totally unrelated tail merely to satisfy a numeric breadth target.
        if not accepted and ranked and ranked[0][0] > 0:
            accepted = [item for _, item in ranked[:min(2, limit)]]
        return accepted, max(0, len(results) - len(accepted))

    def _focused_excerpt(self, content: str, focus: str) -> str:
        """Return an objective-focused excerpt while preserving full text in store."""

        if len(content) <= self.max_tool_result_chars:
            return content
        paragraphs = [part.strip() for part in re.split(r"\n\s*\n+", content) if part.strip()]
        focus_terms = self._text_terms(focus)
        scored: list[tuple[int, int, str]] = []
        for index, paragraph in enumerate(paragraphs):
            overlap = len(focus_terms & self._text_terms(paragraph))
            scored.append((overlap, index, paragraph))
        selected: dict[int, str] = {}
        for _, index, paragraph in scored[:2]:
            selected[index] = paragraph
        for overlap, index, paragraph in sorted(scored, key=lambda row: (-row[0], row[1])):
            if overlap <= 0 and selected:
                continue
            selected[index] = paragraph
            if sum(len(item) for item in selected.values()) >= self.max_tool_result_chars - 500:
                break
        excerpt = "\n\n".join(selected[index] for index in sorted(selected))
        if not excerpt:
            excerpt = content[: self.max_tool_result_chars - 500]
        return (
            "[Engine: objective-focused excerpt; the complete document is preserved "
            "in the source pool.]\n\n" + excerpt[: self.max_tool_result_chars]
        )

    @staticmethod
    def _message_chars(messages: list[dict]) -> int:
        return len(json.dumps(messages, ensure_ascii=False, default=str))

    @staticmethod
    def _source_is_qualified(source: Source, agent: Party) -> bool:
        """A lead counts toward breadth only after screening or inspection."""

        if agent in source.investigated_by:
            return True
        try:
            return float(source.metadata.get("screening_score", 0) or 0) >= 0.08
        except (TypeError, ValueError):
            return False

    @staticmethod
    def _assistant_message(turn: LLMTurn) -> dict:
        message = {
            "role": "assistant",
            "content": turn.text or None,
            "tool_calls": [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.name,
                        "arguments": json.dumps(tc.arguments, ensure_ascii=False),
                    },
                }
                for tc in turn.tool_calls
            ],
        }
        message.update(turn.continuation)
        return message

    @staticmethod
    def _tool_result(tc: ToolCall, content: str) -> dict:
        return {"role": "tool", "tool_call_id": tc.id, "content": content}

    async def _next_source_id(self, session_id: str) -> str:
        sources = await self.store.list_sources(session_id)
        n = max((int(s.source_id.rsplit("_", 1)[-1]) for s in sources), default=0) + 1
        return f"src_{n:04d}"

    async def _register_source(
        self, session_id: str, agent: Party, result: SearchResult
    ) -> str:
        # Pass One runs both positions concurrently. Keep URL de-duplication and
        # sequential IDs atomic so one side can never overwrite the other's lead.
        async with self._source_lock:
            for existing in await self.store.list_sources(session_id):
                if result.url and existing.url == result.url:
                    return existing.source_id
            source_id = await self._next_source_id(session_id)
            source = Source(
                source_id=source_id,
                url=result.url,
                title=result.title,
                content=result.snippet,
                metadata=result.metadata,
                discovered_by=agent,
                source_type=str(result.metadata.get("source_type", "")),
                is_primary=result.metadata.get("is_primary"),
            )
            await self.store.save_source(source, session_id)
            return source_id

    async def _execute_pass_tool(
        self, session_id: str, agent: Party, name: str, args: dict
    ) -> str:
        if name == "search":
            if self.search is None:
                return "search not configured"
            query = args.get("query", "")
            search_mode = str(args.get("search_mode", "argument_discovery"))
            requested = int(args.get("n", 5))
            # Argument discovery needs a compact set of distinct ideas, not a
            # long search-result payload. Fact verification may need a wider
            # candidate pool to locate the named record.
            n = max(
                1,
                min(requested, 6 if search_mode == "argument_discovery" else 10),
            )
            session = await self.store.load_session(session_id)
            if session is not None:
                discovered = [
                    source for source in await self.store.list_sources(session_id)
                    if source.discovered_by is agent
                    and self._source_is_qualified(source, agent)
                ]
                discovery_ceiling = max(
                    session.budget.min_sources_per_agent + 12,
                    int(session.budget.min_sources_per_agent * 1.5),
                )
                if len(discovered) >= discovery_ceiling:
                    return (
                        f"SEARCH_GATE: breadth ceiling reached ({len(discovered)} sources). Stop broad "
                        "discovery: inspect the strongest sources, record evidence, and build "
                        "the current argument system. A later pass can reopen targeted search."
                    )
            try:
                # Ask the backend for a wider cheap candidate set, then let the
                # engine screen it before any item enters durable state.
                raw_limit = min(20, max(n * 2, 8))
                raw_results = await self.search.search(query, raw_limit)
                # General engines often rank generic explainers above the exact
                # debate even when the model chose the right strategy. One cheap
                # platform-focused companion query improves debate archaeology
                # without spending another model turn.
                archaeology_signal = (
                    f"{query} {args.get('strategy', '')}".casefold()
                )
                if (
                    search_mode == "argument_discovery"
                    and session is not None
                    and any(marker in archaeology_signal for marker in (
                        "辩论", "辩题", "辩稿", "立论", "复盘", "exact-motion",
                        "debate", "transcript",
                    ))
                ):
                    companion = (
                        f'site:bilibili.com "{session.position_for(agent)}" '
                        "辩论 复盘 立论"
                    )
                    extra_results = await self.search.search(companion, raw_limit)
                    known = {self._canonical_url(item.url) for item in raw_results}
                    raw_results.extend(
                        item for item in extra_results
                        if self._canonical_url(item.url) not in known
                    )
            except Exception as exc:
                return render_prompt(
                    "feedback/search_failure.md", error=str(exc)[:400]
                )
            if not raw_results:
                return load_prompt("feedback/search_empty.md")
            current_sources = await self.store.list_sources(session_id)
            existing_urls = {self._canonical_url(source.url) for source in current_sources}
            results, rejected = self._screen_search_results(
                raw_results,
                query=query,
                purpose=str(args.get("purpose", "")),
                question=session.question if session else "",
                position=session.position_for(agent) if session else "",
                limit=n,
                existing_urls=existing_urls,
                search_mode=str(args.get("search_mode", "argument_discovery")),
                discovery_kind=str(args.get("discovery_kind", "")),
            )
            if not results:
                return (
                    f"screening rejected all {len(raw_results)} candidates as duplicate or "
                    "insufficiently relevant. Repair a meaningful query dimension before retrying."
                )
            lines = []
            for r in results:
                sid = await self._register_source(session_id, agent, r)
                score = r.metadata.get("screening_score", "")
                lines.append(
                    f"[{sid}] {r.title}\n  {r.url}\n  screening_score={score}\n  "
                    f"access={r.metadata.get('access_tier', 'unknown')}/"
                    f"{r.metadata.get('expected_readability', 'unknown')}; "
                    f"content_access={r.metadata.get('content_access', 'document')}\n  "
                    f"{r.snippet[:500]}"
                )
            return (
                f"SCREENING fetched={len(raw_results)} accepted={len(results)} "
                f"rejected={rejected}\n\n" + "\n\n".join(lines) + "\n\n" + load_prompt(
                    "feedback/search_results.md"
                )
            )
        if name == "read_source":
            if self.search is None or not callable(getattr(self.search, "read", None)):
                return "source reading is not configured"
            source = await self.store.load_source(args.get("source_id", ""))
            if source is None:
                return "unknown source_id"
            if source.metadata.get("content_access") == "lead_only":
                return (
                    "source read skipped: this is a video landing page, not a transcript. "
                    "Its title and search snippet may be attached as argument-discovery "
                    "material, but it cannot count as an inspected document. "
                    + (
                        "Use transcribe_source once if this particular video can materially "
                        "improve an existing argument; otherwise move on."
                        if self.transcriber is not None else
                        "Search once for a transcript, review, subtitle export, or text "
                        "reconstruction; otherwise move on."
                    )
                )
            if agent in source.investigated_by and len(source.content.strip()) >= 300:
                focus = " ".join((
                    str(args.get("purpose", "")),
                    " ".join(str(item) for item in args.get("focus_terms", []) if item),
                ))
                return (
                    "CACHED_SOURCE_ALREADY_INSPECTED: no new network read was spent. "
                    "Use the preserved text below now; do not request this source again. "
                    "Record a factual finding, attach it as argument-discovery material, "
                    "or discard it.\n\n" + self._focused_excerpt(source.content, focus)
                )
            blocked_by = set(source.metadata.get("read_blocked_by", []))
            if agent.value in blocked_by:
                return (
                    "source read skipped: this URL already produced a permanent access "
                    "failure for this position. Search for an open-access copy, repository "
                    "version, DOI landing page, abstract index, or alternate primary source."
                )
            try:
                document = await self.search.read(source.url)
            except Exception as exc:
                error_text = str(exc)[:400]
                if any(marker in error_text.casefold() for marker in (
                    "403", "401", "404", "forbidden", "unauthorized", "not found",
                )):
                    blocked_by.add(agent.value)
                    source.metadata["read_blocked_by"] = sorted(blocked_by)
                    source.metadata["last_read_error"] = error_text
                    await self.store.save_source(source, session_id)
                return f"source read failed; find an accessible primary copy or alternate source: {str(exc)[:400]}"
            source.content = document.content
            source.metadata.update(document.metadata)
            useful_content = document.content.strip()
            if document.metadata.get("read_error") or len(useful_content) < 300:
                blocked_by.add(agent.value)
                source.metadata["read_blocked_by"] = sorted(blocked_by)
                source.metadata["last_read_error"] = str(document.content[:400])
                await self.store.save_source(source, session_id)
                return (
                    "source read failed; fewer than 300 inspectable characters were recovered. "
                    "Find an accessible primary copy or alternate source."
                )
            if agent not in source.investigated_by:
                source.investigated_by.append(agent)
            if agent.value in blocked_by:
                blocked_by.remove(agent.value)
                source.metadata["read_blocked_by"] = sorted(blocked_by)
            await self.store.save_source(source, session_id)
            focus = " ".join((
                str(args.get("purpose", "")),
                " ".join(str(item) for item in args.get("focus_terms", []) if item),
            ))
            return self._focused_excerpt(document.content, focus)
        if name == "transcribe_source":
            if self.transcriber is None:
                return "audio transcription is not configured"
            source = await self.store.load_source(str(args.get("source_id", "")))
            if source is None:
                return "unknown source_id"
            if not self.transcriber.supports(source.url):
                return "source transcription skipped: unsupported media URL"
            if (
                agent in source.investigated_by
                and source.metadata.get("transcript_method")
                and len(source.content.strip()) >= 100
            ):
                focus = " ".join((
                    str(args.get("purpose", "")),
                    " ".join(str(item) for item in args.get("focus_terms", []) if item),
                ))
                return (
                    "CACHED_SOURCE_ALREADY_INSPECTED: no new media or ASR work was spent.\n\n"
                    + self._focused_excerpt(source.content, focus)
                )
            try:
                document = await self.transcriber.transcribe(
                    source.url,
                    language=str(args.get("language", "")),
                    max_duration_seconds=min(
                        5400, max(60, int(args.get("max_duration_seconds", 5400)))
                    ),
                )
            except Exception as exc:
                return (
                    "source transcription failed; use its search lead or find a text "
                    f"reconstruction instead: {str(exc)[:500]}"
                )
            if len(document.content.strip()) < 100:
                return "source transcription failed; fewer than 100 usable characters were recovered"
            source.content = document.content
            source.metadata.update(document.metadata)
            source.metadata["content_access"] = "transcript"
            source.metadata["transcript_segments"] = len(document.segments)
            if agent not in source.investigated_by:
                source.investigated_by.append(agent)
            await self.store.save_source(source, session_id)
            focus = " ".join((
                str(args.get("purpose", "")),
                " ".join(str(item) for item in args.get("focus_terms", []) if item),
            ))
            header = (
                f"TRANSCRIPT method={document.metadata.get('transcript_method', 'unknown')} "
                f"language={document.metadata.get('transcript_language', 'unknown')} "
                f"speaker_labels={document.metadata.get('speaker_labels', False)} "
                f"unreviewed={document.metadata.get('transcript_unreviewed', True)} "
                f"segments={len(document.segments)}. Treat as argument-discovery material; "
                "do not infer speaker identity.\n\n"
            )
            return header + self._focused_excerpt(document.content, focus)
        if self.tools is None:
            return f"tool {name} not configured"
        try:
            result = await self.tools.call(name, args)
        except Exception as exc:
            return f"tool failed; revise the request or use another source: {str(exc)[:400]}"
        return result.content if result.ok else f"error: {result.error}"

    async def _expansion_completion_error(
        self, session: ResearchSession, agent: Party
    ) -> str | None:
        """Return the single authoritative Pass One construction verdict.

        Exit-window entry, conclusion, checkpoint recovery and tool gating all
        consume this same audit.  It deliberately excludes the plan/conclusion
        envelope, which records the model's stopping judgment after construction
        is mechanically complete.
        """

        limits = session.budget
        arguments = await self.store.list_arguments(session.session_id, agent)
        # Tiny scripted/demo profiles intentionally set the argument floor to
        # zero. Keep their legacy fixture contract without reintroducing unit/map
        # gates into either public production profile.
        if not limits.min_core_arguments_per_agent and not arguments:
            units = await self.store.list_units(session.session_id, agent)
            maps = await self.store.list_map_entries(session.session_id, agent)
            if not any(unit.content.strip() for unit in units) or not maps:
                return "Fixture Pass One has not committed its synthetic unit and map yet."
        discovered = [
            source for source in await self.store.list_sources(session.session_id)
            if source.discovered_by is agent
            and self._source_is_qualified(source, agent)
        ]
        if len(discovered) < limits.min_sources_per_agent:
            return (
                "Pass One breadth floor not met: "
                f"{len(discovered)}/{limits.min_sources_per_agent} sources discovered "
                "by this position. Continue only the highest-value open query routes."
            )

        evidence = await self.store.list_evidence(session.session_id, agent)
        examined_source_ids = {
            source.source_id
            for source in await self.store.list_sources(session.session_id)
            if agent in source.investigated_by
        }
        valid_evidence_ids: set[str] = set()
        for item in evidence:
            source = await self.store.load_source(item.source_id)
            if (
                item.status.value != "rejected"
                and source is not None
                and agent in source.investigated_by
                and all((item.proposition, item.finding, item.method,
                         item.limitations, item.provenance))
            ):
                valid_evidence_ids.add(item.evidence_id)
        if len(examined_source_ids) < limits.min_examined_sources_per_agent:
            return (
                "Pass One source-investigation floor not met: "
                f"{len(examined_source_ids)}/{limits.min_examined_sources_per_agent} "
                "distinct inspected sources."
            )

        if limits.argument_first_gate and not any(
            item.status.value != "withdrawn"
            and len(item.original_contribution.strip()) >= 20
            for item in arguments
        ):
            return (
                "Pass One has no inspectable original contribution yet. Revise at least "
                "one argument with a defensible new inferential link, framing, comparison, "
                "boundary, counterexample or defensive repair."
            )

        complete = []
        for item in arguments:
            if item.status.value == "withdrawn":
                continue
            missing = set(item.missing_proof_fields())
            verified = (
                not missing
                and (
                    item.support_type == "reasoning"
                    or bool(valid_evidence_ids.intersection(item.evidence_ids))
                )
            )
            honestly_unverified = (
                missing == {"evidence_ids"}
                and bool(item.evidence_need)
                and all(str(need).strip() for need in item.evidence_need)
            )
            if verified or honestly_unverified:
                complete.append(item)
        if len(complete) < limits.min_core_arguments_per_agent:
            details = "; ".join(
                f"{item.argument_id}: {', '.join(item.missing_proof_fields())}"
                for item in arguments
                if item.status.value != "withdrawn" and item.missing_proof_fields()
            ) or "mixed/empirical arguments lack evidence for their named factual needs"
            return (
                "Pass One case floor not met: "
                f"{len(complete)}/{limits.min_core_arguments_per_agent} complete "
                f"position arguments. Missing proof links: {details}"
            )
        if (
            session.budget.argument_first_gate
            and not await self._exact_motion_attempted(session.session_id, agent)
        ):
            return (
                "Pass One exact-motion archaeology has not been attempted. Run one "
                "bounded argument_discovery search with discovery_kind=exact_motion for "
                "prior rounds, speeches, reviews or public debate on this proposition. "
                "A failed or empty search still counts as an honest attempt."
            )
        return None

    async def _conclusion_error(
        self, mode: str, agent: Party, pass_no: int, args: dict,
        budget: PassBudget | None = None,
    ) -> str | None:
        """Enforce structural pass duties without making semantic judgments."""

        missing = sorted(_PASS_CONCLUSION_FIELDS - set(args))
        if missing:
            return "conclude_pass is incomplete; missing: " + ", ".join(missing)

        plan = await self.store.load_plan(self.log.session_id, agent)
        if plan is None or plan.phase != mode:
            return (
                "This phase has no current model-owned plan. Use update_plan to inspect the "
                "state and make an explicit stopping forecast before concluding."
            )
        if plan.status != "ready_to_conclude":
            return (
                "Your dynamic plan is still active. Re-audit its stopping conditions and use "
                "update_plan with status=ready_to_conclude, completed/abandoned routes and an "
                "honest remaining-work assessment before concluding."
            )

        if mode == "expansion":
            session = await self.store.load_session(self.log.session_id)
            if session is None:
                return "Research session is unavailable; cannot audit Pass One."
            error = await self._expansion_completion_error(session, agent)
            if error:
                return error
        if mode == "collision":
            session = await self.store.load_session(self.log.session_id)
            if session is not None:
                rebuttals = await self.store.list_rebuttals(session.session_id, agent)
                complete = [
                    item for item in rebuttals
                    if not item.missing_fields()
                    and item.status.value not in {"withdrawn", "answered"}
                ]
                if len(complete) < session.budget.min_rebuttals_per_agent:
                    return (
                        "Cross-review cannot conclude yet: build at least "
                        f"{session.budget.min_rebuttals_per_agent} precise rebuttals against "
                        "the opponent's actual argument revisions."
                    )
                opponent = _other(agent)
                current_arguments = [
                    item for item in await self.store.list_arguments(
                        session.session_id, opponent
                    ) if item.status.value != "withdrawn"
                ]
                covered = {item.target_argument_id for item in complete}
                uncovered = [
                    item for item in current_arguments
                    if item.argument_id not in covered
                ]
                if uncovered:
                    return (
                        "Cross-review has not addressed every opponent argument "
                        "family. Use update_rebuttal against these live targets: "
                        + ", ".join(
                            f"{item.argument_id} v{item.version}"
                            for item in uncovered[:8]
                        )
                    )
        if mode == "continuous" and args.get("no_high_value_direction"):
            session = await self.store.load_session(self.log.session_id)
            if session is not None and session.budget.min_core_arguments_per_agent:
                arguments = await self.store.list_arguments(session.session_id, agent)
                unfinished = [
                    item for item in arguments
                    if item.status.value != "withdrawn"
                    and (
                        bool(item.missing_proof_fields())
                        and not (
                            set(item.missing_proof_fields()) == {"evidence_ids"}
                            and bool(item.evidence_need)
                            and all(str(need).strip() for need in item.evidence_need)
                        )
                    )
                ]
                if unfinished:
                    return (
                        "You cannot declare the case stable while current arguments are "
                        "unfinished: " + ", ".join(item.argument_id for item in unfinished)
                    )
        return None

    async def _opponent_recent_diff(self, session_id: str, agent: Party) -> str:
        opponent = _other(agent)
        mutations = await self.log.list()
        opp_passes = {m.pass_no for m in mutations if m.agent is opponent}
        if not opp_passes:
            return "(no prior pass from opponent)"
        last = max(opp_passes)
        opp_mutations = [m for m in mutations if m.pass_no == last and m.agent is opponent]
        return build_semantic_diff(opp_mutations, opponent, last)

    async def _build_context(
        self, session: ResearchSession, agent: Party, mode: str
    ) -> str:
        position = session.position_for(agent)
        parts: list[str] = [
            f"Debate proposition: {session.question}",
            f"Assigned standpoint: {position}",
        ]
        plan = await self.store.load_plan(session.session_id, agent)
        if plan is None or plan.phase != mode:
            parts.append(
                "DYNAMIC PLAN REQUIRED: before any research or case action, inspect the "
                "current durable state and use update_plan to choose your own route for this "
                f"{mode} phase. Do not copy a generic workflow. Decide what matters for this "
                "proposition, what could change your case, and what observable conditions "
                "will make you stop."
            )
        else:
            parts.append(
                f"== Your model-owned dynamic plan · {plan.plan_id} v{plan.version} "
                f"[{plan.status}] ==\n"
                f"Interpretation: {plan.question_interpretation[:900]}\n"
                f"Winning condition: {plan.winning_condition[:700]}\n"
                f"Current strategy: {plan.strategy[:1000]}\n"
                f"Route hypotheses: {str(plan.route_hypotheses)[:1000]}\n"
                f"Next actions: {str(plan.next_actions)[:1800]}\n"
                f"Stopping conditions: {str(plan.stopping_conditions)[:1000]}\n"
                f"Completed: {str(plan.completed)[:800]}\n"
                f"Abandoned: {str(plan.abandoned)[:600]}\n"
                f"Remaining work: {plan.remaining_work[:800]}\n"
                f"Progress assessment: {plan.progress_assessment[:700]}\n"
                f"Estimated remaining actions: {plan.estimated_remaining_actions}\n"
                "The plan is yours: revise it whenever the best route, forecast, or stopping "
                "conditions change. Do not execute stale actions merely because they were planned."
            )
        convergence_ready = False
        if mode == "expansion":
            frame_ready = await self._case_frame_ready(session.session_id, agent)
            if frame_ready:
                parts.append(
                    "Your bounded initial case frame is complete and research tools are now "
                    "available. Search for argument value first; verify only named factual needs."
                )
                convergence_ready = await self._expansion_state_complete(session, agent)
                if convergence_ready:
                    parts.append(
                        "CONVERGENCE SIGNAL: the durable case currently satisfies the structural "
                        "Pass One gate and exact-motion archaeology has been attempted. If the "
                        "useful clash or idea from that material is already incorporated, call "
                        "conclude_pass now. Do not keep searching merely because some shortlisted "
                        "pages are inaccessible or more material might exist."
                    )
            else:
                parts.append(
                    "INITIAL CASE GATE: external research is intentionally unavailable. Build "
                    f"at least {max(1, session.budget.min_core_arguments_per_agent)} distinct, "
                    "explicit arguments from your own reasoning. Do not ask for sources yet "
                    "and do not create empty placeholders. Units and maps are optional planning "
                    "memory, not substitutes for arguments."
                )
        units = await self.store.list_units(session.session_id, agent)
        if units:
            parts.append("== Your recent integrated research units ==")
            visible_units = units[-2:] if mode == "expansion" else units[-1:]
            unit_excerpt_limit = 3000 if mode == "expansion" else 1800
            for u in visible_units:
                parts.append(
                    f"--- {u.unit_id} [{u.status.value}] sources={u.source_ids} ---\n"
                    f"{u.content[:unit_excerpt_limit]}"
                )
        entries = await self.store.list_map_entries(session.session_id, agent)
        if entries:
            active_entries = [entry for entry in entries if entry.status.value == "active"]
            visible_entries = (active_entries or entries)[-10:]
            parts.append(
                f"== Active proof obligations ({len(active_entries)} active; showing "
                f"{len(visible_entries)}) =="
            )
            for e in visible_entries:
                parts.append(
                    f"- {e.map_id} [{e.status.value}] {e.title} "
                    f"(imp={e.importance}, cov={e.coverage}, unc={e.uncertainty})\n"
                    f"  obligation={e.proof_obligation[:500]}\n  note={e.note[:400]}"
                )

        arguments = await self.store.list_arguments(session.session_id, agent)
        if arguments:
            parts.append("== Your current position case (primary product) ==")
            for item in arguments[-8:]:
                parts.append(
                    f"--- {item.argument_id} v{item.version} [{item.status.value}] {item.title} ---\n"
                    f"Claim: {item.claim[:650]}\nBurden: {item.burden[:350]}\n"
                    f"Criterion: {item.criterion[:350]}\nWarrant: {item.warrant[:900]}\n"
                    f"Support type: {item.support_type}; evidence need: {item.evidence_need}\n"
                    f"Factual evidence: {item.evidence_ids}; argument-discovery material: "
                    f"{item.material_source_ids}\nImpact: {item.impact[:500]}\n"
                    f"Original contribution: {item.original_contribution[:600]}\n"
                    f"Scope: {item.scope[:350]}\nVulnerabilities: {item.vulnerabilities[:500]}\n"
                    f"Defense: {item.defense[:500]}"
                )

        evidence = await self.store.list_evidence(session.session_id, agent)
        if evidence:
            parts.append("== Your inspected evidence records ==")
            for item in evidence[-30:]:
                parts.append(
                    f"- {item.evidence_id} [{item.status.value}/{item.relation}] "
                    f"source={item.source_id} argument={item.argument_id}\n"
                    f"  Proposition: {item.proposition[:400]}\n  Finding: {item.finding[:500]}\n"
                    f"  Method: {item.method[:300]}\n  Limitations: {item.limitations[:300]}"
                )

        sources = await self.store.list_sources(session.session_id)
        if sources and not (mode == "expansion" and convergence_ready):
            own_evidence_source_ids = {item.source_id for item in evidence}
            if mode == "expansion":
                visible_sources = [
                    source for source in sources
                    if source.discovered_by is agent or agent in source.investigated_by
                    if (
                        agent.value not in set(source.metadata.get("read_blocked_by", []))
                        or source.source_id in own_evidence_source_ids
                        or agent in source.investigated_by
                    )
                ]
                visible_sources = sorted(
                    visible_sources,
                    key=lambda source: (
                        source.source_id not in own_evidence_source_ids,
                        agent not in source.investigated_by,
                        -float(source.metadata.get("screening_score", 0) or 0),
                        source.source_id,
                    ),
                )[:24]
                heading = (
                    "== Screened source shortlist (prioritize inspected/evidence-linked; "
                    f"showing {len(visible_sources)}) =="
                )
            else:
                opponent_evidence = await self.store.list_evidence(
                    session.session_id, _other(agent)
                )
                referenced = own_evidence_source_ids | {
                    item.source_id for item in opponent_evidence
                }
                opponent_case = await self.store.list_arguments(
                    session.session_id, _other(agent)
                )
                referenced.update(
                    source_id
                    for argument in arguments + opponent_case
                    for source_id in argument.material_source_ids
                )
                visible_sources = sorted(
                    [source for source in sources if source.source_id in referenced],
                    key=lambda source: (
                        source.source_id not in referenced,
                        source.source_id,
                    ),
                )[:30]
                heading = "== Evidence-linked shared source index =="
            if visible_sources:
                parts.append(heading)
            for source in visible_sources[:30]:
                inspected = agent in source.investigated_by
                excerpt = source.content[:260] if (
                    inspected or source.source_id in own_evidence_source_ids
                ) else source.content[:120]
                parts.append(
                    f"- [{source.source_id}] {source.title}\n"
                    f"  {source.url}\n  investigated_by={ [p.value for p in source.investigated_by] } "
                    f"screen={source.metadata.get('screening_score', 'legacy')} "
                    f"access={source.metadata.get('access_tier', 'unknown')}/"
                    f"{source.metadata.get('expected_readability', 'unknown')}\n  {excerpt}"
                )
        elif sources and mode == "expansion" and convergence_ready:
            parts.append(
                "== Research shortlist compressed for convergence ==\n"
                f"{len(sources)} sources remain preserved in durable state. The useful "
                "exact-motion clash has already been incorporated; reopen details only in "
                "a later pass if a new, named proof gap appears."
            )

        if mode == "expansion":
            return "\n\n".join(parts)

        diff = await self._opponent_recent_diff(session.session_id, agent)
        header = (
            "== Opponent's expansion results (fill your map, do NOT attack) =="
            if mode == "collision"
            else "== Opponent's latest changes (semantic diff) =="
        )
        parts.append(header)
        parts.append(diff)

        if mode == "collision":
            opponent = _other(agent)
            opponent_units = await self.store.list_units(session.session_id, opponent)
            if opponent_units:
                parts.append("== Opponent's full Pass One research units ==")
                for u in opponent_units:
                    parts.append(
                        f"--- {u.unit_id} [{u.status.value}] sources={u.source_ids} ---\n"
                        f"{u.content[:2500]}"
                    )

        opponent = _other(agent)
        opponent_arguments = await self.store.list_arguments(session.session_id, opponent)
        if opponent_arguments:
            parts.append("== Opponent's current argument case (attack this exact version) ==")
            for item in opponent_arguments:
                parts.append(
                    f"--- {item.argument_id} v{item.version} [{item.status.value}] {item.title} ---\n"
                    f"Claim: {item.claim[:700]}\nBurden: {item.burden[:400]}\nCriterion: {item.criterion[:400]}\n"
                    f"Warrant: {str(item.warrant)[:1200]}\nFactual evidence: {item.evidence_ids}\n"
                    f"Argument-discovery material: {item.material_source_ids}\n"
                    f"Impact: {item.impact[:550]}\nScope: {item.scope[:400]}"
                )

        opponent_evidence = await self.store.list_evidence(session.session_id, opponent)
        if opponent_evidence:
            parts.append("== Opponent's inspected evidence records ==")
            for item in opponent_evidence:
                source = await self.store.load_source(item.source_id)
                parts.append(
                    f"- {item.evidence_id} [{item.status.value}/{item.relation}] "
                    f"source={item.source_id} {source.title if source else ''}\n"
                    f"  Proposition: {item.proposition}\n  Finding: {item.finding}\n"
                    f"  Method: {item.method}\n  Limitations: {item.limitations}\n"
                    f"  Provenance: {item.provenance}"
                )

        rebuttals = await self.store.list_rebuttals(session.session_id, agent)
        if rebuttals:
            parts.append("== Your rebuttals against the opponent ==")
            for item in rebuttals:
                parts.append(
                    f"- {item.rebuttal_id} -> {item.target_argument_id} v{item.target_version} "
                    f"[{item.status.value}] {item.title}\n"
                    f"  Fair reconstruction: {item.reconstruction[:400]}\n"
                    f"  Attack: {item.attack[:650]}\n  Why it matters: {item.why_it_matters[:400]}\n"
                    f"  Current effect: {item.current_effect[:300]}"
                )

        if mode == "continuous":
            complete_targets = {
                (item.target_argument_id, item.target_version)
                for item in rebuttals
                if not item.missing_fields()
                and item.status.value not in {"withdrawn", "answered"}
            }
            revision_gaps = [
                item for item in opponent_arguments
                if item.status.value != "withdrawn"
                and (item.argument_id, item.version) not in complete_targets
            ]
            if revision_gaps:
                parts.append(
                    "CURRENT OPPONENT VERSION GAPS: your earlier rebuttals do not "
                    "automatically answer these revised texts. Decide whether to "
                    "update_rebuttal, narrow an attack, or honestly report a remaining "
                    "unknown before declaring stable: " + ", ".join(
                        f"{item.argument_id} v{item.version}"
                        for item in revision_gaps
                    )
                )

        if mode == "collision":
            live_targets = {
                item.argument_id
                for item in opponent_arguments
                if item.status.value != "withdrawn"
            }
            covered_targets = {
                item.target_argument_id
                for item in rebuttals
                if not item.missing_fields()
                and item.status.value not in {"withdrawn", "answered"}
            }
            if (
                live_targets
                and live_targets <= covered_targets
                and len([item for item in rebuttals if not item.missing_fields()])
                >= session.budget.min_rebuttals_per_agent
            ):
                parts.append(
                    "COLLISION CONVERGENCE GATE: every non-withdrawn opponent argument "
                    "family has a durable, complete rebuttal from you. "
                    "The ordinary collision contract is satisfied. Call conclude_pass now; "
                    "do not add another rebuttal, rewrite the unit, or polish an argument. "
                    "If an argument changed since your rebuttal, record its version gap "
                    "for the next continuous repair stage rather than replaying collision."
                )
            stale = [
                item for item in opponent_arguments
                if item.status.value != "withdrawn"
                and item.argument_id in covered_targets
                and (item.argument_id, item.version) not in {
                    (reb.target_argument_id, reb.target_version)
                    for reb in rebuttals if not reb.missing_fields()
                }
            ]
            if stale:
                parts.append(
                    "VERSION GAPS FOR CONTINUOUS REPAIR (not an endless collision "
                    "checkpoint invalidation): " + ", ".join(
                        f"{item.argument_id} current v{item.version}"
                        for item in stale
                    )
                )

        incoming_rebuttals = [
            item
            for item in await self.store.list_rebuttals(session.session_id, opponent)
            if item.target_agent is agent
        ]
        if incoming_rebuttals:
            parts.append("== Opponent rebuttals against your current case (repair these) ==")
            for item in incoming_rebuttals:
                parts.append(
                    f"- {item.rebuttal_id} -> {item.target_argument_id} v{item.target_version} "
                    f"[{item.status.value}] {item.title}\n"
                    f"  Fair reconstruction: {item.reconstruction[:400]}\n"
                    f"  Attack: {item.attack[:650]}\n  Why it matters: {item.why_it_matters[:400]}\n"
                    f"  Likely repair: {item.likely_response[:350]}"
                )

        issues = [
            i
            for i in await self.store.list_issues(session.session_id)
            if i.to_agent is agent and i.state.value == "open"
        ]
        if issues:
            parts.append("== Open issues addressed to you ==")
            for i in issues:
                parts.append(f"- {i.issue_id} [{i.priority}] {i.title}: {i.body[:300]}")
        return "\n\n".join(parts) or "(no state yet)"

    # ------------------------------------------------------------------ pass

    async def _run_pass(
        self, session: ResearchSession, agent: Party, pass_no: int, mode: str
    ):
        budget = PassBudget(session.budget)
        self._activity(
            mode,
            f"{agent.value} 方正在执行第 {pass_no} 个研究 Pass",
            agent=agent,
            pass_no=pass_no,
            kind="pass",
            title="开始研究 Pass",
            summary="读取已有研究状态，建立本轮行动上下文",
            budget=budget,
        )
        system_content = self.prompt_builder(
            mode, agent, session.question, session.position_for(agent)
        )
        system_content += "\n\n" + research_policy(session.profile).guidance
        messages = [
            {"role": "system", "content": system_content},
            {"role": "user", "content": await self._build_context(session, agent, mode)},
        ]
        unproductive_turns = 0
        tokens_at_last_progress = 0
        failed_search_terms: set[str] = set()
        similar_failed_searches = 0
        search_branch_closed = False
        search_branch_directive = ""
        attempted_source_actions: set[tuple[str, str]] = set()
        consecutive_failed_source_actions = 0
        retrieval_branch_closed = False
        retrieval_branch_directive = ""
        invalid_argument_updates = 0
        argument_update_closed = False
        argument_update_directive = ""
        # Consecutive plan-only revisions are a signal that the model is
        # narrating a route instead of executing it. Persisted mutations make
        # this gate survive a host restart or checkpoint resume.
        all_history = [
            item for item in await self.log.list() if item.agent is agent
        ]
        pass_history = [item for item in all_history if item.pass_no == pass_no]
        plan_only_streak = 0
        budget_horizon_announced = False
        convergence_announced = False
        collision_exit_announced = False
        continuous_exit_announced = False
        for item in reversed(pass_history):
            if item.action is EngineAction.UPDATE_PLAN:
                plan_only_streak += 1
            else:
                break
        last_conclusion_seq = max(
            (item.seq for item in all_history
             if item.action is EngineAction.CONCLUDE_PASS),
            default=0,
        )
        continuous_repair_actions = sum(
            item.seq > last_conclusion_seq
            and item.action in {EngineAction.UPDATE_ARGUMENT, EngineAction.UPDATE_REBUTTAL}
            for item in all_history
        ) if mode == "continuous" else 0
        if mode == "continuous" and continuous_repair_actions >= 2:
            system_content += (
                "\n\nBOUNDARY: This continuous handoff has already committed its two "
                "allowed concrete repairs across earlier retry attempts. Do not revise "
                "another argument or rebuttal. Audit the durable result, put any residual "
                "risk in remaining_unknowns, set the plan status to ready_to_conclude, "
                "and conclude. Budget exhaustion is not the stopping reason; the bounded "
                "handoff contract is."
            )
            messages = [
                {"role": "system", "content": system_content},
                {"role": "user", "content": await self._build_context(session, agent, mode)},
                {"role": "user", "content": "The two-repair handoff limit is reached. Submit the final plan audit and conclude now; record every other concern as a residual risk."},
            ]
            continuous_exit_announced = True
        while not budget.exhausted:
            remaining_tokens = (
                session.budget.max_tokens_per_pass - budget.usage.total_tokens
            )
            estimated_next_input = (self._message_chars(messages) + 1) // 2
            recent_output_cushion = max(
                2_500, min(6_000, int(budget.usage.last_output_tokens * 1.25))
            )
            dynamic_reserve = max(
                session.budget.min_token_reserve_per_model_turn,
                estimated_next_input + recent_output_cushion,
            )
            if (
                budget.usage.model_turns > 0
                and not budget_horizon_announced
                and remaining_tokens <= 4 * dynamic_reserve
            ):
                budget_horizon_announced = True
                horizon_directive = (
                    "\n\nPASS BUDGET HORIZON: Review your own stopping conditions "
                    "against the durable case now. If the remaining work is not "
                    "decisive, set update_plan status=ready_to_conclude and call "
                    "conclude_pass in the same tool batch. If a decisive gap remains, "
                    "commit that one concrete repair, then reassess. Avoid duplicate "
                    "plan wording and map polishing. A safety ceiling does not prove "
                    "that the case is stable."
                )
                system_content += horizon_directive
                messages[0] = {"role": "system", "content": system_content}
                self._activity(
                    mode,
                    f"{agent.value} 方正在自主核对收束条件",
                    agent=agent, pass_no=pass_no, kind="budget",
                    title="接近 Pass 预算，提示模型评估收束",
                    status="warning",
                    summary=(
                        "不强行宣布完成；请根据已有论证判断是否结束，"
                        "或只处理仍然关键的缺口"
                    ),
                    budget=budget,
                )
            if (
                budget.usage.model_turns > 0
                and remaining_tokens
                < dynamic_reserve
            ):
                reason = (
                    f"当前 Pass 仅余 {remaining_tokens:,} Token，低于下一轮安全预留 "
                    f"{dynamic_reserve:,} Token（预计输入 {estimated_next_input:,} + "
                    f"输出余量 {recent_output_cushion:,}）"
                )
                self._activity(
                    mode,
                    f"{agent.value} 方在下一次模型调用前安全停止",
                    agent=agent,
                    pass_no=pass_no,
                    kind="early_stop",
                    title="预算预判阻止超额调用",
                    status="error",
                    summary=reason,
                    budget=budget,
                )
                raise PassBudgetExhausted(
                    "predictive token stop before hard budget: " + reason
                )
            model = self.llm if agent is Party.A else self.llm_b
            current_plan = await self.store.load_plan(session.session_id, agent)
            plan_current = current_plan is not None and current_plan.phase == mode
            exit_contract_ready = False
            if (
                mode == "continuous"
                and continuous_repair_actions >= 2
                and not continuous_exit_announced
            ):
                continuous_exit_announced = True
                system_content += (
                    "\n\nCONTINUOUS EXIT WINDOW: Two concrete repairs are already "
                    "committed. No more repair is permitted. Update the plan with "
                    "status=ready_to_conclude and empty next_actions, put all remaining "
                    "concerns in the conclusion, and call conclude_pass now."
                )
                messages = [
                    {"role": "system", "content": system_content},
                    {"role": "user", "content": await self._build_context(session, agent, mode)},
                    {"role": "user", "content": "The bounded repair handoff is complete. Submit the final audit and conclude; do not request another repair."},
                ]
            if plan_current and current_plan.status == "ready_to_conclude":
                exit_contract_ready = await self._conclusion_error(
                    mode,
                    agent,
                    pass_no,
                    {
                        "summary": "preflight",
                        "attempted": "preflight",
                        "changed": "preflight",
                        "remaining_unknowns": "preflight",
                        "why_stop": "preflight",
                        "next_pass": "preflight",
                        "no_high_value_direction": True,
                    },
                    budget=budget,
                ) is None
            case_frame_ready = (
                mode != "expansion"
                or await self._case_frame_ready(session.session_id, agent)
            )
            convergence_ready = (
                mode == "expansion"
                and await self._expansion_state_complete(session, agent)
            )
            if convergence_ready and not convergence_announced:
                convergence_announced = True
                system_content += (
                    "\n\nPASS ONE EXIT WINDOW: The durable state now satisfies the "
                    "mechanical construction contract. Do not reopen search, maps or "
                    "argument polishing. Make one honest final audit: put unresolved "
                    "empirical or strategic questions in remaining_unknowns, update the "
                    "current plan with status=ready_to_conclude, empty next_actions and "
                    "an honest stopping assessment, and call conclude_pass in the same "
                    "tool batch. Completion does not mean claiming certainty."
                )
                messages = [
                    {"role": "system", "content": system_content},
                    {"role": "user", "content": await self._build_context(session, agent, mode)},
                    {"role": "user", "content": "The construction phase is complete. Submit the final plan audit and conclude now; do not reopen work."},
                ]
            available_research_tools = (
                self._pass_tools()
                if (
                    plan_current
                    and not exit_contract_ready
                    and
                    mode == "expansion"
                    and
                    not budget.research_exhausted
                    and case_frame_ready
                    and not convergence_ready
                )
                else []
            )
            if retrieval_branch_closed:
                available_research_tools = []
            elif search_branch_closed:
                available_research_tools = [
                    tool for tool in available_research_tools
                    if tool.get("function", {}).get("name") != "search"
                ]
            budget.record_context(self._message_chars(messages))
            self._activity(
                mode,
                f"{agent.value} 方正在判断下一步最有价值的行动",
                agent=agent,
                pass_no=pass_no,
                kind="model",
                title="模型正在决策",
                summary=(
                    "先自主规划本阶段；当前只提供计划工具"
                    if not plan_current
                    else "先完成自主立论骨架；当前不提供搜索工具"
                    if not case_frame_ready
                    else "根据当前论证和明确缺口选择下一步"
                ),
                budget=budget,
            )
            collision_coverage_complete = False
            collision_uncovered: set[str] = set()
            if mode == "collision":
                opponent_arguments = await self.store.list_arguments(
                    session.session_id, _other(agent)
                )
                own_rebuttals = await self.store.list_rebuttals(
                    session.session_id, agent
                )
                live_targets = {
                    item.argument_id
                    for item in opponent_arguments
                    if item.status.value != "withdrawn"
                }
                covered_targets = {
                    item.target_argument_id
                    for item in own_rebuttals
                    if not item.missing_fields()
                    and item.status.value not in {"withdrawn", "answered"}
                }
                collision_coverage_complete = bool(live_targets) and (
                    live_targets <= covered_targets
                    and len([item for item in own_rebuttals if not item.missing_fields()])
                    >= session.budget.min_rebuttals_per_agent
                )
                collision_uncovered = live_targets - covered_targets
                if collision_coverage_complete and not collision_exit_announced:
                    collision_exit_announced = True
                    system_content += (
                        "\n\nCOLLISION EXIT WINDOW: Every current opponent argument has "
                        "a complete rebuttal. Cross-review is finished. Put residual "
                        "risks in remaining_unknowns, update the plan with "
                        "status=ready_to_conclude and empty next_actions, and call "
                        "conclude_pass in the same batch. Own-case repairs belong to the "
                        "bounded continuous handoff; do not reopen them here."
                    )
                    messages = [
                        {"role": "system", "content": system_content},
                        {"role": "user", "content": await self._build_context(session, agent, mode)},
                        {"role": "user", "content": "Opponent-argument coverage is complete. Submit the final plan audit and conclude now; do not create another rebuttal or repair your own case."},
                    ]
            if not plan_current:
                allowed_engine_actions = {"update_plan"}
            elif (
                mode == "continuous"
                and continuous_repair_actions >= 2
                and current_plan.status == "ready_to_conclude"
            ):
                allowed_engine_actions = {"conclude_pass"}
            elif exit_contract_ready:
                # The model has already declared its plan complete and every
                # mechanical phase duty passes a dry-run audit. Do not let a
                # final wording pass turn back into more research or polishing.
                allowed_engine_actions = {"conclude_pass"}
            elif convergence_ready:
                # Pass One's mechanical contract is already satisfied: a case
                # spine, proof map, exact-motion attempt and enough complete
                # arguments exist.  Further argument/map polishing was the main
                # source of 300k+ token non-termination.  The model still owns
                # the stopping judgment, but must now express it as an honest
                # plan audit and conclusion with residual unknowns, not reopen
                # the completed construction phase.
                allowed_engine_actions = (
                    {"conclude_pass"}
                    if current_plan.status == "ready_to_conclude"
                    else {"update_plan", "conclude_pass"}
                )
            elif collision_coverage_complete:
                allowed_engine_actions = (
                    {"conclude_pass"}
                    if current_plan.status == "ready_to_conclude"
                    else {"update_plan", "conclude_pass"}
                )
            elif mode == "collision":
                # This pass is for reading and testing the opponent's current
                # case. Own-case repair happens in the following bounded handoff;
                # mixing both jobs caused full-pass polishing loops.
                allowed_engine_actions = {
                    "update_plan", "update_rebuttal", "conclude_pass",
                }
            elif mode == "continuous":
                # Continuous repair is a bounded handoff, not another Pass One.
                # Keep the model's semantic freedom (it chooses which case break
                # matters) while removing expansion-shaped actions that repeatedly
                # reopened research maps and consumed a whole pass before exit.
                allowed_engine_actions = {
                    "update_plan", "update_rebuttal", "update_argument",
                    "conclude_pass",
                }
            elif mode == "expansion":
                # Pass One is private position construction. It cannot see the
                # opponent and therefore cannot create valid rebuttals or
                # cross-party work orders. Keeping those generic actions open
                # caused fabricated target ids and wasted turns.
                allowed_engine_actions = {
                    "update_plan", "update_unit", "update_map",
                    "record_evidence", "update_argument", "conclude_pass",
                }
            else:
                allowed_engine_actions = set(ENGINE_ACTION_NAMES)
            if mode == "continuous" and continuous_repair_actions >= 2:
                allowed_engine_actions = {"update_plan", "conclude_pass"}
            if (
                plan_only_streak >= 2
                and not exit_contract_ready
                and not convergence_ready
                and not collision_coverage_complete
                and not (
                    mode == "continuous" and continuous_repair_actions >= 2
                )
            ):
                allowed_engine_actions.discard("update_plan")
                # A plan can be revised again after a concrete state action.
                # A collision pass keeps its rebuttal tool regardless of how
                # many plan revisions were made beforehand.
                self._activity(
                    mode,
                    f"{agent.value} 方连续修改计划但尚未执行路线",
                    agent=agent, pass_no=pass_no, kind="gate",
                    title="从规划切换到实际行动", status="warning",
                    summary=(
                        "计划工具暂时隐藏；请执行现有计划中的论点、驳论或其他具体行动，"
                        "产生可保留成果后才重新开放修订"
                    ),
                    budget=budget,
                )
            available_engine_tools = [
                tool for tool in ENGINE_ACTION_TOOLS
                if tool.get("function", {}).get("name") in allowed_engine_actions
            ]
            if mode == "continuous":
                # This phase repairs the existing case; it never invents a new
                # argument family. Constrain the identifier at the provider
                # contract so human-readable aliases from the model's plan
                # cannot be mistaken for new argument ids.
                own_arguments = await self.store.list_arguments(
                    session.session_id, agent
                )
                own_argument_ids = [
                    item.argument_id for item in own_arguments
                    if item.status.value != "withdrawn"
                ]
                if own_argument_ids:
                    available_engine_tools = copy.deepcopy(available_engine_tools)
                    title_index = "; ".join(
                        f"{item.argument_id} = {item.title}"
                        for item in own_arguments
                        if item.status.value != "withdrawn"
                    )
                    for tool in available_engine_tools:
                        function = tool.get("function", {})
                        if function.get("name") == "update_argument":
                            properties = function.get("parameters", {}).get("properties", {})
                            properties["argument_id"] = {
                                "type": "string",
                                "enum": own_argument_ids,
                                "description": (
                                    "Choose the exact existing argument id to repair. "
                                    "Do not use a title or plan alias. " + title_index
                                ),
                            }
            if mode == "collision" and collision_uncovered:
                # Make target ownership explicit in the contract. On resumed
                # collision passes, the context also contains the opponent's
                # rebuttals against us; without an enum some models mistake our
                # own argument ids mentioned there for legal attack targets.
                available_engine_tools = copy.deepcopy(available_engine_tools)
                for tool in available_engine_tools:
                    function = tool.get("function", {})
                    if function.get("name") == "update_rebuttal":
                        properties = function.get("parameters", {}).get("properties", {})
                        properties["target_argument_id"] = {
                            "type": "string", "enum": sorted(collision_uncovered),
                            "description": "Choose one uncovered opponent argument id from this exact list.",
                        }
            if (
                (
                    convergence_ready
                    or collision_coverage_complete
                    or (mode == "continuous" and continuous_repair_actions >= 2)
                )
                and current_plan is not None
                and current_plan.status != "ready_to_conclude"
            ):
                # Make the state transition unambiguous at the tool-contract
                # boundary. The model still writes the audit; it cannot submit
                # another "active" plan after declaring the case complete.
                available_engine_tools = copy.deepcopy(available_engine_tools)
                for tool in available_engine_tools:
                    function = tool.get("function", {})
                    if function.get("name") == "update_plan":
                        properties = function.get("parameters", {}).get("properties", {})
                        properties["status"] = {
                            "type": "string", "enum": ["ready_to_conclude"],
                            "description": "The construction contract is complete; submit the final audit state.",
                        }
                        properties["next_actions"] = {
                            "type": "array", "maxItems": 0,
                            "description": "Must be empty in the Pass One exit window.",
                            "items": {"type": "object"},
                        }
            if argument_update_closed:
                available_engine_tools = [
                    tool for tool in available_engine_tools
                    if tool.get("function", {}).get("name") != "update_argument"
                ]
            offered_tool_names = {
                tool.get("function", {}).get("name")
                for tool in available_engine_tools + available_research_tools
            }
            turn = await model.run(messages, available_engine_tools + available_research_tools)
            for tool_call in turn.tool_calls:
                tool_call.name = _canonical_tool_name(
                    tool_call.name, {name for name in offered_tool_names if name}
                )
            budget.record_model_turn()
            budget.record_tokens(turn.usage)
            self._activity(
                mode,
                f"{agent.value} 方完成本轮模型调用",
                agent=agent,
                pass_no=pass_no,
                kind="model",
                title="模型返回行动决定",
                status="done",
                summary=(
                    f"本轮实际输入 {turn.usage.input_tokens:,} Token，"
                    f"输出 {turn.usage.output_tokens:,} Token"
                ),
                details=[
                    {"label": "工具行动", "value": str(len(turn.tool_calls))},
                ],
                budget=budget,
            )

            if not turn.tool_calls:
                self._activity(
                    mode,
                    f"{agent.value} 方返回了分析文字，正在要求其转化为可执行行动",
                    agent=agent,
                    pass_no=pass_no,
                    kind="model",
                    title="尚未提交结构化行动",
                    status="warning",
                    summary="模型本轮没有调用搜索、证据、论点或结束工具",
                    budget=budget,
                )
                # Free-form analysis is not durable research output.  Discard it
                # and rebuild from the blackboard rather than paying for it in
                # every subsequent request.
                messages = [
                    {"role": "system", "content": system_content},
                    {"role": "user", "content": await self._build_context(session, agent, mode)},
                    {
                        "role": "user",
                        "content": (
                            "Your previous response did not commit an action. Choose the "
                            "single highest-value search/read/state action now."
                        ),
                    },
                ]
                unproductive_turns += 1
                tokens_without_progress = (
                    budget.usage.total_tokens - tokens_at_last_progress
                )
                if (
                    unproductive_turns
                    >= session.budget.max_unproductive_turns_per_pass
                    or tokens_without_progress
                    >= session.budget.max_tokens_without_state_progress
                ):
                    reason = (
                        f"连续 {unproductive_turns} 轮未提交结构化成果；"
                        f"已消耗 {tokens_without_progress:,} Token 但没有可保留进展"
                    )
                    self._activity(
                        mode,
                        f"{agent.value} 方因空转触发早停",
                        agent=agent,
                        pass_no=pass_no,
                        kind="early_stop",
                        title="模型思考未转化为成果",
                        status="error",
                        summary=reason,
                        budget=budget,
                    )
                    raise PassBudgetExhausted(
                        "behavioral early stop after text-only turns: " + reason
                    )
                budget.record_context(self._message_chars(messages), compacted=True)
                continue

            exchange_start = len(messages)
            messages.append(self._assistant_message(turn))
            # Provider APIs describe tool calls as a batch. Apply state changes
            # before conclusion even when a model emitted conclude_pass first.
            ordered_calls = sorted(
                turn.tool_calls, key=lambda tc: tc.name == "conclude_pass"
            )
            selected = "、".join(
                _ACTION_EVENT_LABELS.get(tc.name, "搜索" if tc.name == "search" else "深读来源" if tc.name == "read_source" else "转写音视频" if tc.name == "transcribe_source" else tc.name)
                for tc in ordered_calls
            )
            self._activity(
                mode,
                f"{agent.value} 方选择了 {len(ordered_calls)} 个行动",
                agent=agent,
                pass_no=pass_no,
                kind="decision",
                title="本轮行动计划",
                status="done",
                summary=selected,
                budget=budget,
            )
            external_actions_seen = 0
            turn_productive = False
            for tc in ordered_calls:
                if tc.name not in offered_tool_names:
                    content = (
                        f"TOOL_GATE: {tc.name} was not offered in this model turn. "
                        "Do not submit hidden, disabled or stale tools. Execute one "
                        "currently offered action that advances the existing case."
                    )
                    messages.append(self._tool_result(tc, content))
                    self._activity(
                        mode,
                        f"{agent.value} 方提交了本轮未开放的工具",
                        agent=agent, pass_no=pass_no, kind="gate",
                        title="未开放动作已被拒绝", status="warning",
                        summary=content, budget=budget,
                    )
                    continue
                if tc.name == "conclude_pass":
                    budget.record_state_action()
                    error = await self._conclusion_error(
                        mode, agent, pass_no, tc.arguments, budget=budget
                    )
                    if error:
                        messages.append(self._tool_result(tc, error))
                        self._activity(
                            mode,
                            f"{agent.value} 方尚未满足本阶段完成条件",
                            agent=agent,
                            pass_no=pass_no,
                            kind="gate",
                            title="结束申请被质量门槛驳回",
                            status="warning",
                            summary=error,
                            budget=budget,
                        )
                        if budget.research_exhausted and (
                            "breadth floor" in error
                            or "source-investigation floor" in error
                        ):
                            raise PassBudgetExhausted(
                                "research allowance exhausted before quality gates: "
                                f"agent={agent.value}, pass={pass_no}, phase={mode}, "
                                f"successful={budget.usage.tool_calls}, "
                                f"failed={budget.usage.failed_tool_calls}"
                            )
                        continue
                    exit_window_active = (
                        convergence_ready
                        or collision_coverage_complete
                        or (mode == "continuous" and continuous_repair_actions >= 2)
                    )
                    if exit_window_active and tc.name == "update_plan":
                        # Some OpenAI-compatible providers ignore a single-value
                        # enum and keep returning an "active" read-only audit.
                        # In an exit window no further action is legally
                        # available, so normalize only the mechanical fields;
                        # all model-written reasoning and residual risks remain.
                        tc.arguments["status"] = "ready_to_conclude"
                        tc.arguments["next_actions"] = []
                        tc.arguments["estimated_remaining_actions"] = 0
                    try:
                        mutation = await apply_action(
                            self.store, self.log, EngineAction.CONCLUDE_PASS,
                            agent, pass_no, tc.arguments,
                        )
                    except (KeyError, TypeError, ValueError) as exc:
                        messages.append(self._tool_result(tc, f"action rejected: {exc}"))
                        self._activity(
                            mode,
                            f"{agent.value} 方的结束记录格式无效",
                            agent=agent,
                            pass_no=pass_no,
                            kind="gate",
                            title="结束动作执行失败",
                            status="error",
                            summary=str(exc),
                            budget=budget,
                        )
                        continue
                    messages.append(self._tool_result(tc, "pass concluded"))
                    self._activity(
                        mode,
                        f"{agent.value} 方完成当前 Pass",
                        agent=agent,
                        pass_no=pass_no,
                        kind="pass",
                        title="Pass 已完成",
                        status="done",
                        summary=self._action_summary(tc.name, tc.arguments),
                        budget=budget,
                    )
                    return mutation
                if tc.name in ENGINE_ACTION_NAMES:
                    if (
                        mode == "continuous"
                        and tc.name in {"update_argument", "update_rebuttal"}
                        and continuous_repair_actions >= 2
                    ):
                        content = (
                            "TOOL_GATE: the bounded continuous handoff has already "
                            "committed two concrete repairs. Audit, set the plan to "
                            "ready_to_conclude, record residual risks in the conclusion, "
                            "and stop instead of opening another revision."
                        )
                        messages.append(self._tool_result(tc, content))
                        self._activity(
                            mode,
                            f"{agent.value} 方已达到连续修复的实质改动边界",
                            agent=agent, pass_no=pass_no, kind="gate",
                            title="停止新增修订，转入终审", status="warning",
                            summary=content, budget=budget,
                        )
                        continue
                    if tc.name == "update_argument" and argument_update_closed:
                        content = "TOOL_GATE: repeated invalid argument update blocked.\n\n" + argument_update_directive
                        messages.append(self._tool_result(tc, content))
                        self._activity(
                            mode,
                            f"{agent.value} 方的重复错误论点修改已被拦截",
                            agent=agent,
                            pass_no=pass_no,
                            kind="gate",
                            title="论点修改工具已切断错误分支",
                            status="warning",
                            summary="请改用驳论工具处理对手论点，或完成本阶段",
                            budget=budget,
                        )
                        continue
                    if tc.name == "update_map":
                        requested_id = str(tc.arguments.get("map_id", ""))
                        existing_entry = (
                            await self.store.load_map_entry(requested_id)
                            if requested_id else None
                        )
                        active_entries = [
                            entry for entry in await self.store.list_map_entries(
                                session.session_id, agent
                            )
                            if entry.status.value == "active"
                        ]
                        requested_status = str(tc.arguments.get("status", "active"))
                        if (
                            existing_entry is None
                            and requested_status == "active"
                            and len(active_entries) >= 5
                        ):
                            error = (
                                "active proof-obligation frontier already has five entries; "
                                "merge this idea into an existing map item, or resolve/dormant "
                                "one before opening another"
                            )
                            messages.append(self._tool_result(tc, f"action rejected: {error}"))
                            self._activity(
                                mode,
                                f"{agent.value} 方的新研究分支被漏斗上限拦截",
                                agent=agent,
                                pass_no=pass_no,
                                kind="gate",
                                title="活跃证明任务已达五项",
                                status="warning",
                                summary="请合并、完成或关闭旧任务，避免分支无限膨胀",
                                budget=budget,
                            )
                            continue
                    if mode == "continuous" and tc.name == "update_argument":
                        own_arguments = await self.store.list_arguments(
                            session.session_id, agent
                        )
                        resolved_id = _resolve_existing_argument_id(
                            tc.arguments, own_arguments
                        )
                        if resolved_id:
                            tc.arguments = dict(tc.arguments)
                            tc.arguments["argument_id"] = resolved_id
                    try:
                        mutation = await apply_action(
                            self.store, self.log, EngineAction(tc.name),
                            agent, pass_no, tc.arguments,
                        )
                    except (KeyError, TypeError, ValueError) as exc:
                        messages.append(self._tool_result(tc, f"action rejected: {exc}"))
                        self._activity(
                            mode,
                            f"{agent.value} 方的本地研究动作未能写入",
                            agent=agent,
                            pass_no=pass_no,
                            kind="state",
                            title=_ACTION_EVENT_LABELS.get(tc.name, tc.name),
                            status="error",
                            summary=str(exc),
                            budget=budget,
                        )
                        if tc.name == "update_argument":
                            invalid_argument_updates += 1
                            # One malformed call must not poison the entire argument
                            # batch: providers occasionally omit fields from one tool
                            # call while their sibling calls are valid. Fuse only after
                            # three consecutive invalid updates, and never while Pass One
                            # still needs this tool to reach its argument floor. Any valid
                            # argument below resets the streak.
                            may_close_argument_branch = mode != "expansion"
                            if mode == "expansion":
                                own_arguments = await self.store.list_arguments(
                                    session.session_id, agent
                                )
                                argument_floor_met = len([
                                    item for item in own_arguments
                                    if item.status.value != "withdrawn"
                                    and not item.missing_proof_fields()
                                ]) >= session.budget.min_core_arguments_per_agent
                                may_close_argument_branch = argument_floor_met
                            if (
                                invalid_argument_updates >= 3
                                and may_close_argument_branch
                                and not argument_update_closed
                            ):
                                argument_update_closed = True
                                own_ids = ", ".join(sorted(
                                    item.argument_id for item in await self.store.list_arguments(
                                        session.session_id, agent
                                    )
                                )) or "none"
                                argument_update_directive = (
                                    "ARGUMENT UPDATE CLOSED FOR THIS PASS after repeated invalid "
                                    "updates. Do not retry or rename the same action. Opponent "
                                    "arguments can only be addressed with update_rebuttal; valid "
                                    f"own argument ids were: {own_ids}. Continue with rebuttals, "
                                    "the integrated unit or map if genuinely needed, then call "
                                    "conclude_pass once the collision duties are satisfied."
                                )
                                messages.append({
                                    "role": "user", "content": argument_update_directive,
                                })
                                self._activity(
                                    mode,
                                    f"{agent.value} 方连续提交无效论点修改，已强制切换行动类型",
                                    agent=agent,
                                    pass_no=pass_no,
                                    kind="gate",
                                    title="错误结构化动作已熔断",
                                    status="warning",
                                    summary="本 Pass 不再提供论点修改；保留驳论、整合和结束能力",
                                    budget=budget,
                                )
                    else:
                        budget.record_state_action()
                        if tc.name == "update_plan":
                            plan_only_streak += 1
                        else:
                            plan_only_streak = 0
                        if tc.name == "update_argument":
                            invalid_argument_updates = 0
                        if mode == "continuous" and tc.name in {
                            "update_argument", "update_rebuttal"
                        }:
                            continuous_repair_actions += 1
                        ref = mutation.target.id if mutation.target else "ok"
                        turn_productive = True
                        messages.append(self._tool_result(tc, f"applied ({ref})"))
                        details = [
                            {"label": "变化", "value": str(tc.arguments.get("what_changed", ""))},
                            {"label": "原因", "value": str(tc.arguments.get("why", ""))},
                        ]
                        self._activity(
                            mode,
                            f"{agent.value} 方正在{_ACTION_EVENT_LABELS.get(tc.name, '更新研究状态')}",
                            agent=agent,
                            pass_no=pass_no,
                            kind=tc.name.removeprefix("update_").removeprefix("record_"),
                            title=_ACTION_EVENT_LABELS.get(tc.name, tc.name),
                            status="done",
                            summary=self._action_summary(tc.name, tc.arguments),
                            details=[item for item in details if item["value"]],
                            budget=budget,
                        )
                else:
                    if retrieval_branch_closed:
                        content = "TOOL_GATE: external retrieval is closed for this pass.\n\n" + retrieval_branch_directive
                        messages.append(self._tool_result(tc, content))
                        continue
                    source_action = tc.name in {"read_source", "transcribe_source"}
                    source_action_key = (
                        tc.name, str(tc.arguments.get("source_id", ""))
                    )
                    if source_action and source_action_key in attempted_source_actions:
                        retrieval_branch_closed = True
                        retrieval_branch_directive = (
                            "EXTERNAL RETRIEVAL CLOSED FOR THIS PASS. The same source action "
                            "was requested again after its first result was already returned. "
                            "The external tools are now unavailable. Use the preserved snippets "
                            "and current case: update arguments, mark unavailable factual tasks "
                            "externally blocked or withdraw them, update the integrated unit, "
                            "and conclude the pass."
                        )
                        content = "TOOL_GATE: duplicate source action blocked.\n\n" + retrieval_branch_directive
                        messages.append(self._tool_result(tc, content))
                        self._activity(
                            mode,
                            f"{agent.value} 方的重复来源请求被拦截",
                            agent=agent,
                            pass_no=pass_no,
                            kind="gate",
                            title="重复读取已触发收束",
                            status="warning",
                            summary="同一来源动作不会再次执行；本 Pass 切回论证整理",
                            budget=budget,
                        )
                        continue
                    if source_action:
                        attempted_source_actions.add(source_action_key)
                    if (
                        tc.name == "transcribe_source"
                        and budget.usage.audio_transcriptions >= 1
                    ):
                        content = (
                            "tool request deferred: this position has already transcribed one "
                            "selected video in the current pass. Extract and use its arguments; "
                            "a later pass may select another only if a named gap remains."
                        )
                        messages.append(self._tool_result(tc, content))
                        self._activity(
                            mode,
                            f"{agent.value} 方的视频转写请求被顺延",
                            agent=agent,
                            pass_no=pass_no,
                            kind="gate",
                            title="本 Pass 视频转写已达上限",
                            status="warning",
                            summary="每方每个 Pass 最多转写一个经过筛选的视频",
                            budget=budget,
                        )
                        continue
                    if (
                        external_actions_seen
                        >= session.budget.max_parallel_research_actions_per_turn
                        or (tc.name == "search" and external_actions_seen >= 1)
                    ):
                        content = (
                            "tool request deferred: the staged evidence funnel permits one "
                            "search, or at most two already-screened source reads, per model "
                            "turn. Consume and classify this batch before another retrieval."
                        )
                        messages.append(self._tool_result(tc, content))
                        self._activity(
                            mode,
                            f"{agent.value} 方的并行研究请求被顺延",
                            agent=agent,
                            pass_no=pass_no,
                            kind="gate",
                            title="外部研究批次已达上限",
                            status="warning",
                            summary="先消化当前搜索或至多两份候选材料，再启动下一批",
                            budget=budget,
                        )
                        continue
                    external_actions_seen += 1
                    if budget.research_exhausted:
                        content = (
                            "research-tool allowance for this pass is exhausted. Synthesize "
                            "the inspected material now: record evidence, update arguments, "
                            "resolve the map, and conclude the pass."
                        )
                        self._activity(
                            mode,
                            f"{agent.value} 方已到达本 Pass 的外部研究额度",
                            agent=agent,
                            pass_no=pass_no,
                            kind="budget",
                            title="搜索与阅读额度已用完",
                            status="warning",
                            summary="仍可整理证据、修建立论并提交本轮成果",
                            budget=budget,
                        )
                    else:
                        if tc.name == "search":
                            details = [
                                {"label": "目的", "value": str(tc.arguments.get("purpose", ""))},
                                {"label": "策略", "value": str(tc.arguments.get("strategy", ""))},
                            ]
                            title = "发起定向搜索"
                            summary = str(tc.arguments.get("query", ""))
                            message = f"{agent.value} 方正在搜索：{summary[:90]}"
                        elif tc.name == "read_source":
                            source = await self.store.load_source(str(tc.arguments.get("source_id", "")))
                            details = [
                                {"label": "阅读目的", "value": str(tc.arguments.get("purpose", ""))},
                                {
                                    "label": "聚焦词",
                                    "value": "、".join(
                                        str(item) for item in tc.arguments.get("focus_terms", []) if item
                                    ),
                                },
                            ]
                            title = "深读候选来源"
                            summary = source.title if source else str(tc.arguments.get("source_id", ""))
                            message = f"{agent.value} 方正在深读：{summary[:90]}"
                        elif tc.name == "transcribe_source":
                            source = await self.store.load_source(str(tc.arguments.get("source_id", "")))
                            details = [
                                {"label": "转写目的", "value": str(tc.arguments.get("purpose", ""))},
                                {"label": "语言", "value": str(tc.arguments.get("language", "自动识别"))},
                            ]
                            title = "转写音视频材料"
                            summary = source.title if source else str(tc.arguments.get("source_id", ""))
                            message = f"{agent.value} 方正在转写：{summary[:90]}"
                        else:
                            details = []
                            title = f"调用研究工具：{tc.name}"
                            summary = str(tc.arguments)[:300]
                            message = f"{agent.value} 方正在调用 {tc.name}"
                        self._activity(
                            mode,
                            message,
                            agent=agent,
                            pass_no=pass_no,
                            kind="search" if tc.name == "search" else "read" if tc.name in {"read_source", "transcribe_source"} else "tool",
                            title=title,
                            summary=summary,
                            details=[item for item in details if item["value"]],
                            budget=budget,
                        )
                        try:
                            content = await self._execute_pass_tool(
                                session.session_id, agent, tc.name, tc.arguments
                            )
                        except (TypeError, ValueError) as exc:
                            content = f"tool request rejected: {exc}"
                        failed = self._tool_result_failed(content)
                        cached_read = content.startswith("CACHED_SOURCE_ALREADY_INSPECTED:")
                        gated_search = content.startswith("SEARCH_GATE:")
                        if not cached_read and not gated_search:
                            budget.record_tool_call(
                                success=not failed,
                                kind=tc.name,
                                mode=str(tc.arguments.get("search_mode", "argument_discovery")),
                                discovery_kind=str(tc.arguments.get("discovery_kind", "")),
                            )
                        if (
                            tc.name == "search"
                            and not gated_search
                            and str(tc.arguments.get("discovery_kind", "")) == "exact_motion"
                        ):
                            # The protocol requires one honest attempt, not a
                            # successful result. Persist it independently from
                            # the source pool so an empty result can still resume.
                            await self._record_protocol_attempt(
                                session, "exact_motion", agent
                            )
                        if tc.name in {"read_source", "transcribe_source"} and not failed and not cached_read:
                            turn_productive = True
                        if tc.name == "search" and not failed:
                            count = sum(
                                1 for line in content.splitlines()
                                if line.startswith("[src_")
                            )
                            if count:
                                # Screened, newly persisted leads are genuine
                                # progress. A later read or argument revision
                                # still decides whether they are useful.
                                turn_productive = True
                            screening = re.search(
                                r"SCREENING fetched=(\d+) accepted=(\d+) rejected=(\d+)",
                                content,
                            )
                            if screening:
                                outcome = (
                                    f"初筛 {screening.group(1)} 条，保留 {screening.group(2)} 条，"
                                    f"拦截 {screening.group(3)} 条噪声或重复结果"
                                )
                            else:
                                outcome = f"返回 {count} 个候选来源；下一步应选择强候选深读或调整查询"
                        elif tc.name == "read_source" and cached_read:
                            outcome = "该来源已经读过；直接复用缓存文本，不重复消耗网络阅读额度"
                        elif tc.name == "read_source" and not failed:
                            outcome = f"已读取约 {len(content):,} 字符；尚需提取方法、局限和可证明命题"
                        elif tc.name == "transcribe_source" and not failed:
                            outcome = f"已获得约 {len(content):,} 字符带时间戳文本；尚需提取可用论证并核对说话者归属"
                        else:
                            outcome = content.splitlines()[0][:500] if content else "工具没有返回内容"
                        if tc.name == "search":
                            accepted = sum(
                                1 for line in content.splitlines()
                                if line.startswith("[src_")
                            )
                            stalled = failed or accepted == 0
                            current_terms = self._text_terms(" ".join((
                                str(tc.arguments.get("query", "")),
                                str(tc.arguments.get("purpose", "")),
                            )))
                            if stalled:
                                overlap = (
                                    len(current_terms & failed_search_terms)
                                    / max(1, len(current_terms | failed_search_terms))
                                    if failed_search_terms else 0.0
                                )
                                similar_failed_searches = (
                                    similar_failed_searches + 1
                                    if failed_search_terms and overlap >= 0.45 else 1
                                )
                                failed_search_terms = current_terms
                                if similar_failed_searches >= 2 and not search_branch_closed:
                                    search_branch_closed = True
                                    search_branch_directive = (
                                        "RETRIEVAL BRANCH CLOSED FOR THIS PASS. Two materially "
                                        "similar searches failed or yielded no new candidate. The "
                                        "search tool is now unavailable. Do not rename the same query. "
                                        "Use already discovered sources, revise the factual premise into "
                                        "a reasoning claim, or mark the exact map obligation externally "
                                        "blocked with the concrete failed target; then update the integrated "
                                        "unit and conclude when the remaining case is defensible."
                                    )
                                    content += "\n\n" + search_branch_directive
                                    outcome = "相似检索连续两次无新增结果；本 Pass 已封存该检索分支并切回论证整合"
                            else:
                                similar_failed_searches = 0
                                failed_search_terms = set()
                        if source_action:
                            if failed:
                                consecutive_failed_source_actions += 1
                            else:
                                consecutive_failed_source_actions = 0
                            if (
                                consecutive_failed_source_actions >= 3
                                and not retrieval_branch_closed
                            ):
                                retrieval_branch_closed = True
                                retrieval_branch_directive = (
                                    "EXTERNAL RETRIEVAL CLOSED FOR THIS PASS. Three selected "
                                    "source actions failed consecutively. Do not hunt for a fourth "
                                    "copy. Use the preserved source leads and reasoning already on "
                                    "the blackboard; mark the exact unavailable fact externally "
                                    "blocked or revise the argument so it no longer depends on it, "
                                    "then update the integrated unit and conclude."
                                )
                                content += "\n\n" + retrieval_branch_directive
                                outcome = "连续三个来源动作失败；本 Pass 已停止外部读取并切回论证整合"
                        self._activity(
                            mode,
                            f"{agent.value} 方的{title}已{'失败' if failed else '返回'}",
                            agent=agent,
                            pass_no=pass_no,
                            kind="search" if tc.name == "search" else "read" if tc.name in {"read_source", "transcribe_source"} else "tool",
                            title=f"{title}结果",
                            status="error" if failed else "done",
                            summary=outcome,
                            budget=budget,
                        )
                    messages.append(self._tool_result(tc, content))

            if turn_productive:
                unproductive_turns = 0
                tokens_at_last_progress = budget.usage.total_tokens
            else:
                unproductive_turns += 1
            tokens_without_progress = (
                budget.usage.total_tokens - tokens_at_last_progress
            )
            if (
                unproductive_turns >= session.budget.max_unproductive_turns_per_pass
                or tokens_without_progress
                >= session.budget.max_tokens_without_state_progress
            ):
                reason = (
                    f"连续 {unproductive_turns} 个模型轮次没有形成可保留的论证、证据或有效深读；"
                    f"距上次有效进展已消耗 {tokens_without_progress:,} Token"
                )
                self._activity(
                    mode,
                    f"{agent.value} 方触发低产出早停",
                    agent=agent,
                    pass_no=pass_no,
                    kind="early_stop",
                    title="旁路监控已暂停本轮",
                    status="error",
                    summary=reason,
                    details=[{"label": "处理建议", "value": "检查轨迹与提示词后再从检查点恢复"}],
                    budget=budget,
                )
                raise PassBudgetExhausted(
                    "behavioral early stop before hard budget: " + reason
                )

            # The durable blackboard, not an ever-growing chat transcript, is the
            # memory of the engine. Never resend the assistant's full structured
            # tool arguments after they have been committed: that duplicated the
            # same case once as tool JSON and again as blackboard state. Preserve
            # only compact tool outcomes so the next turn can react to failures or
            # newly retrieved material.
            before_chars = self._message_chars(messages)
            latest_tool_outcomes = [
                str(item.get("content", ""))
                for item in messages[exchange_start + 1:]
                if item.get("role") == "tool" and item.get("content")
            ]
            feedback = "\n\n".join(latest_tool_outcomes)
            if len(feedback) > self.max_tool_result_chars:
                feedback = feedback[: self.max_tool_result_chars]
            messages = [
                {"role": "system", "content": system_content},
                {"role": "user", "content": await self._build_context(session, agent, mode)},
            ]
            if feedback:
                messages.append({
                    "role": "user",
                    "content": "Outcomes from the immediately previous actions:\n" + feedback,
                })
            if search_branch_directive:
                messages.append({
                    "role": "user",
                    "content": search_branch_directive,
                })
            if retrieval_branch_directive:
                messages.append({
                    "role": "user",
                    "content": retrieval_branch_directive,
                })
            if argument_update_directive:
                messages.append({
                    "role": "user",
                    "content": argument_update_directive,
                })
            after_chars = self._message_chars(messages)
            budget.record_context(after_chars, compacted=True)
            self._activity(
                mode,
                f"{agent.value} 方已把本轮结果压缩进研究黑板",
                agent=agent,
                pass_no=pass_no,
                kind="context",
                title="滚动整理上下文",
                status="done",
                summary=(
                    f"保留最新工具结果，历史对话从约 {before_chars:,} 字符整理为 "
                    f"{after_chars:,} 字符"
                ),
                details=[
                    {"label": "长期记忆", "value": "论点、证据卡、来源索引和证明任务"},
                    {"label": "短期记忆", "value": "仅保留最近一轮工具结果供下一轮消费"},
                ],
                budget=budget,
            )

        # A mechanical ceiling can never certify a phase as complete. Preserve a
        # diagnostic mutation and leave the phase resumable from durable state.
        await apply_action(
            self.store, self.log, EngineAction.CONCLUDE_PASS, agent, pass_no,
            {
                "summary": "pass budget exhausted before quality gates",
                "attempted": "research continued until the mechanical pass ceiling",
                "changed": "durable source and argument state was preserved",
                "remaining_unknowns": "the phase contract remains incomplete",
                "why_stop": "mechanical pass budget",
                "next_pass": "resume this same phase from durable state",
                "no_high_value_direction": False,
            },
        )
        self._activity(
            mode,
            f"{agent.value} 方达到模型轮次或 Token 硬上限",
            agent=agent,
            pass_no=pass_no,
            kind="budget",
            title="本轮机械预算耗尽",
            status="error",
            summary="状态已保存，但当前阶段尚未满足质量门槛",
            budget=budget,
        )
        raise PassBudgetExhausted(
            f"pass budget exhausted before quality gates: agent={agent.value}, "
            f"pass={pass_no}, phase={mode}"
        )

    async def _run_and_checkpoint(
        self, session: ResearchSession, agent: Party, pass_no: int, mode: str,
        checkpoint_key: str,
    ):
        result = await self._run_pass(session, agent, pass_no, mode)
        completed = session.phase_progress.setdefault(checkpoint_key, [])
        if agent.value not in completed:
            completed.append(agent.value)
        session.updated_at = now_iso()
        await self.store.save_session(session)
        self._progress(
            mode,
            f"{agent.value} 方检查点已持久化",
            agent=agent.value,
            pass_no=pass_no,
            checkpoint=checkpoint_key,
        )
        return result

    async def _expansion_state_complete(
        self, session: ResearchSession, agent: Party
    ) -> bool:
        """Revalidate a checkpoint through the same audit used at conclusion."""

        return await self._expansion_completion_error(session, agent) is None

    async def _expansion_checkpoint_intact(
        self, session: ResearchSession, agent: Party
    ) -> bool:
        """Check that a completed Pass One still has its durable deliverables.

        Later collision/repair work may legitimately reopen a shared map item or
        alter an argument.  That must not send a resumed session back in time to
        Pass One; the original conclusion mutation is the completion decision.
        Recovery therefore checks integrity, not today's open-work frontier.
        """

        if not session.budget.min_core_arguments_per_agent:
            return bool(
                any(
                    unit.content.strip()
                    for unit in await self.store.list_units(session.session_id, agent)
                )
                and await self.store.list_map_entries(session.session_id, agent)
            )
        viable = [
            item for item in await self.store.list_arguments(session.session_id, agent)
            if item.status.value != "withdrawn"
            and (
                not item.missing_proof_fields()
                or (
                    set(item.missing_proof_fields()) == {"evidence_ids"}
                    and bool(item.evidence_need)
                )
            )
        ]
        return len(viable) >= session.budget.min_core_arguments_per_agent

    async def _repair_phase_progress(self, session: ResearchSession) -> None:
        """Remove markers written by older runtimes that accepted budget exhaustion."""

        changed = False
        # Older runtimes allowed one side to reuse the other side's rebuttal id
        # or even write a rebuttal against its own argument. Such a record is
        # structurally unusable and must never satisfy a collision checkpoint.
        for owner in (Party.A, Party.B):
            own_argument_ids = {
                item.argument_id
                for item in await self.store.list_arguments(session.session_id, owner)
            }
            for rebuttal in await self.store.list_rebuttals(session.session_id, owner):
                if (
                    rebuttal.target_argument_id in own_argument_ids
                    and rebuttal.status is not RebuttalStatus.WITHDRAWN
                ):
                    rebuttal.status = RebuttalStatus.WITHDRAWN
                    await self.store.save_rebuttal(
                        rebuttal, session.session_id, owner
                    )
                    changed = True
        # A prior recovery bug could erase phase markers when later-stage map
        # tasks became active. Reconstruct only passes with durable conclusion
        # mutations and a model-owned plan for the same phase.
        historical: dict[str, set[str]] = {
            "expansion": set(), "collision": set(), "continuous": set()
        }
        last_plan_phase: dict[str, str] = {}
        for item in sorted(
            await self.store.list_mutations(session.session_id),
            key=lambda mutation: mutation.seq,
        ):
            if item.action is EngineAction.UPDATE_PLAN:
                phase = str(item.payload.get("phase", ""))
                if phase in historical:
                    last_plan_phase[item.agent.value] = phase
            elif item.action is EngineAction.CONCLUDE_PASS:
                phase = last_plan_phase.get(item.agent.value, "")
                if phase in historical:
                    historical[phase].add(item.agent.value)
        recorded_expansion = list(dict.fromkeys(
            session.phase_progress.get("expansion", [])
            + sorted(historical["expansion"])
        ))
        if recorded_expansion != session.phase_progress.get("expansion", []):
            changed = True
        valid_expansion = []
        for value in recorded_expansion:
            try:
                agent = Party(value)
            except ValueError:
                changed = True
                continue
            if await self._expansion_checkpoint_intact(session, agent):
                valid_expansion.append(value)
            else:
                changed = True
        if valid_expansion:
            session.phase_progress["expansion"] = valid_expansion
        else:
            session.phase_progress.pop("expansion", None)

        if set(valid_expansion) != {Party.A.value, Party.B.value}:
            if session.phase_progress.pop("collision", None) is not None:
                changed = True
            for key in list(session.phase_progress):
                if key.startswith("continuous:"):
                    session.phase_progress.pop(key, None)
                    changed = True
            if session.status is not SessionStatus.CREATED:
                session.status = SessionStatus.CREATED
                changed = True
        else:
            recorded_collision = list(dict.fromkeys(
                session.phase_progress.get("collision", [])
                + sorted(historical["collision"])
            ))
            if recorded_collision != session.phase_progress.get("collision", []):
                changed = True
            valid_collision = []
            for value in recorded_collision:
                try:
                    agent = Party(value)
                except ValueError:
                    changed = True
                    continue
                rebuttals = await self.store.list_rebuttals(session.session_id, agent)
                complete = [
                    item for item in rebuttals
                    if not item.missing_fields()
                    and item.status.value not in {"withdrawn", "answered"}
                ]
                opponent = _other(agent)
                live_targets = {
                    item.argument_id
                    for item in await self.store.list_arguments(
                        session.session_id, opponent
                    )
                    if item.status.value != "withdrawn"
                }
                covered_targets = {
                    item.target_argument_id
                    for item in complete
                }
                if (
                    len(complete) >= session.budget.min_rebuttals_per_agent
                    and live_targets <= covered_targets
                ):
                    valid_collision.append(value)
                else:
                    changed = True
            if valid_collision:
                session.phase_progress["collision"] = valid_collision
            else:
                session.phase_progress.pop("collision", None)
            if set(valid_collision) != {Party.A.value, Party.B.value}:
                for key in list(session.phase_progress):
                    if key.startswith("continuous:") and not historical["continuous"]:
                        session.phase_progress.pop(key, None)
                        changed = True
            if (
                recorded_collision
                and set(valid_collision) != {Party.A.value, Party.B.value}
                and session.status is not SessionStatus.CREATED
            ):
                session.status = SessionStatus.CREATED
                changed = True
            if session.current_cycle == 0 and historical["continuous"]:
                restored = list(dict.fromkeys(
                    session.phase_progress.get("continuous:0", [])
                    + sorted(historical["continuous"])
                ))
                if restored != session.phase_progress.get("continuous:0", []):
                    session.phase_progress["continuous:0"] = restored
                    changed = True
                if (
                    set(valid_collision) == {Party.A.value, Party.B.value}
                    and session.status is SessionStatus.CREATED
                ):
                    session.status = SessionStatus.CONTINUOUS
                    changed = True
        if changed:
            session.updated_at = now_iso()
            await self.store.save_session(session)
            self._progress(
                "recovery",
                "检测到旧版不完整检查点，已恢复为未完成阶段",
            )

    # ------------------------------------------------------------------ phases

    async def _run_parallel_phase(
        self,
        session: ResearchSession,
        passes: list[tuple[Party, int]],
        mode: str,
        checkpoint_key: str,
    ) -> None:
        """Let each position finish or fail independently before surfacing errors."""

        results = await asyncio.gather(*[
            self._run_and_checkpoint(session, agent, pass_no, mode, checkpoint_key)
            for agent, pass_no in passes
        ], return_exceptions=True)
        errors = [result for result in results if isinstance(result, BaseException)]
        if errors:
            # Checkpoints from successful siblings are already durable. Preserve
            # the original exception type so the host can render a useful error.
            raise errors[0]

    async def _do_expansion(self, session: ResearchSession) -> None:
        completed = set(session.phase_progress.get("expansion", []))
        pending = [agent for agent in (Party.A, Party.B) if agent.value not in completed]
        passes = [(agent, self._next_pass_no()) for agent in pending]
        await self._run_parallel_phase(session, passes, "expansion", "expansion")

    async def _do_collision(self, session: ResearchSession) -> None:
        completed = set(session.phase_progress.get("collision", []))
        pending = [agent for agent in (Party.A, Party.B) if agent.value not in completed]
        passes = [(agent, self._next_pass_no()) for agent in pending]
        await self._run_parallel_phase(session, passes, "collision", "collision")

    async def _do_cycle(self, session: ResearchSession) -> None:
        first = session.next_agent
        second = _other(first)
        checkpoint_key = f"continuous:{session.current_cycle}"
        completed = set(session.phase_progress.get(checkpoint_key, []))
        for agent in (first, second):
            if agent.value not in completed:
                await self._run_and_checkpoint(
                    session, agent, self._next_pass_no(), "continuous", checkpoint_key
                )
        session.next_agent = second
        session.current_cycle += 1

    async def _ask_stability(self, session: ResearchSession, agent: Party) -> dict:
        messages = [
            {
                "role": "system",
                "content": self.prompt_builder(
                    "stability_check", agent, session.question, session.position_for(agent)
                ),
            },
            {"role": "user", "content": await self._build_context(session, agent, "stability_check")},
        ]
        model = self.llm if agent is Party.A else self.llm_b
        turn = await model.run(messages, [stability_tool_schema()])
        for tc in turn.tool_calls:
            if _canonical_tool_name(tc.name, {"answer_stability"}) == "answer_stability":
                return tc.arguments
        # An absent structured answer is not evidence of stability. Re-open the
        # case so a protocol/model failure can never certify incomplete research.
        return {
            "has_direction": True,
            "direction": "Stability audit did not return a structured answer; repeat it.",
        }

    async def _do_stability_check(self, session: ResearchSession) -> bool:
        has_direction = False
        pass_no = self._next_pass_no()
        for agent in session.agents:
            answer = await self._ask_stability(session, agent)
            if answer.get("has_direction"):
                has_direction = True
                await apply_action(
                    self.store, self.log, EngineAction.UPDATE_MAP, agent, pass_no,
                    {
                        "title": answer.get("direction", ""),
                        "status": "active",
                        "importance": "high",
                        "what_changed": "reopened from stability check",
                    },
                )
        return has_direction

    # ------------------------------------------------------------------ main

    async def run(self, session_id: str) -> ResearchSession:
        session = await self.store.load_session(session_id)
        if session is None:
            raise KeyError(f"unknown session {session_id}")
        await self._repair_phase_progress(session)
        self.log = MutationLog(self.store, session_id)
        existing_mutations = await self.log.list()
        self._pass_no = max((item.pass_no for item in existing_mutations), default=0)

        while True:
            status = session.status
            if status == SessionStatus.CREATED:
                self._progress("expansion", "双方正在独立展开深度研究与立论")
                await self._do_expansion(session)
                self._progress("collision", "双方正在交叉核验并形成基础驳论")
                await self._do_collision(session)
                session.status = SessionStatus.CONTINUOUS
            elif status == SessionStatus.CONTINUOUS:
                self._progress("continuous", "正在根据对方攻击修复当前论证")
                await self._do_cycle(session)
                mutations = await self.log.list()
                maxed_out = (
                    session.budget.max_cycles is not None
                    and session.current_cycle >= session.budget.max_cycles
                )
                if await evaluate_candidate_stable(self.store, session, mutations):
                    session.status = SessionStatus.CANDIDATE_STABLE
                elif maxed_out:
                    # A safety ceiling means "incomplete, needs review", never
                    # "research is stable". Quality gates must not be bypassed by
                    # exhausting compute.
                    session.status = SessionStatus.HUMAN_REVIEW
            elif status == SessionStatus.CANDIDATE_STABLE:
                self._progress("stability", "正在进行最终稳定性审计")
                if await self._do_stability_check(session):
                    session.status = SessionStatus.CONTINUOUS
                else:
                    session.status = SessionStatus.STABLE_FOR_REVIEW
            else:
                break

            session.updated_at = now_iso()
            await self.store.save_session(session)

        return session
