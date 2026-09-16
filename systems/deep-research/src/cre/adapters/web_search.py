"""No-key web search and document reader for production local runs."""

from __future__ import annotations

import asyncio
import base64
from concurrent.futures import ThreadPoolExecutor, as_completed
import gzip
import http.cookiejar
import html
import json
import re
import xml.etree.ElementTree as ET
import urllib.parse
import urllib.request
import zlib
from html.parser import HTMLParser

from ..ports.search import SearchResult, SourceDocument


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self.ignored = 0

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in {"script", "style", "svg", "noscript", "nav", "footer"}:
            self.ignored += 1
        elif not self.ignored and tag in {"p", "br", "li", "h1", "h2", "h3", "tr"}:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "svg", "noscript", "nav", "footer"} and self.ignored:
            self.ignored -= 1

    def handle_data(self, data: str) -> None:
        if not self.ignored:
            self.parts.append(data)

    def text(self) -> str:
        value = html.unescape(" ".join(self.parts))
        value = re.sub(r"[ \t\f\v]+", " ", value)
        value = re.sub(r"\n\s*\n+", "\n\n", value)
        return value.strip()


class DuckDuckGoSearch:
    """Search DuckDuckGo HTML and read public web pages without another API key."""

    # Public HTML search pages often send non-browser agents into verification
    # or redirect loops. This is only presentation compatibility; the client
    # does not execute scripts, retain cookies, or attempt to bypass a challenge.
    user_agent = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/140.0.0.0 Safari/537.36"
    )

    def __init__(self, timeout: float = 30.0, max_document_chars: int = 80_000):
        self.timeout = timeout
        self.max_document_chars = max_document_chars

    @staticmethod
    def _decode_transport(raw: bytes, content_encoding: str = "") -> bytes:
        encoding = content_encoding.casefold()
        if "gzip" in encoding or raw.startswith(b"\x1f\x8b"):
            return gzip.decompress(raw)
        if "deflate" in encoding:
            try:
                return zlib.decompress(raw)
            except zlib.error:
                return zlib.decompress(raw, -zlib.MAX_WBITS)
        return raw

    def _get(self, url: str) -> tuple[bytes, str]:
        request = urllib.request.Request(
            url,
            headers={"User-Agent": self.user_agent, "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.7"},
        )
        # Some search pages set a routing cookie on the first redirect. Keep a
        # per-request jar so redirects work without retaining browsing state.
        opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar())
        )
        with opener.open(request, timeout=self.timeout) as response:
            raw = response.read(5_000_000)
            content_encoding = (response.headers.get("Content-Encoding") or "").casefold()
            try:
                raw = self._decode_transport(raw, content_encoding)
            except (gzip.BadGzipFile, EOFError, zlib.error):
                # Preserve the response for the caller's text-quality guard;
                # a transport decode failure must never be mistaken for prose.
                pass
            return raw, response.headers.get_content_type()

    @staticmethod
    def _decode_redirect(url: str) -> str:
        parsed = urllib.parse.urlparse(html.unescape(url))
        if "duckduckgo.com" in parsed.netloc:
            target = urllib.parse.parse_qs(parsed.query).get("uddg")
            if target:
                return target[0]
        return html.unescape(url)

    @staticmethod
    def _decode_html(raw: bytes) -> str:
        """Decode Chinese search pages without assuming every provider is UTF-8."""

        head = raw[:4096].decode("ascii", errors="ignore")
        declared = re.search(
            r"charset\s*=\s*['\"]?([a-zA-Z0-9._-]+)", head, re.I
        )
        encodings: list[str] = []
        if declared:
            encodings.append(declared.group(1))
        encodings.extend(["utf-8", "gb18030"])
        best = ""
        best_score = float("inf")
        for encoding in dict.fromkeys(encodings):
            try:
                value = raw.decode(encoding, errors="replace")
            except LookupError:
                continue
            score = value.count("\ufffd") * 20 + sum(
                1 for char in value if ord(char) < 32 and char not in "\r\n\t"
            )
            if score < best_score:
                best, best_score = value, score
        return best

    def _duckduckgo_search(self, query: str, limit: int) -> list[SearchResult]:
        url = "https://html.duckduckgo.com/html/?" + urllib.parse.urlencode({"q": query})
        raw, _ = self._get(url)
        page = self._decode_html(raw)
        pattern = re.compile(
            r'class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>.*?'
            r'class="result__snippet"[^>]*>(.*?)</(?:a|div)>', re.S
        )
        results = []
        for href, title, snippet in pattern.findall(page):
            clean_title = re.sub(r"<[^>]+>", "", html.unescape(title)).strip()
            clean_snippet = re.sub(r"<[^>]+>", "", html.unescape(snippet)).strip()
            target = self._decode_redirect(href)
            if not target.startswith(("http://", "https://")):
                continue
            results.append(SearchResult(title=clean_title, url=target, snippet=clean_snippet, metadata={"search_provider": "duckduckgo"}))
            if len(results) >= limit:
                break
        return results

    def _bing_rss_search(self, query: str, limit: int) -> list[SearchResult]:
        """Fallback endpoint used when DuckDuckGo changes markup or rate-limits."""

        url = "https://www.bing.com/search?" + urllib.parse.urlencode(
            {"q": query, "format": "rss", "mkt": "zh-CN", "cc": "CN"}
        )
        raw, _ = self._get(url)
        root = ET.fromstring(raw)
        results: list[SearchResult] = []
        for item in root.findall(".//item"):
            target = (item.findtext("link") or "").strip()
            if not target.startswith(("http://", "https://")):
                continue
            results.append(
                SearchResult(
                    title=(item.findtext("title") or target).strip(),
                    url=target,
                    snippet=re.sub(r"<[^>]+>", "", item.findtext("description") or "").strip(),
                    metadata={"search_provider": "bing-rss"},
                )
            )
            if len(results) >= limit:
                break
        return results

    def _crossref_search(self, query: str, limit: int) -> list[SearchResult]:
        """Structured scholarly discovery for exact papers and empirical claims."""

        url = "https://api.crossref.org/works?" + urllib.parse.urlencode({
            "query.bibliographic": query,
            "rows": max(5, min(limit, 20)),
            "select": "DOI,title,author,published,container-title,abstract,URL,type",
        })
        raw, _ = self._get(url)
        payload = json.loads(raw.decode("utf-8", errors="replace"))
        results: list[SearchResult] = []
        for item in payload.get("message", {}).get("items", []):
            titles = item.get("title") or []
            title = str(titles[0]).strip() if titles else ""
            if not title:
                continue
            authors = []
            for author in (item.get("author") or [])[:5]:
                authors.append(" ".join(filter(None, (author.get("given"), author.get("family")))))
            date_parts = ((item.get("published") or {}).get("date-parts") or [[]])[0]
            year = str(date_parts[0]) if date_parts else ""
            venue = ", ".join(item.get("container-title") or [])
            abstract = re.sub(r"<[^>]+>", " ", item.get("abstract") or "")
            abstract = re.sub(r"\s+", " ", html.unescape(abstract)).strip()
            snippet = "; ".join(filter(None, (
                ", ".join(filter(None, authors)), year, venue, abstract[:800],
            )))
            doi = str(item.get("DOI") or "").strip()
            target = f"https://doi.org/{doi}" if doi else str(item.get("URL") or "")
            if not target.startswith(("http://", "https://")):
                continue
            results.append(SearchResult(
                title=title,
                url=target,
                snippet=snippet,
                metadata={
                    "search_provider": "crossref",
                    "source_type": str(item.get("type") or "scholarly-work"),
                    "doi": doi,
                    "publication_year": year,
                    "access_tier": "structured_api",
                    "structured_reader": "crossref",
                    "stability_score": 0.95,
                },
            ))
        return results

    def _wikipedia_search(
        self, query: str, limit: int, language: str
    ) -> list[SearchResult]:
        """Stable concept/case discovery through Wikimedia's documented API."""

        host = f"{language}.wikipedia.org"
        url = f"https://{host}/w/api.php?" + urllib.parse.urlencode({
            "action": "query",
            "format": "json",
            "formatversion": 2,
            "list": "search",
            "srsearch": query,
            "srlimit": max(1, min(limit, 10)),
            "srprop": "snippet|wordcount|timestamp",
            "utf8": 1,
        })
        raw, _ = self._get(url)
        payload = json.loads(raw.decode("utf-8", errors="replace"))
        results: list[SearchResult] = []
        for item in payload.get("query", {}).get("search", []):
            title = str(item.get("title") or "").strip()
            if not title:
                continue
            snippet = re.sub(r"<[^>]+>", " ", str(item.get("snippet") or ""))
            snippet = re.sub(r"\s+", " ", html.unescape(snippet)).strip()
            target = f"https://{host}/wiki/" + urllib.parse.quote(
                title.replace(" ", "_"), safe="()_,-"
            )
            results.append(SearchResult(
                title=title,
                url=target,
                snippet=snippet,
                metadata={
                    "search_provider": f"wikipedia-{language}",
                    "source_type": "reference-article",
                    "access_tier": "structured_api",
                    "structured_reader": "mediawiki",
                    "stability_score": 0.98,
                    "is_primary": False,
                },
            ))
        return results

    def _pubmed_search(self, query: str, limit: int) -> list[SearchResult]:
        """Biomedical discovery through NCBI E-utilities, not scraped HTML."""

        common = {"db": "pubmed", "retmode": "json", "tool": "lunheng_engine"}
        search_url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?" + urllib.parse.urlencode({
            **common, "term": query, "retmax": max(1, min(limit, 10)),
        })
        raw, _ = self._get(search_url)
        ids = json.loads(raw.decode("utf-8", errors="replace")).get(
            "esearchresult", {}
        ).get("idlist", [])
        if not ids:
            return []
        summary_url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi?" + urllib.parse.urlencode({
            **common, "id": ",".join(ids), "version": "2.0",
        })
        raw, _ = self._get(summary_url)
        payload = json.loads(raw.decode("utf-8", errors="replace"))
        records = payload.get("result", {})
        results: list[SearchResult] = []
        for pmid in ids:
            item = records.get(str(pmid), {})
            title = str(item.get("title") or "").strip()
            if not title:
                continue
            authors = ", ".join(
                str(author.get("name") or "") for author in (item.get("authors") or [])[:5]
            )
            snippet = "; ".join(filter(None, (
                authors, str(item.get("pubdate") or ""),
                str(item.get("fulljournalname") or item.get("source") or ""),
            )))
            results.append(SearchResult(
                title=title,
                url=f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
                snippet=snippet,
                metadata={
                    "search_provider": "pubmed-eutils",
                    "source_type": "biomedical-record",
                    "access_tier": "structured_api",
                    "structured_reader": "pubmed",
                    "stability_score": 0.98,
                    "pmid": str(pmid),
                },
            ))
        return results

    def _bing_html_search(self, query: str, limit: int) -> list[SearchResult]:
        url = "https://www.bing.com/search?" + urllib.parse.urlencode(
            {"q": query, "count": max(10, limit), "mkt": "zh-CN", "cc": "CN"}
        )
        raw, _ = self._get(url)
        page = self._decode_html(raw)
        results: list[SearchResult] = []
        for block in re.findall(r'<li[^>]+class="[^"]*\bb_algo\b[^"]*".*?</li>', page, re.S | re.I):
            heading = re.search(r'<h2[^>]*>\s*<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', block, re.S | re.I)
            if not heading:
                continue
            target = self._decode_bing_redirect(html.unescape(heading.group(1)))
            if not target.startswith(("http://", "https://")):
                continue
            title = re.sub(r"<[^>]+>", "", html.unescape(heading.group(2))).strip()
            paragraph = re.search(r'<p[^>]*>(.*?)</p>', block, re.S | re.I)
            snippet = re.sub(r"<[^>]+>", "", html.unescape(paragraph.group(1) if paragraph else "")).strip()
            results.append(SearchResult(title=title, url=target, snippet=snippet, metadata={"search_provider": "bing"}))
            if len(results) >= limit:
                break
        return results

    def _baidu_html_search(self, query: str, limit: int) -> list[SearchResult]:
        """Chinese-web discovery fallback, especially useful for debate archives."""

        url = "https://www.baidu.com/s?" + urllib.parse.urlencode({
            "wd": query,
            "rn": max(10, min(limit, 20)),
            "ie": "utf-8",
            "oe": "utf-8",
        })
        raw, _ = self._get(url)
        page = self._decode_html(raw)
        results: list[SearchResult] = []
        seen: set[str] = set()
        blocks = re.findall(
            r'<div[^>]+(?:class="[^"]*\bc-container\b[^"]*"|mu="https?://)[^>]*>.*?'
            r'(?=<div[^>]+(?:class="[^"]*\bc-container\b[^"]*"|id="page")|$)',
            page,
            re.S | re.I,
        )
        for block in blocks:
            heading = re.search(
                r'<h3[^>]*>.*?<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>',
                block,
                re.S | re.I,
            )
            if not heading:
                continue
            target = html.unescape(heading.group(1)).strip()
            if target.startswith("/"):
                target = urllib.parse.urljoin("https://www.baidu.com", target)
            if not target.startswith(("http://", "https://")) or target in seen:
                continue
            seen.add(target)
            title = re.sub(r"<[^>]+>", "", html.unescape(heading.group(2))).strip()
            text = _TextExtractor()
            text.feed(block)
            snippet = text.text()
            if title and snippet.startswith(title):
                snippet = snippet[len(title):].strip()
            results.append(SearchResult(
                title=title or target,
                url=target,
                snippet=snippet[:1000],
                metadata={"search_provider": "baidu"},
            ))
            if len(results) >= limit:
                break
        return results

    def _so_html_search(self, query: str, limit: int) -> list[SearchResult]:
        """Parse 360 Search's compact server-rendered result list."""

        url = "https://www.so.com/s?" + urllib.parse.urlencode({"q": query})
        raw, _ = self._get(url)
        page = self._decode_html(raw)
        results: list[SearchResult] = []
        seen: set[str] = set()
        for block in re.findall(
            r'<li[^>]+class="[^"]*\bres-list\b[^"]*".*?</li>',
            page,
            re.S | re.I,
        ):
            heading = re.search(
                r'<h3[^>]*>\s*<a\s+([^>]*)>(.*?)</a>\s*</h3>',
                block,
                re.S | re.I,
            )
            if not heading:
                continue
            attrs, title_html = heading.groups()
            original = re.search(r'data-mdurl="([^"]+)"', attrs, re.I)
            href = re.search(r'href="([^"]+)"', attrs, re.I)
            target = html.unescape(
                original.group(1) if original else href.group(1) if href else ""
            ).strip()
            if not target.startswith(("http://", "https://")) or target in seen:
                continue
            seen.add(target)
            title = re.sub(r"<[^>]+>", "", html.unescape(title_html)).strip()
            description = re.search(
                r'<p[^>]+class="[^"]*\bres-desc\b[^"]*"[^>]*>(.*?)</p>',
                block,
                re.S | re.I,
            )
            snippet = re.sub(
                r"<[^>]+>", " ", html.unescape(description.group(1) if description else "")
            )
            snippet = re.sub(r"\s+", " ", snippet).strip()
            results.append(SearchResult(
                title=title or target,
                url=target,
                snippet=snippet[:1000],
                metadata={"search_provider": "360-search"},
            ))
            if len(results) >= limit:
                break
        return results

    @staticmethod
    def _decode_bing_redirect(url: str) -> str:
        parsed = urllib.parse.urlparse(html.unescape(url))
        if "bing.com" not in parsed.netloc or not parsed.path.startswith("/ck/"):
            return url
        encoded = urllib.parse.parse_qs(parsed.query).get("u", [""])[0]
        if encoded.startswith("a1"):
            try:
                data = encoded[2:] + "=" * (-len(encoded[2:]) % 4)
                return base64.urlsafe_b64decode(data).decode("utf-8")
            except (ValueError, UnicodeDecodeError):
                pass
        return url

    def _google_html_search(self, query: str, limit: int) -> list[SearchResult]:
        url = "https://www.google.com/search?" + urllib.parse.urlencode(
            {"q": query, "num": max(10, limit), "hl": "zh-CN"}
        )
        raw, _ = self._get(url)
        page = self._decode_html(raw)
        pattern = re.compile(
            r'<a[^>]+href="(?:/url\?q=)?(https?[^"&]+)[^>]*>\s*<h3[^>]*>(.*?)</h3>',
            re.S,
        )
        results: list[SearchResult] = []
        seen: set[str] = set()
        for href, title in pattern.findall(page):
            target = urllib.parse.unquote(html.unescape(href))
            if "google.com/" in target or target in seen:
                continue
            seen.add(target)
            clean_title = re.sub(r"<[^>]+>", "", html.unescape(title)).strip()
            results.append(SearchResult(title=clean_title, url=target, snippet="", metadata={"search_provider": "google"}))
            if len(results) >= limit:
                break
        return results

    @staticmethod
    def _decode_yahoo_redirect(url: str) -> str:
        value = html.unescape(url)
        if "search.yahoo.com" not in urllib.parse.urlparse(value).netloc:
            return value
        match = re.search(r"/RU=([^/]+)(?:/RK=|$)", value)
        return urllib.parse.unquote(match.group(1)) if match else value

    def _yahoo_html_search(self, query: str, limit: int) -> list[SearchResult]:
        url = "https://search.yahoo.com/search?" + urllib.parse.urlencode(
            {"p": query, "n": max(10, limit)}
        )
        raw, _ = self._get(url)
        page = self._decode_html(raw)
        pattern = re.compile(
            r'<div[^>]+class="[^"]*compTitle[^"]*".*?<h3[^>]*>.*?'
            r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>',
            re.S | re.I,
        )
        results: list[SearchResult] = []
        seen: set[str] = set()
        for href, title in pattern.findall(page):
            target = self._decode_yahoo_redirect(href)
            hostname = urllib.parse.urlparse(target).netloc.lower()
            if (
                not target.startswith(("http://", "https://"))
                or target in seen
                or hostname.endswith("yahoo.com")
            ):
                continue
            seen.add(target)
            without_meta = re.sub(r"<span\b.*?</span>", "", title, flags=re.S | re.I)
            clean_title = re.sub(r"<[^>]+>", "", html.unescape(without_meta)).strip()
            if not clean_title:
                continue
            results.append(SearchResult(title=clean_title, url=target, snippet="", metadata={"search_provider": "yahoo"}))
            if len(results) >= limit:
                break
        return results

    def _search_sync(self, query: str, n: int) -> list[SearchResult]:
        limit = max(1, min(n, 20))
        errors = []
        scholarly = bool(re.search(
            r"\b(?:19|20)\d{2}\b|doi|journal|study|meta-analysis|review|"
            r"experiment|dataset|ethnology|psychology|medicine|论文|研究|期刊|元分析",
            query,
            re.I,
        ))
        chinese_query = bool(re.search(r"[\u3400-\u9fff]", query))
        biomedical = bool(re.search(
            r"\b(?:medical|medicine|health|clinical|disease|patient|therapy|"
            r"psychology|psychiatry|randomi[sz]ed|pubmed)\b|"
            r"医学|医疗|健康|疾病|患者|临床|治疗|心理|精神|随机对照|"
            r"安乐死|生命伦理|基因|生物医学",
            query,
            re.I,
        ))
        # Do not let the first public search surface monopolize the candidate
        # pool. Chinese 360 results, for example, often fill a numeric limit
        # with document mirrors while another engine has the court/news page.
        # Query a small diverse portfolio concurrently, then interleave results
        # so the runtime's argument-aware screening can rank across providers.
        searchers = (
            [self._so_html_search, self._duckduckgo_search,
             self._google_html_search, self._bing_html_search,
             lambda q, k: self._wikipedia_search(q, k, "zh")]
            if chinese_query else
            [self._duckduckgo_search, self._google_html_search,
             self._bing_html_search, self._yahoo_html_search,
             lambda q, k: self._wikipedia_search(q, k, "en")]
        )
        if scholarly:
            searchers.insert(0, self._crossref_search)
        if biomedical:
            searchers.insert(0, self._pubmed_search)
        provider_limit = max(5, min(10, (limit + 1) // 2))
        batches: dict[int, list[SearchResult]] = {}
        with ThreadPoolExecutor(max_workers=min(5, len(searchers))) as executor:
            futures = {
                executor.submit(searcher, query, provider_limit): index
                for index, searcher in enumerate(searchers)
            }
            for future in as_completed(futures):
                index = futures[future]
                try:
                    batches[index] = future.result()
                except Exception as exc:  # another public endpoint may still work
                    errors.append(str(exc))

        merged: list[SearchResult] = []
        seen: set[str] = set()
        depth = max((len(items) for items in batches.values()), default=0)
        for offset in range(depth):
            for index in range(len(searchers)):
                results = batches.get(index) or []
                if offset >= len(results):
                    continue
                result = results[offset]
                try:
                    key = result.url.casefold().rstrip("/")
                    if key and key not in seen:
                        seen.add(key)
                        merged.append(result)
                except (AttributeError, TypeError):
                    continue
                if len(merged) >= limit:
                    return merged
        if merged:
            return merged
        if errors:
            raise RuntimeError("公开网页搜索暂时不可用：" + "；".join(errors)[:500])
        return []

    async def search(self, query: str, n: int = 5) -> list[SearchResult]:
        return await asyncio.to_thread(self._search_sync, query, n)

    def _read_wikipedia_api(self, url: str) -> SourceDocument:
        parsed = urllib.parse.urlparse(url)
        title = urllib.parse.unquote(parsed.path.split("/wiki/", 1)[1]).replace("_", " ")
        api_url = f"{parsed.scheme}://{parsed.netloc}/w/api.php?" + urllib.parse.urlencode({
            "action": "query",
            "format": "json",
            "formatversion": 2,
            "prop": "extracts",
            "explaintext": 1,
            "redirects": 1,
            "titles": title,
        })
        raw, content_type = self._get(api_url)
        payload = json.loads(raw.decode("utf-8", errors="replace"))
        pages = payload.get("query", {}).get("pages", [])
        text = str(pages[0].get("extract") or "") if pages else ""
        return SourceDocument(
            content=text[: self.max_document_chars],
            metadata={
                "content_type": content_type,
                "characters_read": min(len(text), self.max_document_chars),
                "access_tier": "structured_api",
                "structured_reader": "mediawiki",
            },
        )

    def _read_crossref_api(self, url: str) -> SourceDocument:
        doi = urllib.parse.unquote(urllib.parse.urlparse(url).path.lstrip("/"))
        api_url = "https://api.crossref.org/works/" + urllib.parse.quote(doi, safe="")
        raw, content_type = self._get(api_url)
        item = json.loads(raw.decode("utf-8", errors="replace")).get("message", {})
        abstract = re.sub(r"<[^>]+>", " ", str(item.get("abstract") or ""))
        abstract = re.sub(r"\s+", " ", html.unescape(abstract)).strip()
        title = " ".join(str(value) for value in (item.get("title") or []))
        authors = ", ".join(
            " ".join(filter(None, (author.get("given"), author.get("family"))))
            for author in (item.get("author") or [])
        )
        text = "\n\n".join(filter(None, (
            f"Title: {title}" if title else "",
            f"Authors: {authors}" if authors else "",
            f"Container: {'; '.join(item.get('container-title') or [])}",
            f"Type: {item.get('type', '')}",
            f"DOI: {doi}",
            f"Abstract: {abstract}" if abstract else "",
        )))
        return SourceDocument(
            content=text[: self.max_document_chars],
            metadata={
                "content_type": content_type,
                "characters_read": min(len(text), self.max_document_chars),
                "access_tier": "structured_api",
                "structured_reader": "crossref",
            },
        )

    def _read_pubmed_api(self, url: str) -> SourceDocument:
        match = re.search(r"pubmed\.ncbi\.nlm\.nih\.gov/(\d+)", url)
        if not match:
            raise ValueError("PubMed URL does not contain a PMID")
        pmid = match.group(1)
        api_url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?" + urllib.parse.urlencode({
            "db": "pubmed", "id": pmid, "retmode": "xml", "tool": "lunheng_engine",
        })
        raw, content_type = self._get(api_url)
        root = ET.fromstring(raw)
        title = " ".join("".join(node.itertext()) for node in root.findall(".//ArticleTitle"))
        abstracts = ["".join(node.itertext()).strip() for node in root.findall(".//AbstractText")]
        publication_types = ["".join(node.itertext()).strip() for node in root.findall(".//PublicationType")]
        mesh_terms = ["".join(node.itertext()).strip() for node in root.findall(".//MeshHeading/DescriptorName")]
        text = "\n\n".join(filter(None, (
            f"Title: {title}" if title else "",
            "Abstract: " + "\n".join(abstracts) if abstracts else "",
            "Publication types: " + "; ".join(publication_types) if publication_types else "",
            "Indexed topics: " + "; ".join(mesh_terms) if mesh_terms else "",
            f"PMID: {pmid}",
        )))
        return SourceDocument(
            content=text[: self.max_document_chars],
            metadata={
                "content_type": content_type,
                "characters_read": min(len(text), self.max_document_chars),
                "access_tier": "structured_api",
                "structured_reader": "pubmed",
            },
        )

    def _read_sync(self, url: str) -> SourceDocument:
        parsed = urllib.parse.urlparse(url)
        if ".wikipedia.org" in parsed.netloc and "/wiki/" in parsed.path:
            return self._read_wikipedia_api(url)
        if parsed.netloc.casefold() == "doi.org" and parsed.path.strip("/"):
            return self._read_crossref_api(url)
        if "pubmed.ncbi.nlm.nih.gov" in parsed.netloc.casefold():
            return self._read_pubmed_api(url)
        raw, content_type = self._get(url)
        if content_type == "application/pdf" or url.lower().split("?", 1)[0].endswith(".pdf"):
            try:
                from io import BytesIO
                from pypdf import PdfReader
                reader = PdfReader(BytesIO(raw))
                text = "\n\n".join((page.extract_text() or "") for page in reader.pages[:120])
            except Exception as exc:
                return SourceDocument(content=f"PDF 无法解析：{exc}", metadata={"content_type": content_type, "read_error": True})
        else:
            encoding_match = re.search(br"charset=[\"']?([\w-]+)", raw[:5000], re.I)
            encoding = encoding_match.group(1).decode("ascii", errors="ignore") if encoding_match else "utf-8"
            page = raw.decode(encoding, errors="replace")
            parser = _TextExtractor()
            parser.feed(page)
            text = parser.text()
        if text:
            sample = text[: min(len(text), 8000)]
            replacement_ratio = sample.count("\ufffd") / max(1, len(sample))
            control_ratio = sum(
                1 for char in sample
                if ord(char) < 32 and char not in "\n\r\t"
            ) / max(1, len(sample))
            if replacement_ratio > 0.03 or control_ratio > 0.01:
                return SourceDocument(
                    content="页面响应不是可读文本，可能仍为压缩或二进制内容。",
                    metadata={
                        "content_type": content_type,
                        "read_error": True,
                        "text_quality": "binary_or_mojibake",
                    },
                )
        return SourceDocument(content=text[: self.max_document_chars], metadata={"content_type": content_type, "characters_read": min(len(text), self.max_document_chars)})

    async def read(self, url: str) -> SourceDocument:
        return await asyncio.to_thread(self._read_sync, url)
