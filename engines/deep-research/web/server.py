"""Local product server for the Continuous Research Engine.

Run from the project root with::

    python web/server.py

It serves the workbench, runs durable background research jobs, calls the two
configured models, searches and reads public sources, and exports clean reports.
"""

from __future__ import annotations

import asyncio
import copy
import json
import mimetypes
import os
import socket
import sys
import threading
import time
import traceback
import uuid
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
STATIC = Path(__file__).resolve().parent / "static"
LOCAL_STATE = Path(__file__).resolve().parent / ".local"
MODEL_CONFIG = LOCAL_STATE / "model_config.json"
MODEL_CATALOG_CACHE = LOCAL_STATE / "model_catalogs.json"
RESEARCH_DIR = LOCAL_STATE / "researches"
JOB_STATE_DIR = LOCAL_STATE / "jobs"
ENGINE_STATE_DIR = LOCAL_STATE / "engine"
TRASH_DIR = LOCAL_STATE / "trash"
MEDIA_CACHE_DIR = LOCAL_STATE / "media_cache"
APP_VERSION = "0.8.2"
JOBS: dict[str, dict] = {}
JOBS_LOCK = threading.Lock()
JOB_FILE_LOCK = threading.Lock()
sys.path.insert(0, str(ROOT / "src"))

from cre.adapters import (  # noqa: E402
    DuckDuckGoSearch, JsonFileStore, LocalASRTranscriber, create_debate_llms,
)
from cre.adapters.in_memory_store import InMemoryStore  # noqa: E402
from cre.engine import (  # noqa: E402
    MutationLog,
    ResearchEngine,
    ResearchRequest,
    Runtime,
    compile_reader_report,
    research_budget,
    project_research as project_engine_state,
)
from cre.models import (  # noqa: E402
    EngineAction,
    Party,
    ResearchBudget,
    ResearchSession,
    SessionStatus,
)
from cre.serialization import to_dict  # noqa: E402
from cre.providers import get_provider, provider_catalog, resolve_protocol  # noqa: E402
from cre.engine.mutation_log import now_iso  # noqa: E402
try:  # package import in tests; local import when launched as ``python web/server.py``
    from web.pdf_report import build_pdf_report  # noqa: E402
except ModuleNotFoundError:  # pragma: no cover - script entry point
    from pdf_report import build_pdf_report  # type: ignore[no-redef]  # noqa: E402


DEFAULT_MODEL_CONFIG = {
    "provider": "openai",
    "base_url": "https://api.openai.com/v1",
    "api_key": "",
    "model_a": "",
    "model_b": "",
    "protocol": "auto",
    "auth_mode": "bearer",
    "query_params": {},
    "timeout_seconds": 120,
}


def load_model_config(path: Path | None = None) -> dict:
    """Load the local server-side model profile without ever exposing it directly."""

    target = path or MODEL_CONFIG
    config = dict(DEFAULT_MODEL_CONFIG)
    if target.is_file():
        try:
            saved = json.loads(target.read_text(encoding="utf-8"))
            if isinstance(saved, dict):
                config.update({key: saved[key] for key in config if key in saved})
        except (OSError, json.JSONDecodeError):
            pass
    if config.get("provider") == "openai-compatible":
        config["provider"] = "generic-chat"
    return config


class TrackingStore(InMemoryStore):
    """Production runtime store with the lightweight status timeline used by UI."""

    def __init__(self) -> None:
        super().__init__()
        self.timeline: list[tuple[str, str, int, str]] = []

    async def save_session(self, session: ResearchSession) -> None:
        self.timeline.append(
            (now_iso(), session.status.value, session.current_cycle, session.next_agent.value)
        )
        await super().save_session(session)


def public_model_config(config: dict) -> dict:
    key = str(config.get("api_key", ""))
    return {
        "provider": config.get("provider", DEFAULT_MODEL_CONFIG["provider"]),
        "base_url": config.get("base_url", DEFAULT_MODEL_CONFIG["base_url"]),
        "model_a": config.get("model_a", ""),
        "model_b": config.get("model_b", ""),
        "protocol": config.get("protocol", "auto"),
        "auth_mode": config.get("auth_mode", "bearer"),
        "timeout_seconds": config.get("timeout_seconds", 120),
        "has_api_key": bool(key),
        "api_key_hint": f"••••{key[-4:]}" if key else "",
        "ready": bool(
            config.get("model_a") and config.get("model_b")
            and (key or config.get("auth_mode") == "none")
        ),
    }


