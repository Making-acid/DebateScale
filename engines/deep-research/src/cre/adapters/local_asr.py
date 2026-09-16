"""Subtitle-first local ASR adapter.

Heavy dependencies are optional. Importing CRE never imports yt-dlp or
faster-whisper; they are loaded only when a selected video is transcribed.
"""

from __future__ import annotations

import asyncio
import ctypes
import hashlib
import html
import os
import re
import tempfile
import sys
from contextlib import nullcontext
from pathlib import Path
from urllib.parse import urlparse, urlunparse
from urllib.request import Request, urlopen

from ..ports.transcription import TranscriptDocument, TranscriptSegment


_TIME = re.compile(
    r"(?:(?P<h>\d+):)?(?P<m>\d{2}):(?P<s>\d{2}(?:[.,]\d+)?)"
)


def _seconds(value: str) -> float:
    match = _TIME.fullmatch(value.strip())
    if not match:
        return 0.0
    return (
        int(match.group("h") or 0) * 3600
        + int(match.group("m")) * 60
        + float(match.group("s").replace(",", "."))
    )


def _clean_caption(value: str) -> str:
    value = re.sub(r"<[^>]+>", "", value)
    value = html.unescape(value).replace("\u200b", "").strip()
    return re.sub(r"\s+", " ", value)


def parse_webvtt(value: str) -> list[TranscriptSegment]:
    """Parse ordinary VTT and de-duplicate rolling auto-caption cues."""

    blocks = re.split(r"\r?\n\s*\r?\n", value.replace("\ufeff", ""))
    parsed: list[TranscriptSegment] = []
    for block in blocks:
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        timing_index = next((i for i, line in enumerate(lines) if "-->" in line), -1)
        if timing_index < 0:
            continue
        timing = lines[timing_index].split("-->", 1)
        start_token = timing[0].strip().split()[0]
        end_token = timing[1].strip().split()[0]
        text = _clean_caption(" ".join(lines[timing_index + 1 :]))
        if not text:
            continue
        if parsed and text == parsed[-1].text:
            continue
        parsed.append(TranscriptSegment(_seconds(start_token), _seconds(end_token), text))
    return parsed


def _format_timestamp(seconds: float) -> str:
    total = max(0, int(seconds))
    return f"{total // 3600:02d}:{(total % 3600) // 60:02d}:{total % 60:02d}"


def render_transcript(segments: list[TranscriptSegment]) -> str:
    return "\n".join(
        f"[{_format_timestamp(item.start)}] "
        f"{(item.speaker + ': ') if item.speaker else ''}{item.text}"
        for item in segments
    )


def _sentence_segments(raw_segments: list) -> list[TranscriptSegment]:
    """Turn Whisper's long decoding windows into timestamped argument-sized cues."""

    result: list[TranscriptSegment] = []
    sentence_end = tuple("。！？!?；;")
    for raw in raw_segments:
        words = list(getattr(raw, "words", None) or [])
        if not words:
            text = str(getattr(raw, "text", "")).strip()
            if not text:
                continue
            tokens = [
                item for item in re.split(r"(?<=[，,。！？!?；;])", text) if item.strip()
            ] or [text]
            pieces: list[str] = []
            bucket = ""
            for token in tokens:
                bucket += token
                if len(bucket) >= 48:
                    pieces.append(bucket.strip())
                    bucket = ""
            if bucket.strip():
                pieces.append(bucket.strip())
            duration = max(0.1, float(raw.end) - float(raw.start))
            total_chars = max(1, sum(len(item) for item in pieces))
            consumed = 0
            for piece in pieces:
                start = float(raw.start) + duration * consumed / total_chars
                consumed += len(piece)
                end = float(raw.start) + duration * consumed / total_chars
                result.append(TranscriptSegment(start, end, piece))
            continue
        bucket: list[str] = []
        start = float(words[0].start or raw.start)
        end = start
        for word in words:
            token = str(word.word)
            bucket.append(token)
            end = float(word.end or end)
            text = "".join(bucket).strip()
            if (
                (text.endswith(sentence_end) and len(text) >= 8)
                or (end - start >= 12 and len(text) >= 12)
            ):
                result.append(TranscriptSegment(start, end, re.sub(r"\s+", " ", text)))
                bucket = []
                start = end
        text = "".join(bucket).strip()
        if text:
            result.append(TranscriptSegment(start, end, re.sub(r"\s+", " ", text)))
    return result


