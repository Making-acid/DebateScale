"""Bounded manual probe for one selected debate video."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from cre.adapters import LocalASRTranscriber


async def run(url: str, language: str, max_duration: int, model: str) -> None:
    adapter = LocalASRTranscriber(
        model_size=model,
        cache_dir=ROOT / "web" / ".local" / "media_cache",
    )
    document = await adapter.transcribe(
        url, language=language, max_duration_seconds=max_duration
    )
    output_dir = ROOT / "web" / ".local" / "experiments" / "asr"
    output_dir.mkdir(parents=True, exist_ok=True)
    transcript_path = output_dir / "latest-transcript.txt"
    summary_path = output_dir / "latest-summary.json"
    transcript_path.write_text(document.content, encoding="utf-8")
    summary = {
        **document.metadata,
        "url": url,
        "segments": len(document.segments),
        "characters": len(document.content),
        "transcript_path": str(transcript_path),
    }
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=True, indent=2), flush=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("url")
    parser.add_argument("--language", default="zh")
    parser.add_argument("--max-duration", type=int, default=1800)
    parser.add_argument("--model", default="large-v3")
    args = parser.parse_args()
    asyncio.run(run(args.url, args.language, args.max_duration, args.model))


if __name__ == "__main__":
    main()
