import json
import gzip
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from cre.adapters.web_search import DuckDuckGoSearch


class TestStructuredSourceAdapters(unittest.TestCase):
    def test_gb18030_search_page_is_not_stored_as_mojibake(self):
        page = '<meta charset="gbk"><h3>爱情是不是人类的必需品</h3>'.encode("gb18030")
        decoded = DuckDuckGoSearch._decode_html(page)
        self.assertIn("爱情是不是人类的必需品", decoded)
        self.assertNotIn("\ufffd", decoded)

    def test_gzip_transport_is_decoded_before_html_parsing(self):
        html_body = "<html><body><p>可读的辩论正文</p></body></html>".encode()
        decoded = DuckDuckGoSearch._decode_transport(gzip.compress(html_body), "gzip")
        self.assertEqual(decoded, html_body)

    def test_binary_or_mojibake_page_is_rejected(self):
        adapter = DuckDuckGoSearch()
        adapter._get = lambda url: (("\ufffd\x01" * 500).encode("utf-8"), "text/html")
        document = adapter._read_sync("https://example.com/broken")
        self.assertTrue(document.metadata.get("read_error"))
        self.assertEqual(document.metadata.get("text_quality"), "binary_or_mojibake")

    def test_wikipedia_search_and_read_use_mediawiki_api(self):
        adapter = DuckDuckGoSearch()

        def fake_get(url):
            if "list=search" in url:
                return json.dumps({
                    "query": {"search": [{
                        "title": "死刑",
                        "snippet": "一种刑罚制度",
                        "wordcount": 5000,
                    }]}
                }).encode(), "application/json"
            self.assertIn("prop=extracts", url)
            return json.dumps({
                "query": {"pages": [{"title": "死刑", "extract": "可稳定读取的正文。" * 80}]}
            }).encode(), "application/json"

        adapter._get = fake_get
        results = adapter._wikipedia_search("死刑", 5, "zh")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].metadata["access_tier"], "structured_api")
        document = adapter._read_sync(results[0].url)
        self.assertIn("可稳定读取的正文", document.content)
        self.assertEqual(document.metadata["structured_reader"], "mediawiki")

    def test_pubmed_search_and_read_use_eutilities(self):
        adapter = DuckDuckGoSearch()

        def fake_get(url):
            if "esearch.fcgi" in url:
                return json.dumps({"esearchresult": {"idlist": ["123"]}}).encode(), "application/json"
            if "esummary.fcgi" in url:
                return json.dumps({"result": {"123": {
                    "title": "A clinical study",
                    "authors": [{"name": "Li A"}],
                    "pubdate": "2024",
                    "fulljournalname": "Example Journal",
                }}}).encode(), "application/json"
            self.assertIn("efetch.fcgi", url)
            return b"""<PubmedArticleSet><PubmedArticle><MedlineCitation><Article>
                <ArticleTitle>A clinical study</ArticleTitle>
                <Abstract><AbstractText>Measured outcome and limitations.</AbstractText></Abstract>
                <PublicationTypeList><PublicationType>Randomized Controlled Trial</PublicationType></PublicationTypeList>
                </Article></MedlineCitation></PubmedArticle></PubmedArticleSet>""", "text/xml"

        adapter._get = fake_get
        results = adapter._pubmed_search("clinical treatment", 5)
        self.assertEqual(results[0].url, "https://pubmed.ncbi.nlm.nih.gov/123/")
        document = adapter._read_sync(results[0].url)
        self.assertIn("Measured outcome", document.content)
        self.assertEqual(document.metadata["structured_reader"], "pubmed")

    def test_doi_read_uses_crossref_instead_of_publisher_page(self):
        adapter = DuckDuckGoSearch()

        def fake_get(url):
            self.assertIn("api.crossref.org/works/", url)
            return json.dumps({"message": {
                "title": ["Debate evidence"],
                "author": [{"given": "A", "family": "Scholar"}],
                "container-title": ["Journal"],
                "type": "journal-article",
                "abstract": "<jats:p>A sufficiently detailed inspected abstract.</jats:p>",
            }}).encode(), "application/json"

        adapter._get = fake_get
        document = adapter._read_sync("https://doi.org/10.1000/example")
        self.assertIn("sufficiently detailed", document.content)
        self.assertEqual(document.metadata["structured_reader"], "crossref")


if __name__ == "__main__":
    unittest.main()
