"""Small no-LLM diagnostic for the built-in public web search adapter."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from cre.adapters.web_search import DuckDuckGoSearch
from cre.adapters import InMemoryStore
from cre.engine import Runtime


def main() -> None:
    query = sys.argv[1] if len(sys.argv) > 1 else "相信需不需要证明 辩论 立论"
    search = DuckDuckGoSearch()
    if "--combined" in sys.argv:
        results = search._search_sync(query, 20)
        if "--screen" in sys.argv:
            results, rejected = Runtime(
                store=InMemoryStore(), llm=None
            )._screen_search_results(
                results, query=query, purpose=query,
                question="网络舆论对司法公正利大于弊还是弊大于利？",
                position="网络舆论对司法公正弊大于利", limit=10,
                existing_urls=set(), search_mode="fact_verification",
            )
        else:
            rejected = 0
        structured_read = None
        if "--read-first-structured" in sys.argv or "--read-first-fragile" in sys.argv:
            wanted_tier = (
                "fragile_platform" if "--read-first-fragile" in sys.argv
                else "structured_api"
            )
            candidate = next((
                item for item in results
                if item.metadata.get("access_tier") == wanted_tier
            ), None)
            if candidate is not None:
                try:
                    document = search._read_sync(candidate.url)
                    structured_read = {
                        "title": candidate.title,
                        "url": candidate.url,
                        "characters": len(document.content),
                        "reader": document.metadata.get("structured_reader"),
                        "excerpt": document.content[:300],
                    }
                except Exception as exc:
                    structured_read = {"error": f"{type(exc).__name__}: {exc}"}
        print(json.dumps([
            {
                "title": item.title, "url": item.url,
                "provider": item.metadata.get("search_provider"),
                "access_tier": item.metadata.get("access_tier"),
                "readability": item.metadata.get("expected_readability"),
                "snippet": item.snippet[:300],
            }
            for item in results
        ], ensure_ascii=True, indent=2))
        if "--screen" in sys.argv:
            print(json.dumps({"accepted": len(results), "rejected": rejected}))
        if structured_read is not None:
            print(json.dumps({"structured_read": structured_read}, ensure_ascii=True, indent=2))
        return
    output: dict[str, object] = {}
    for name in (
        "_so_html_search",
        "_baidu_html_search",
        "_duckduckgo_search",
        "_bing_rss_search",
        "_google_html_search",
        "_bing_html_search",
        "_yahoo_html_search",
    ):
        try:
            results = getattr(search, name)(query, 8)
            output[name] = [
                {"title": item.title, "url": item.url, "snippet": item.snippet[:300]}
                for item in results
            ]
        except Exception as exc:
            output[name] = {"error": f"{type(exc).__name__}: {exc}"}
    print(json.dumps(output, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