class LocalASRTranscriber:
    """Use embedded subtitles when possible and Whisper only when necessary."""

    def __init__(
        self,
        *,
        model_size: str = "large-v3",
        cpu_fallback_model_size: str = "medium",
        device: str = "auto",
        compute_type: str = "int8_float16",
        timeout: float = 45.0,
        cache_dir: str | Path | None = None,
    ) -> None:
        self.model_size = model_size
        self.cpu_fallback_model_size = cpu_fallback_model_size
        self.device = device
        self.compute_type = compute_type
        self.timeout = timeout
        self.cache_dir = Path(cache_dir) if cache_dir else None
        self._model = None
        self._model_identity = ""

    @staticmethod
    def supports(url: str) -> bool:
        parsed = urlparse(url)
        return parsed.scheme in {"http", "https"} and bool(parsed.netloc)

    @staticmethod
    def _normalize_media_url(url: str) -> str:
        parsed = urlparse(url)
        if parsed.netloc.casefold() in {"bilibili.com", "www.bilibili.com"}:
            match = re.fullmatch(r"/video/(\d+)/?", parsed.path)
            if match:
                return urlunparse(parsed._replace(path=f"/video/av{match.group(1)}"))
        return url

    @staticmethod
    def _pick_caption(info: dict, language: str) -> tuple[str, str, str]:
        pools = [
            ("publisher_subtitles", info.get("subtitles") or {}),
            ("automatic_captions", info.get("automatic_captions") or {}),
        ]
        wanted = [language, "zh-Hans", "zh-CN", "zh", "en"] if language else [
            "zh-Hans", "zh-CN", "zh", "en"
        ]
        for method, pool in pools:
            keys = list(pool)
            ordered = [key for key in wanted if key and key in pool]
            ordered.extend(key for key in keys if key not in ordered)
            for key in ordered:
                formats = pool.get(key) or []
                candidate = next(
                    (item for item in formats if item.get("ext") in {"vtt", "webvtt"}),
                    None,
                )
                if candidate and candidate.get("url"):
                    return str(candidate["url"]), str(key), method
        return "", "", ""

    def _fetch_caption(self, url: str) -> str:
        request = Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urlopen(request, timeout=self.timeout) as response:
            raw = response.read(8_000_000)
            return raw.decode("utf-8", errors="replace")

    def _load_model(self, *, force_cpu: bool = False):
        # A small number of concurrent range requests is substantially more
        # reliable on Windows networks/firewalls than the Hub's high-throughput
        # default. Respect explicit operator settings.
        os.environ.setdefault("HF_XET_RECONSTRUCT_WRITE_SEQUENTIALLY", "1")
        os.environ.setdefault("HF_XET_NUM_CONCURRENT_RANGE_GETS", "2")
        os.environ.setdefault("HF_HUB_DOWNLOAD_TIMEOUT", "60")
        from faster_whisper import WhisperModel

        if force_cpu:
            identity = f"{self.cpu_fallback_model_size}:cpu:int8"
            if self._model is None or self._model_identity != identity:
                self._model = WhisperModel(
                    self.cpu_fallback_model_size, device="cpu", compute_type="int8"
                )
                self._model_identity = identity
            return self._model
        device = "cuda" if self.device == "auto" else self.device
        compute = self.compute_type if device == "cuda" else "int8"
        identity = f"{self.model_size}:{device}:{compute}"
        if self._model is None or self._model_identity != identity:
            self._model = WhisperModel(self.model_size, device=device, compute_type=compute)
            self._model_identity = identity
        return self._model

    @staticmethod
    def _cuda_runtime_available() -> bool:
        if sys.platform != "win32":
            return True
        try:
            ctypes.WinDLL("cublas64_12.dll")
            ctypes.WinDLL("cudnn64_9.dll")
            return True
        except OSError:
            return False

    def _run(self, url: str, language: str, max_duration_seconds: int) -> TranscriptDocument:
        if not self.supports(url):
            raise ValueError("ASR accepts only HTTP(S) media URLs")
        url = self._normalize_media_url(url)
        try:
            import yt_dlp
        except ImportError as exc:
            raise RuntimeError(
                "ASR optional dependencies are missing; install the project 'asr' extra"
            ) from exc

        common = {"quiet": True, "no_warnings": True, "noplaylist": True}
        with yt_dlp.YoutubeDL(common) as downloader:
            info = downloader.extract_info(url, download=False)
        duration = int(info.get("duration") or 0)
        if duration and duration > max_duration_seconds:
            raise ValueError(
                f"media duration {duration}s exceeds the selected ASR limit "
                f"of {max_duration_seconds}s"
            )

        caption_url, caption_language, caption_method = self._pick_caption(info, language)
        if caption_url:
            try:
                segments = parse_webvtt(self._fetch_caption(caption_url))
            except Exception:
                segments = []
            if segments:
                return TranscriptDocument(
                    content=render_transcript(segments),
                    segments=segments,
                    metadata={
                        "transcript_method": caption_method,
                        "transcript_language": caption_language,
                        "transcript_model": "",
                        "duration_seconds": duration,
                        "speaker_labels": False,
                        "transcript_unreviewed": caption_method == "automatic_captions",
                        "media_title": str(info.get("title") or ""),
                    },
                )

        if self.cache_dir:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
        workspace = (
            nullcontext(str(self.cache_dir)) if self.cache_dir
            else tempfile.TemporaryDirectory(prefix="cre-asr-")
        )
        with workspace as temp:
            cache_key = hashlib.sha256(url.encode("utf-8")).hexdigest()[:20]
            stem = f"audio-{cache_key}" if self.cache_dir else "audio"
            matches = [
                item for item in Path(temp).glob(f"{stem}.*")
                if not item.name.endswith((".part", ".ytdl"))
            ]
            cache_hit = bool(matches)
            if matches:
                filename = matches[0]
            else:
                output = str(Path(temp) / f"{stem}.%(ext)s")
                options = {
                    **common,
                    "format": "bestaudio/best",
                    "outtmpl": output,
                    "overwrites": True,
                }
                with yt_dlp.YoutubeDL(options) as downloader:
                    downloaded = downloader.extract_info(url, download=True)
                    filename = Path(downloader.prepare_filename(downloaded))
            if not filename.exists():
                matches = list(Path(temp).glob(f"{stem}.*"))
                if not matches:
                    raise RuntimeError("media downloader did not produce an audio file")
                filename = matches[0]

            fallback = self.device == "auto" and not self._cuda_runtime_available()
            try:
                model = self._load_model(force_cpu=fallback)
                raw_segments, detected = model.transcribe(
                    str(filename), language=language or None,
                    vad_filter=True, beam_size=5, word_timestamps=False,
                )
                materialized = list(raw_segments)
            except Exception as gpu_error:
                if fallback:
                    raise RuntimeError(f"CPU ASR failed ({gpu_error})") from gpu_error
                if self.device not in {"auto", "cuda"}:
                    raise
                fallback = True
                try:
                    model = self._load_model(force_cpu=True)
                    raw_segments, detected = model.transcribe(
                        str(filename), language=language or None,
                        vad_filter=True, beam_size=5, word_timestamps=False,
                    )
                    materialized = list(raw_segments)
                except Exception as cpu_error:
                    raise RuntimeError(
                        f"GPU ASR failed ({gpu_error}); CPU fallback failed ({cpu_error})"
                    ) from cpu_error
            segments = _sentence_segments(materialized)
            detected_language = str(getattr(detected, "language", "") or language)
            return TranscriptDocument(
                content=render_transcript(segments),
                segments=segments,
                metadata={
                    "transcript_method": "local_asr",
                    "transcript_language": detected_language,
                    "transcript_model": self._model_identity,
                    "duration_seconds": duration,
                    "speaker_labels": False,
                    "transcript_unreviewed": True,
                    "asr_cpu_fallback": fallback,
                    "media_title": str(info.get("title") or ""),
                    "media_cache_hit": cache_hit,
                },
            )

    async def transcribe(
        self, url: str, *, language: str = "", max_duration_seconds: int = 7200
    ) -> TranscriptDocument:
        return await asyncio.to_thread(
            self._run, url, language.strip(), max(60, int(max_duration_seconds))
        )
