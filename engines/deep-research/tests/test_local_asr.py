import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from cre.adapters import InMemoryStore
from cre.adapters.local_asr import _sentence_segments, parse_webvtt, render_transcript
from cre.engine import Runtime, inspect_capabilities
from cre.models import Party, ResearchSession, Source
from cre.ports.transcription import TranscriptDocument, TranscriptSegment


class NoopLLM:
    async def run(self, messages, tools=None):
        raise AssertionError("not used")


class FakeTranscriber:
    def supports(self, url):
        return url.startswith("https://")

    async def transcribe(self, url, *, language="", max_duration_seconds=7200):
        segments = [
            TranscriptSegment(1.2, 5.0, "自由的边界不是令人舒适。"),
            TranscriptSegment(5.1, 9.0, "而是是否造成了可以说明的伤害。"),
            TranscriptSegment(9.1, 14.0, "这一区分决定了举证责任。"),
            TranscriptSegment(14.1, 20.0, "若反方只证明有人感到不适，还没有证明表达自由应当被剥夺。"),
            TranscriptSegment(20.1, 27.0, "正方仍需承认威胁、骚扰与制度性排斥会跨过伤害边界。"),
        ]
        return TranscriptDocument(
            content=render_transcript(segments), segments=segments,
            metadata={
                "transcript_method": "local_asr", "transcript_language": "zh",
                "speaker_labels": False, "duration_seconds": 14,
            },
        )


class TestSubtitleParsing(unittest.TestCase):
    def test_bilibili_numeric_video_path_is_normalized_for_extractor(self):
        from cre.adapters import LocalASRTranscriber

        self.assertEqual(
            LocalASRTranscriber._normalize_media_url(
                "https://www.bilibili.com/video/1801712256"
            ),
            "https://www.bilibili.com/video/av1801712256",
        )

    def test_vtt_timestamps_and_rolling_duplicate_are_preserved(self):
        value = """WEBVTT

00:00:01.200 --> 00:00:03.000
<c>第一句话</c>

00:00:01.200 --> 00:00:04.000
第一句话

00:01:04.000 --> 00:01:07.000 align:start
第二句话
"""
        segments = parse_webvtt(value)
        self.assertEqual([item.text for item in segments], ["第一句话", "第二句话"])
        self.assertEqual(render_transcript(segments).splitlines()[-1], "[00:01:04] 第二句话")

    def test_whisper_windows_are_split_into_precise_sentence_cues(self):
        class Word:
            def __init__(self, start, end, word):
                self.start, self.end, self.word = start, end, word

        class Raw:
            start, end, text = 0.0, 10.0, "第一句。第二句！"
            words = [
                Word(0, 1, "第一句。"), Word(2, 3, "第二句还没说完"),
                Word(3, 4, "但现在结束！"),
            ]

        cues = _sentence_segments([Raw()])
        self.assertEqual([item.text for item in cues], ["第一句。第二句还没说完但现在结束！"])

    def test_long_window_without_word_timestamps_is_cheaply_interpolated(self):
        class Raw:
            start, end, words = 0.0, 30.0, []
            text = "这是第一部分，" * 8 + "这是结论。"

        cues = _sentence_segments([Raw()])
        self.assertGreater(len(cues), 1)
        self.assertEqual(cues[0].start, 0.0)
        self.assertAlmostEqual(cues[-1].end, 30.0)


class TestRuntimeTranscription(unittest.IsolatedAsyncioTestCase):
    async def test_transcript_becomes_inspected_timestamped_material(self):
        store = InMemoryStore()
        session = ResearchSession(
            session_id="asr", question="人有没有表达偏见的自由",
            position_a="有", position_b="没有",
        )
        await store.save_session(session)
        source = Source(
            source_id="src_video", url="https://video.example/debate",
            title="比赛片段", content="搜索摘要",
            metadata={"content_access": "lead_only"}, discovered_by=Party.A,
        )
        await store.save_source(source, session.session_id)
        runtime = Runtime(store=store, llm=NoopLLM(), transcriber=FakeTranscriber())
        result = await runtime._execute_pass_tool(
            session.session_id, Party.A, "transcribe_source",
            {"source_id": "src_video", "purpose": "检验伤害标准", "language": "zh"},
        )
        self.assertIn("speaker_labels=False", result)
        saved = await store.load_source("src_video")
        self.assertEqual(saved.metadata["content_access"], "transcript")
        self.assertEqual(saved.metadata["transcript_segments"], 5)
        self.assertIn("[00:00:01]", saved.content)
        self.assertIn(Party.A, saved.investigated_by)

    async def test_capability_manifest_reports_optional_asr(self):
        caps = inspect_capabilities(InMemoryStore(), None, None, FakeTranscriber())
        self.assertTrue(caps.audio_transcription)