def validate_model_config(payload: dict, existing: dict | None = None) -> dict:
    current = existing or DEFAULT_MODEL_CONFIG
    provider_id = str(payload.get("provider", current.get("provider", "openai"))).strip()
    if provider_id == "openai-compatible":  # migrate the first preview's config
        provider_id = "generic-chat"
    try:
        provider = get_provider(provider_id)
    except KeyError as exc:
        raise ValueError("请选择受支持的模型供应商。") from exc
    base_url = str(payload.get("base_url", current.get("base_url", ""))).strip().rstrip("/")
    parsed = urlparse(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("API 地址必须是完整的 http:// 或 https:// 地址。")
    if parsed.username or parsed.password:
        raise ValueError("请不要把账号或密码写进 API 地址。")

    submitted_key = str(payload.get("api_key", "")).strip()
    same_provider = provider_id == current.get("provider")
    api_key = submitted_key or (str(current.get("api_key", "")) if same_provider else "")
    model_a = str(payload.get("model_a", current.get("model_a", ""))).strip()
    model_b = str(payload.get("model_b", current.get("model_b", ""))).strip()
    protocol = str(payload.get("protocol", "auto")).strip()
    allowed_protocols = {"auto", "openai_responses", "openai_chat", "anthropic_messages"}
    if protocol not in allowed_protocols:
        raise ValueError("接口协议无效。")
    auth_mode = provider["auth_mode"]
    try:
        timeout = int(payload.get("timeout_seconds", current.get("timeout_seconds", 120)))
    except (TypeError, ValueError) as exc:
        raise ValueError("超时时间必须是整数秒。") from exc
    if not 10 <= timeout <= 600:
        raise ValueError("超时时间应在 10–600 秒之间。")

    return {
        "provider": provider_id,
        "base_url": base_url,
        "api_key": api_key,
        "model_a": model_a,
        "model_b": model_b,
        "protocol": protocol,
        "auth_mode": auth_mode,
        "query_params": provider.get("query_params", {}),
        "timeout_seconds": timeout,
    }


def save_model_config(config: dict, path: Path | None = None) -> None:
    target = path or MODEL_CONFIG
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    temporary.replace(target)


def load_model_catalogs() -> dict:
    try:
        value = json.loads(MODEL_CATALOG_CACHE.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def save_model_catalog(provider_id: str, base_url: str, models: list[str]) -> None:
    catalogs = load_model_catalogs()
    catalogs[provider_id] = {
        "base_url": base_url,
        "models": models,
        "updated_at": now_iso(),
    }
    MODEL_CATALOG_CACHE.parent.mkdir(parents=True, exist_ok=True)
    temporary = MODEL_CATALOG_CACHE.with_suffix(".tmp")
    temporary.write_text(json.dumps(catalogs, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(MODEL_CATALOG_CACHE)


def provider_catalog_with_cache() -> list[dict]:
    catalog = provider_catalog()
    cached = load_model_catalogs()
    for provider in catalog:
        entry = cached.get(provider["id"])
        if isinstance(entry, dict) and isinstance(entry.get("models"), list):
            provider["models"] = [str(model) for model in entry["models"] if model]
            provider["catalog_updated_at"] = entry.get("updated_at", "")
    return catalog


def test_model_connection(config: dict) -> dict:
    """Validate credentials through the provider's model-list endpoint.

    This avoids generating tokens or invoking either debate model merely to test
    configuration. OpenAI-compatible gateways normally expose the same endpoint.
    """

    if not config.get("api_key") and config.get("auth_mode") != "none":
        raise ValueError("请先填写 API 密钥。")
    if not config.get("model_a") or not config.get("model_b"):
        raise ValueError("请同时填写 A 方和 B 方的模型 ID。")

    headers = {"User-Agent": f"Continuous-Research-Engine/{APP_VERSION}"}
    if config.get("auth_mode") == "bearer" and config.get("api_key"):
        headers["Authorization"] = f"Bearer {config['api_key']}"
    elif config.get("auth_mode") == "api-key" and config.get("api_key"):
        headers["api-key"] = config["api_key"]
    elif config.get("auth_mode") == "x-api-key" and config.get("api_key"):
        headers.update({"x-api-key": config["api_key"], "anthropic-version": "2023-06-01"})
    if config.get("provider") == "opencode-go":
        headers["x-opencode-session"] = uuid.uuid4().hex
    models_url = f"{config['base_url']}/models"
    if config.get("query_params"):
        models_url += "?" + urlencode(config["query_params"])
    request = Request(models_url, headers=headers, method="GET")
    result = None
    for attempt in range(3):
        try:
            with urlopen(request, timeout=min(config["timeout_seconds"], 30)) as response:
                result = json.loads(response.read().decode("utf-8"))
            break
        except HTTPError as exc:
            retryable = exc.code in {408, 409, 425, 429, 500, 502, 503, 504, 529}
            if retryable and attempt < 2:
                retry_after = exc.headers.get("Retry-After", "")
                delay = float(retry_after) if retry_after.replace(".", "", 1).isdigit() else 1.5 * (2**attempt)
                time.sleep(min(delay, 15))
                continue
            detail = exc.read().decode("utf-8", errors="replace")[:300]
            raise ValueError(f"连接失败（HTTP {exc.code}）：{detail or exc.reason}") from exc
        except (URLError, TimeoutError, OSError) as exc:
            if attempt < 2:
                time.sleep(1.5 * (2**attempt))
                continue
            raise ValueError(f"无法连接到模型服务：{exc}") from exc
        except json.JSONDecodeError as exc:
            raise ValueError("模型服务返回了无法识别的内容。") from exc

    if isinstance(result, dict) and isinstance(result.get("data"), list):
        raw_models = result["data"]
    elif isinstance(result, dict) and isinstance(result.get("models"), list):
        raw_models = result["models"]
    elif isinstance(result, list):
        raw_models = result
    else:
        raise ValueError("模型服务没有返回可识别的模型列表；请手动填写模型或部署 ID。")
    model_ids = set()
    for item in raw_models:
        if isinstance(item, str):
            model_ids.add(item)
        elif isinstance(item, dict):
            model_id = item.get("id") or item.get("name") or item.get("model")
            if model_id:
                model_ids.add(str(model_id).removeprefix("models/"))
    missing = [
        model for model in (config["model_a"], config["model_b"]) if model not in model_ids
    ]
    sorted_models = sorted(model_ids, key=str.casefold)
    save_model_catalog(str(config["provider"]), str(config["base_url"]), sorted_models)
    return {
        "ok": True,
        "message": (
            f"连接成功，已读取 {len(model_ids)} 个可用模型。"
            if not missing
            else f"连接成功，但模型列表中未找到：{', '.join(missing)}"
        ),
        "available_count": len(model_ids),
        "missing_models": missing,
        "models": sorted_models,
        "protocols": {
            "model_a": resolve_protocol(config["provider"], config["model_a"], config.get("protocol", "auto")),
            "model_b": resolve_protocol(config["provider"], config["model_b"], config.get("protocol", "auto")),
        },
    }


def _pass_label(number: int) -> str:
    if number <= 2:
        return "Pass One · 独立展开"
    if number <= 4:
        return "Pass Two · 交叉校验"
    return f"持续研究 · 第 {(number - 3) // 2} 轮"


async def build_demo() -> dict:
    # Kept only as an importable developer fixture; the product has no demo route.
    from examples.pioneer_test import MockSearch, PioneerLLM, QUESTION

    store = TrackingStore()
    session_id = f"preview-{uuid.uuid4().hex[:8]}"
    session = ResearchSession(
        session_id=session_id,
        question=QUESTION,
        position_a="表情包丰富了我们的表达",
        position_b="表情包虚泛了我们的表达",
        status=SessionStatus.CREATED,
        budget=ResearchBudget(
            argument_first_gate=False,
            min_sources_per_agent=0,
            min_examined_sources_per_agent=0,
            min_core_arguments_per_agent=0,
            min_rebuttals_per_agent=0,
            max_cycles=2,
        ),
    )
    await store.save_session(session)
    await Runtime(store=store, llm=PioneerLLM(), search=MockSearch()).run(
        session_id
    )
    result = await project_engine_state(store, session_id, mode="demo")
    result["mode_note"] = "内置案例：引擎与状态流真实运行，模型判断与搜索材料为固定演示数据。"
    return result


async def project_research(store, session_id: str, mode: str = "live") -> dict:
    """Compatibility wrapper around the engine-owned output contract."""
    return await project_engine_state(store, session_id, mode=mode)


def _research_path(session_id: str) -> Path:
    return RESEARCH_DIR / f"{session_id}.json"


def _save_research(result: dict) -> None:
    RESEARCH_DIR.mkdir(parents=True, exist_ok=True)
    target = _research_path(result["session"]["session_id"])
    temporary = target.with_suffix(".tmp")
    temporary.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
    temporary.replace(target)


def _load_research(session_id: str) -> dict | None:
    target = _research_path(session_id)
    if not target.is_file():
        return None
    try:
        value = json.loads(target.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else None
    except (OSError, json.JSONDecodeError):
        return None


async def rebuild_reader_report(session_id: str) -> dict:
    """Retry only the editorial deliverable without rerunning research."""

    result = _load_research(session_id)
    if result is None:
        raise KeyError(session_id)
    config = load_model_config()
    if not public_model_config(config)["ready"]:
        raise ValueError("请先完成模型 API 配置。")
    llm, _ = create_debate_llms(config)
    reader_report, editorial = await compile_reader_report(result, llm)
    result["reader_report"] = reader_report
    result["editorial"] = editorial
    _save_research(result)
    return result


def _save_job_snapshot(job: dict) -> None:
    """Persist safe task metadata, never model credentials or prompts."""

    # A and B report progress concurrently.  Serialize the atomic temp-file
    # swap so Windows never sees two writers replacing the same .tmp path.
    with JOB_FILE_LOCK:
        JOB_STATE_DIR.mkdir(parents=True, exist_ok=True)
        target = JOB_STATE_DIR / f"{job['id']}.json"
        temporary = target.with_suffix(".tmp")
        temporary.write_text(json.dumps(job, ensure_ascii=False), encoding="utf-8")
        temporary.replace(target)


def _restore_job_snapshots() -> None:
    if not JOB_STATE_DIR.is_dir():
        return
    for path in JOB_STATE_DIR.glob("research-*.json"):
        try:
            job = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(job, dict) or not job.get("id"):
            continue
        if _load_research(str(job["id"])) is not None:
            continue
        if job.get("status") in {"queued", "running"}:
            resumable = (ENGINE_STATE_DIR / str(job["id"]) / "state.json").is_file()
            job.update({
                "status": "failed",
                "phase": "failed",
                "message": "上次研究被程序关闭中断",
                "error": (
                    "研究运行时服务被关闭；已经完成的阶段已保存，可从检查点继续。"
                    if resumable
                    else "研究运行时服务被关闭，未发现可恢复的检查点。"
                ),
                "resumable": resumable,
                "updated_at": now_iso(),
                "sort_time": time.time(),
            })
            _save_job_snapshot(job)
        elif "HTTP Error 402" in str(job.get("error", "")):
            job["error"] = (
                "DeepSeek 官方 API 在生成开始前返回 HTTP 402（需要付费）。"
                "请检查当前 API Key 所属账户的余额与模型计费权限，"
                "或切换到有额度的供应商/模型后从检查点继续。"
            )
            job["error_code"] = "provider_payment_required"
            job["message"] = "模型供应商拒绝计费请求"
            _save_job_snapshot(job)
        elif "WinError 10013" in str(job.get("error", "")):
            job["error"] = "此前的研究服务受到 Windows 网络权限限制。启动器已经修复，请直接重新发起该辩题。"
            job["message"] = "旧启动环境导致研究中断"
            _save_job_snapshot(job)
        JOBS[str(job["id"])] = job


def list_researches() -> list[dict]:
    items: dict[str, dict] = {}
    if RESEARCH_DIR.is_dir():
        for path in RESEARCH_DIR.glob("*.json"):
            result = _load_research(path.stem)
            if not result:
                continue
            session = result.get("session") or {}
            items[path.stem] = {"id": path.stem, "question": session.get("question", ""), "status": "complete", "updated_at": session.get("updated_at", ""), "sort_time": path.stat().st_mtime, "metrics": result.get("metrics", {})}
    with JOBS_LOCK:
        for session_id, job in JOBS.items():
            if job.get("status") in {"queued", "running", "failed"}:
                items[session_id] = {key: job.get(key) for key in (
                    "id", "question", "status", "updated_at", "sort_time", "phase",
                    "message", "error", "resumable", "provider", "model_a", "model_b",
                )}
    ordered = sorted(items.values(), key=lambda item: float(item.get("sort_time", 0)), reverse=True)
    for item in ordered:
        item.pop("sort_time", None)
    return ordered


def _move_record_to_trash(path: Path, session_id: str, category: str) -> bool:
    """Move a local history file out of the active index without destroying it."""

    if not path.is_file():
        return False
    destination_dir = TRASH_DIR / f"{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"
    destination_dir.mkdir(parents=True, exist_ok=True)
    path.replace(destination_dir / f"{session_id}.{category}.json")
    return True


def delete_research_record(session_id: str) -> dict:
    if not session_id.startswith("research-"):
        raise KeyError(session_id)
    with JOBS_LOCK:
        job = dict(JOBS.get(session_id, {}))
    if job.get("status") in {"queued", "running"}:
        raise RuntimeError("正在运行的研究不能删除；请等待其结束。")

    moved = False
    moved |= _move_record_to_trash(_research_path(session_id), session_id, "research")
    moved |= _move_record_to_trash(JOB_STATE_DIR / f"{session_id}.json", session_id, "job")
    engine_state = ENGINE_STATE_DIR / session_id
    if engine_state.is_dir():
        destination_dir = TRASH_DIR / f"{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"
        destination_dir.mkdir(parents=True, exist_ok=True)
        engine_state.replace(destination_dir / f"{session_id}.engine")
        moved = True
    with JOBS_LOCK:
        existed_in_memory = JOBS.pop(session_id, None) is not None
    if not moved and not existed_in_memory:
        raise KeyError(session_id)
    return {"ok": True, "id": session_id, "recoverable": moved}


def delete_failed_researches() -> dict:
    with JOBS_LOCK:
        failed_ids = [
            session_id for session_id, job in JOBS.items()
            if job.get("status") == "failed"
        ]
    for session_id in failed_ids:
        delete_research_record(session_id)
    return {"ok": True, "deleted": len(failed_ids), "recoverable": True}


def _update_job(session_id: str, **changes) -> None:
    snapshot = None
    event = changes.pop("event", None)
    budget = changes.pop("budget", None)
    with JOBS_LOCK:
        if session_id in JOBS:
            JOBS[session_id].update(changes)
            if isinstance(event, dict):
                item = dict(event)
                item["time"] = now_iso()
                item["seq"] = int(JOBS[session_id].get("event_seq", 0)) + 1
                JOBS[session_id]["event_seq"] = item["seq"]
                events = JOBS[session_id].setdefault("events", [])
                events.append(item)
                # A job snapshot stays lightweight while retaining enough recent
                # detail to diagnose waste and understand the current trajectory.
                del events[:-400]
            if isinstance(budget, dict):
                agent = str(
                    changes.get("agent")
                    or (event.get("agent") if isinstance(event, dict) else "")
                )
                if agent in {"A", "B"}:
                    JOBS[session_id].setdefault("budgets", {})[agent] = dict(budget)
            JOBS[session_id]["updated_at"] = now_iso()
            JOBS[session_id]["sort_time"] = time.time()
            snapshot = copy.deepcopy(JOBS[session_id])
    if snapshot is not None:
        _save_job_snapshot(snapshot)


async def build_live_research(session_id: str, payload: dict, config: dict) -> dict:
    store = JsonFileStore(ENGINE_STATE_DIR / session_id / "state.json")
    question = str(payload["question"]).strip()
    llm_a, llm_b = create_debate_llms(config)
    search = DuckDuckGoSearch(timeout=min(float(config.get("timeout_seconds", 120)), 45))
    engine = ResearchEngine(
        store=store, llm_a=llm_a, llm_b=llm_b, search=search,
        transcriber=LocalASRTranscriber(
            model_size="large-v3", cache_dir=MEDIA_CACHE_DIR
        ),
        progress_callback=lambda update: _update_job(session_id, **update),
    )
    existing_session = await store.load_session(session_id)
    if existing_session is None:
        await engine.create(ResearchRequest(
            session_id=session_id,
            question=question,
            position_a=str(payload.get("position_a", "")),
            position_b=str(payload.get("position_b", "")),
            profile=str(payload.get("depth", "deep")),
        ))
    else:
        # A resumable checkpoint should benefit from corrected budget semantics
        # and current profile ceilings instead of remaining trapped by limits
        # serialized by an older engine version.
        desired_budget = research_budget(str(payload.get("depth", "deep")))
        if existing_session.budget != desired_budget:
            existing_session.budget = desired_budget
            await store.save_session(existing_session)
            _update_job(
                session_id,
                event={
                    "kind": "budget",
                    "title": "检查点预算已迁移",
                    "status": "done",
                    "summary": "沿用全部研究成果，并采用新版分层研究预算与计账规则",
                    "details": [],
                    "agent": "",
                    "pass_no": 0,
                    "phase": "expansion",
                },
            )
    await engine.run(session_id)
    result = await project_research(store, session_id, "live")
    _update_job(
        session_id, phase="reporting", message="研究已完成，正在将成果编辑成可直接阅读的终稿",
        event={
            "kind": "reporting", "title": "终稿编辑", "status": "running",
            "summary": "已隔离运行轨迹与内部标签，正在重写摘要、双方立论、核心交锋与备赛建议",
            "details": [], "agent": "", "pass_no": 0, "phase": "reporting",
        },
    )
    reader_report, editorial = await compile_reader_report(result, llm_a)
    result["reader_report"] = reader_report
    result["editorial"] = editorial
    _update_job(
        session_id,
        event={
            "kind": "reporting", "title": "终稿编辑", "status": "done",
            "summary": "用户报告已完成重组；正文不含对象编号、版本状态、工单或模型运行叙述",
            "details": ["研究原始状态仍完整保留在推演历史中", "PDF 与独立 HTML 将优先使用这份终稿"],
            "agent": "", "pass_no": 0, "phase": "reporting",
        },
    )
    return result


def _research_worker(session_id: str, payload: dict, config: dict) -> None:
    try:
        _update_job(
            session_id, status="running", phase="expansion",
            message="正在建立研究空间并启动双方模型", error="", error_code="",
        )
        result = asyncio.run(build_live_research(session_id, payload, config))
        _save_research(result)
        _update_job(session_id, status="complete", phase="complete", message="研究完成，结果已保存", metrics=result.get("metrics", {}))
    except Exception as exc:
        # Keep the real exception chain in the local log. The browser receives a
        # short diagnosis, while credentials and request payloads are never logged.
        traceback.print_exc()
        detail = str(exc)[:1200]
        error_code = "engine_error"
        if "WinError 10013" in detail:
            error_code = "network_permission_denied"
            detail = (
                "研究服务进程没有获得出站网络访问权限（WinError 10013）。"
                "这通常来自进程运行环境或安全软件策略，并不表示模型额度耗尽。"
                "请从桌面双击“启动论衡.bat”重新启动；若仍复现，再检查安全软件规则。"
            )
        elif "HTTP Error 402" in detail:
            error_code = "provider_payment_required"
            detail = (
                "DeepSeek 官方 API 在生成开始前返回 HTTP 402（需要付费）。"
                "这通常表示当前 API Key 所属账户余额不足、付费额度已经耗尽，"
                "或所选模型没有可用的计费权限。该错误不可通过自动重试解决；"
                "请在 DeepSeek 控制台检查余额与 Key 所属账户，或切换到有额度的供应商/模型后从检查点继续。"
            )
        elif "HTTP Error 429" in detail:
            error_code = "provider_rate_limited"
            detail = "模型供应商在多次自动退避后仍然限流（HTTP 429）。研究没有被伪装成完成；可等待额度窗口恢复，或在模型 API 中切换供应商/模型后重试。"
        elif "Remote end closed" in detail or "IncompleteRead" in detail:
            error_code = "provider_disconnected"
            detail = "模型供应商在多次自动重连后仍主动断开连接。研究没有被伪装成完成；可稍后重试或切换供应商。"
        elif "behavioral early stop" in detail:
            error_code = "trajectory_early_stop"
            detail = (
                "轨迹监控发现模型连续多轮没有增加可用论点、研究任务或有效材料，"
                "因此已在耗尽硬预算前主动暂停。已有成果和检查点均已保存；"
                "这不是伪装完成，也不建议原样继续烧 Token。请在过程面板查看停机前的具体行动。"
            )
        elif "predictive token stop" in detail:
            error_code = "token_reserve_stop"
            detail = (
                "当前阶段剩余 Token 已不足以安全完成下一次模型调用，引擎已提前暂停，"
                "避免单次请求突破预算。已有论点与研究状态均已保存，可调整预算或策略后从检查点继续。"
            )
        elif "before quality gates" in detail:
            error_code = "pass_incomplete"
            detail = (
                "当前 Pass 的外部研究、模型轮次或 Token 额度已经用完，"
                "但尚未满足来源深读、立论或驳论门槛。"
                "已有研究状态已经保存；引擎没有把预算耗尽伪装成阶段完成。"
                "过程面板会显示具体是哪一项达到上限，可以从检查点继续当前阶段。"
            )
        _update_job(
            session_id, status="failed", phase="failed", message="研究未完成",
            error=detail, error_code=error_code,
            resumable=(ENGINE_STATE_DIR / session_id / "state.json").is_file(),
            event={
                "kind": "failure",
                "title": "研究运行中止",
                "status": "error",
                "summary": detail,
                "details": [],
                "agent": "",
                "pass_no": 0,
                "phase": "failed",
            },
        )


def start_research(payload: dict) -> dict:
    question = str(payload.get("question", "")).strip()
    if len(question) < 4:
        raise ValueError("请填写完整辩题。")
    if len(question) > 500:
        raise ValueError("辩题过长，请控制在 500 字以内。")
    if payload.get("depth", "deep") not in {"standard", "deep"}:
        raise ValueError("研究深度无效。")
    config = load_model_config()
    public = public_model_config(config)
    if not public["ready"]:
        raise ValueError("请先在“模型 API”中完成供应商、密钥和双方模型配置。")
    session_id = f"research-{uuid.uuid4().hex[:12]}"
    request_snapshot = {
        "question": question,
        "position_a": str(payload.get("position_a", "")),
        "position_b": str(payload.get("position_b", "")),
        "depth": str(payload.get("depth", "deep")),
    }
    job = {
        "id": session_id, "question": question, "status": "queued",
        "phase": "queued", "message": "等待启动", "updated_at": now_iso(),
        "sort_time": time.time(), "request": request_snapshot,
        "provider": config.get("provider"), "model_a": config.get("model_a"),
        "model_b": config.get("model_b"), "resumable": False,
        "events": [], "event_seq": 0, "budgets": {},
    }
    with JOBS_LOCK:
        JOBS[session_id] = job
    _save_job_snapshot(job)
    threading.Thread(target=_research_worker, args=(session_id, dict(payload), config), daemon=True, name=f"cre-{session_id}").start()
    return dict(job)


def resume_research(session_id: str, options: dict | None = None) -> dict:
    with JOBS_LOCK:
        job = dict(JOBS.get(session_id, {}))
    if not job:
        raise KeyError(session_id)
    if job.get("status") in {"queued", "running"}:
        raise ValueError("该研究仍在运行。")
    if not (ENGINE_STATE_DIR / session_id / "state.json").is_file():
        raise ValueError("这条旧记录没有引擎检查点，只能重新发起研究。")
    raw_payload = job.get("request")
    if not isinstance(raw_payload, dict) or not raw_payload.get("question"):
        raise ValueError("这条旧记录缺少可恢复的研究请求。")
    payload = dict(raw_payload)
    requested_depth = str((options or {}).get("depth", payload.get("depth", "deep")))
    if requested_depth not in {"standard", "deep"}:
        raise ValueError("继续研究的强度无效。")
    payload["depth"] = requested_depth
    config = load_model_config()
    if not public_model_config(config)["ready"]:
        raise ValueError("请先完成模型 API 配置。")
    _update_job(
        session_id, status="queued", phase="queued", message="正在从检查点恢复",
        error="", error_code="", resumable=True, provider=config.get("provider"),
        model_a=config.get("model_a"), model_b=config.get("model_b"),
        request=payload,
    )
    threading.Thread(
        target=_research_worker, args=(session_id, dict(payload), config), daemon=True,
        name=f"cre-resume-{session_id}",
    ).start()
    with JOBS_LOCK:
        return dict(JOBS[session_id])


def _json_bytes(payload: object) -> bytes:
    return json.dumps(payload, ensure_ascii=False).encode("utf-8")


class WorkbenchHandler(BaseHTTPRequestHandler):
    server_version = f"CREWorkbench/{APP_VERSION}"

    def log_message(self, fmt: str, *args: object) -> None:
        print(f"[web] {self.address_string()} - {fmt % args}")

    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self, max_bytes: int = 65_536) -> dict:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as exc:
            raise ValueError("无效的请求长度。") from exc
        if length > max_bytes:
            raise ValueError("设置请求过大。")
        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("请求不是有效的 JSON。") from exc
        if not isinstance(payload, dict):
            raise ValueError("设置请求必须是一个对象。")
        return payload

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path in {"/favicon.ico", "/.well-known/appspecific/com.chrome.devtools.json"}:
            self._send(HTTPStatus.NO_CONTENT, b"", "application/octet-stream")
            return
        if path == "/api/health":
            self._send(HTTPStatus.OK, _json_bytes({"ok": True, "version": APP_VERSION}), "application/json")
            return
        if path == "/api/researches":
            self._send(HTTPStatus.OK, _json_bytes({"items": list_researches()}), "application/json; charset=utf-8")
            return
        if path.startswith("/api/research/"):
            parts = path.strip("/").split("/")
            if len(parts) in {3, 4}:
                session_id = parts[2]
                if not session_id.startswith("research-"):
                    self._send(HTTPStatus.NOT_FOUND, b"not found", "text/plain")
                    return
                if len(parts) == 4 and parts[3] == "status":
                    with JOBS_LOCK:
                        job = dict(JOBS.get(session_id, {}))
                    if not job:
                        result = _load_research(session_id)
                        if result:
                            job = {"id": session_id, "question": result.get("session", {}).get("question", ""), "status": "complete", "phase": "complete", "message": "研究完成", "metrics": result.get("metrics", {})}
                    if not job:
                        self._send(HTTPStatus.NOT_FOUND, _json_bytes({"error": "未找到该研究。"}), "application/json; charset=utf-8")
                    else:
                        self._send(HTTPStatus.OK, _json_bytes(job), "application/json; charset=utf-8")
                    return
                if len(parts) == 3:
                    result = _load_research(session_id)
                    if result is None:
                        self._send(HTTPStatus.NOT_FOUND, _json_bytes({"error": "研究尚未完成或不存在。"}), "application/json; charset=utf-8")
                    else:
                        self._send(HTTPStatus.OK, _json_bytes(result), "application/json; charset=utf-8")
                    return
        if path == "/api/settings/model":
            self._send(
                HTTPStatus.OK,
                _json_bytes(public_model_config(load_model_config())),
                "application/json; charset=utf-8",
            )
            return
        if path == "/api/providers":
            self._send(
                HTTPStatus.OK,
                _json_bytes({"providers": provider_catalog_with_cache(), "preset_count": len(provider_catalog())}),
                "application/json; charset=utf-8",
            )
            return

        relative = "index.html" if path in ("", "/") else path.lstrip("/")
        candidate = (STATIC / relative).resolve()
        try:
            candidate.relative_to(STATIC.resolve())
        except ValueError:
            self._send(HTTPStatus.FORBIDDEN, b"forbidden", "text/plain")
            return
        if not candidate.is_file():
            self._send(HTTPStatus.NOT_FOUND, b"not found", "text/plain")
            return
        content_type = mimetypes.guess_type(candidate.name)[0] or "application/octet-stream"
        if content_type.startswith("text/") or content_type in {
            "application/javascript",
            "application/json",
        }:
            content_type += "; charset=utf-8"
        self._send(HTTPStatus.OK, candidate.read_bytes(), content_type)

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path == "/api/research/run":
            try:
                job = start_research(self._read_json(max_bytes=100_000))
                self._send(HTTPStatus.ACCEPTED, _json_bytes(job), "application/json; charset=utf-8")
            except ValueError as exc:
                self._send(HTTPStatus.BAD_REQUEST, _json_bytes({"ok": False, "error": str(exc)}), "application/json; charset=utf-8")
            return
        if path.startswith("/api/research/") and path.endswith("/resume"):
            parts = path.strip("/").split("/")
            try:
                if len(parts) != 4:
                    raise KeyError(path)
                job = resume_research(parts[2], self._read_json())
                self._send(HTTPStatus.ACCEPTED, _json_bytes(job), "application/json; charset=utf-8")
            except KeyError:
                self._send(HTTPStatus.NOT_FOUND, _json_bytes({"ok": False, "error": "未找到该研究。"}), "application/json; charset=utf-8")
            except ValueError as exc:
                self._send(HTTPStatus.CONFLICT, _json_bytes({"ok": False, "error": str(exc)}), "application/json; charset=utf-8")
            return
        if path.startswith("/api/research/") and path.endswith("/report/rebuild"):
            parts = path.strip("/").split("/")
            try:
                if len(parts) != 5:
                    raise KeyError(path)
                result = asyncio.run(rebuild_reader_report(parts[2]))
                self._send(HTTPStatus.OK, _json_bytes(result), "application/json; charset=utf-8")
            except KeyError:
                self._send(HTTPStatus.NOT_FOUND, _json_bytes({"ok": False, "error": "未找到该研究。"}), "application/json; charset=utf-8")
            except ValueError as exc:
                self._send(HTTPStatus.BAD_REQUEST, _json_bytes({"ok": False, "error": str(exc)}), "application/json; charset=utf-8")
            return
        if path == "/api/shutdown":
            self._send(HTTPStatus.OK, _json_bytes({"ok": True}), "application/json")
            threading.Thread(target=self.server.shutdown, daemon=True).start()
            return
        if path == "/api/report/pdf":
            try:
                payload = self._read_json(max_bytes=20_000_000)
                if not isinstance(payload.get("session"), dict):
                    raise ValueError("报告数据不完整。")
                pdf = build_pdf_report(payload)
                self._send(HTTPStatus.OK, pdf, "application/pdf")
            except ValueError as exc:
                self._send(
                    HTTPStatus.BAD_REQUEST,
                    _json_bytes({"ok": False, "error": str(exc)}),
                    "application/json; charset=utf-8",
                )
            except Exception as exc:  # pragma: no cover - environment/font errors
                self._send(
                    HTTPStatus.INTERNAL_SERVER_ERROR,
                    _json_bytes({"ok": False, "error": f"PDF 生成失败：{exc}"}),
                    "application/json; charset=utf-8",
                )
            return
        if path == "/api/settings/model/test":
            try:
                config = validate_model_config(self._read_json(), load_model_config())
                result = test_model_connection(config)
                self._send(
                    HTTPStatus.OK,
                    _json_bytes(result),
                    "application/json; charset=utf-8",
                )
            except ValueError as exc:
                self._send(
                    HTTPStatus.BAD_REQUEST,
                    _json_bytes({"ok": False, "error": str(exc)}),
                    "application/json; charset=utf-8",
                )
            return
        self._send(HTTPStatus.NOT_FOUND, b"not found", "text/plain")

    def do_PUT(self) -> None:  # noqa: N802
        if urlparse(self.path).path != "/api/settings/model":
            self._send(HTTPStatus.NOT_FOUND, b"not found", "text/plain")
            return
        try:
            config = validate_model_config(self._read_json(), load_model_config())
            save_model_config(config)
            self._send(
                HTTPStatus.OK,
                _json_bytes(public_model_config(config)),
                "application/json; charset=utf-8",
            )
        except ValueError as exc:
            self._send(
                HTTPStatus.BAD_REQUEST,
                _json_bytes({"ok": False, "error": str(exc)}),
                "application/json; charset=utf-8",
            )

    def do_DELETE(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        try:
            if path == "/api/researches/failed":
                result = delete_failed_researches()
            elif path.startswith("/api/research/"):
                parts = path.strip("/").split("/")
                if len(parts) != 3:
                    raise KeyError(path)
                result = delete_research_record(parts[2])
            else:
                raise KeyError(path)
            self._send(
                HTTPStatus.OK,
                _json_bytes(result),
                "application/json; charset=utf-8",
            )
        except RuntimeError as exc:
            self._send(
                HTTPStatus.CONFLICT,
                _json_bytes({"ok": False, "error": str(exc)}),
                "application/json; charset=utf-8",
            )
        except KeyError:
            self._send(
                HTTPStatus.NOT_FOUND,
                _json_bytes({"ok": False, "error": "未找到这条研究记录。"}),
                "application/json; charset=utf-8",
            )


class ExclusiveWorkbenchServer(ThreadingHTTPServer):
    """Bind one local workbench only, even across rapid Windows restarts."""

    allow_reuse_address = False

    def server_bind(self) -> None:
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


def main() -> None:
    host, port = "127.0.0.1", 8765
    server = ExclusiveWorkbenchServer((host, port), WorkbenchHandler)
    _restore_job_snapshots()
    server.daemon_threads = True
    url = f"http://{host}:{port}"
    print(f"CRE research workbench: {url}")
    if os.environ.get("CRE_NO_BROWSER") != "1":
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
