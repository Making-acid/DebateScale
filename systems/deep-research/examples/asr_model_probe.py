"""Download and load one faster-whisper model without touching media."""

from __future__ import annotations

import argparse
import json
import time

from faster_whisper import WhisperModel


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="tiny")
    args = parser.parse_args()
    started = time.monotonic()
    print(json.dumps({"stage": "starting", "model": args.model}), flush=True)
    WhisperModel(args.model, device="cpu", compute_type="int8")
    print(json.dumps({
        "stage": "loaded", "model": args.model,
        "elapsed_seconds": round(time.monotonic() - started, 1),
    }), flush=True)


if __name__ == "__main__":
    main()
