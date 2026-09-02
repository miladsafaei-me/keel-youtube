"""Unit tests for everything that does not need the network.

Deliberately offline: the parts that talk to YouTube or a model are thin wrappers
around external programs, and pinning them in tests would only pin the wrapper.
What is tested here is where the bugs actually live - parsing, grouping,
timecodes, slugs, and the tolerant JSON reader that every provider depends on.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from unittest import mock

from yt_extract import binaries, frames, ids, prompts, subtitles, transcript
from yt_extract.errors import LLMError, MissingRequirement
from yt_extract.llm.base import parse_json_object


class TestIds(unittest.TestCase):
    def test_every_url_form_yields_the_id(self):
        for url in (
            "https://www.youtube.com/watch?v=7wL2oyebbvU",
            "https://youtu.be/7wL2oyebbvU",
            "https://www.youtube.com/shorts/7wL2oyebbvU",
            "https://www.youtube.com/embed/7wL2oyebbvU",
            "https://www.youtube.com/live/7wL2oyebbvU",
            "https://www.youtube.com/watch?list=PL9&v=7wL2oyebbvU&t=30s",
        ):
            self.assertEqual(ids.video_id(url), "7wL2oyebbvU", url)

    def test_a_non_youtube_string_is_empty_not_an_error(self):
        self.assertEqual(ids.video_id("https://vimeo.com/12345"), "")
        self.assertEqual(ids.video_id(""), "")

    def test_canonical_url(self):
        self.assertEqual(
            ids.canonical_url("https://youtu.be/7wL2oyebbvU?t=90"),
            "https://www.youtube.com/watch?v=7wL2oyebbvU",
        )


class TestSubtitles(unittest.TestCase):
    def test_json3_is_parsed_with_timestamps(self):
        payload = {"events": [
            {"tStartMs": 1500, "segs": [{"utf8": "hello "}, {"utf8": "world"}]},
            {"tStartMs": 4000, "segs": [{"utf8": "second line"}]},
        ]}
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "c.json3"
            path.write_text(json.dumps(payload), encoding="utf-8")
            segments = subtitles.parse(path)
        self.assertEqual([s.start for s in segments], [1.5, 4.0])
        self.assertEqual(segments[0].text, "hello world")

    def test_vtt_is_parsed_with_timestamps(self):
        vtt = (
            "WEBVTT\n\n"
            "00:00:01.500 --> 00:00:03.000\nhello world\n\n"
            "00:01:05.000 --> 00:01:07.000\n<c>second</c> line\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "c.vtt"
            path.write_text(vtt, encoding="utf-8")
            segments = subtitles.parse(path)
        self.assertEqual([s.start for s in segments], [1.5, 65.0])
        self.assertEqual(segments[1].text, "second line")

    def test_rolling_auto_captions_are_deduplicated(self):
        """YouTube's auto-captions restate the previous line; that must not survive."""
        payload = {"events": [
            {"tStartMs": 0, "segs": [{"utf8": "the market opens"}]},
            {"tStartMs": 1000, "segs": [{"utf8": "the market opens at nine thirty"}]},
            {"tStartMs": 2000, "segs": [{"utf8": "the market opens at nine thirty"}]},
            {"tStartMs": 3000, "segs": [{"utf8": "and then it moves"}]},
        ]}
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "c.json3"
            path.write_text(json.dumps(payload), encoding="utf-8")
            segments = subtitles.parse(path)
        self.assertEqual(
            [s.text for s in segments],
            ["the market opens at nine thirty", "and then it moves"],
        )


def _segments(pairs):
    return [subtitles.Segment(start, text) for start, text in pairs]


class TestTranscript(unittest.TestCase):
    def test_timecode_grows_an_hour_field_only_when_needed(self):
        self.assertEqual(transcript.timecode(0), "00:00")
        self.assertEqual(transcript.timecode(75), "01:15")
        self.assertEqual(transcript.timecode(3661), "1:01:01")

    def test_paragraphs_break_on_sentence_end_after_the_target(self):
        segs = _segments([(0, "one."), (10, "two."), (50, "three."), (60, "four.")])
        grouped = transcript.paragraphs(segs, target_seconds=45)
        self.assertEqual(len(grouped), 2)
        self.assertEqual(grouped[0][0], 0)
        self.assertIn("three.", grouped[0][1])

    def test_thin_index_downsamples(self):
        segs = _segments([(i * 5, f"line {i}") for i in range(20)])
        lines = transcript.thin_index(segs, every_seconds=30).splitlines()
        self.assertEqual(len(lines), 4)
        self.assertTrue(lines[0].startswith("[00:00] "))

    def test_a_screenshot_follows_the_paragraph_that_covers_its_second(self):
        """The image must come after the words that explain it, not before.

        Both lines here land in one long paragraph starting at 0, which is the
        case a naive "before the next paragraph" rule gets wrong.
        """
        segs = _segments([(0, "intro."), (100, "the chart."), (200, "the end.")])
        md = transcript.render_markdown(
            {"title": "T", "url": "u", "duration_seconds": 210},
            segs,
            [{"second": 95, "file": "a.jpg", "caption": "a chart"}],
        )
        self.assertIn("![a chart]", md)
        self.assertLess(md.index("the chart."), md.index("screenshots/a.jpg"))
        self.assertLess(md.index("screenshots/a.jpg"), md.index("the end."))

    def test_a_screenshot_past_the_last_paragraph_still_appears(self):
        segs = _segments([(0, "only paragraph.")])
        md = transcript.render_markdown(
            {"title": "T", "url": "u", "duration_seconds": 10},
            segs,
            [{"second": 9999, "file": "z.jpg", "caption": "late"}],
        )
        self.assertIn("screenshots/z.jpg", md)


class TestFrames(unittest.TestCase):
    def test_burst_offsets_are_centred_and_span_the_spread(self):
        self.assertEqual(frames.burst_offsets(5, 6.0), [-6.0, -3.0, 0.0, 3.0, 6.0])
        self.assertEqual(frames.burst_offsets(1, 6.0), [0.0])

    def test_slugify_is_ascii_and_bounded(self):
        self.assertEqual(frames.slugify("Opening Range Gap: High & Low!"), "opening-range-gap-high-low")
        self.assertEqual(frames.slugify(""), "frame")
        self.assertLessEqual(len(frames.slugify("x" * 200)), 60)

    def test_second_is_read_back_from_a_candidate_filename(self):
        self.assertEqual(frames.second_from_name(Path("venom_880s.jpg")), 880.0)
        self.assertEqual(frames.second_from_name(Path("nope.jpg")), 0.0)


class TestPrompts(unittest.TestCase):
    def test_timecodes_in_every_form_become_seconds(self):
        self.assertEqual(prompts.parse_timecode("01:30"), 90.0)
        self.assertEqual(prompts.parse_timecode("1:00:30"), 3630.0)
        self.assertEqual(prompts.parse_timecode("90"), 90.0)
        self.assertEqual(prompts.parse_timecode("nonsense"), 0.0)

    def test_both_schemas_are_closed_objects(self):
        for schema in (prompts.MOMENTS_SCHEMA, prompts.SELECTION_SCHEMA):
            self.assertEqual(schema["type"], "object")
            self.assertFalse(schema["additionalProperties"])


class TestJsonReader(unittest.TestCase):
    def test_a_bare_object_parses(self):
        self.assertEqual(parse_json_object('{"a": 1}'), {"a": 1})

    def test_a_fenced_object_parses(self):
        self.assertEqual(parse_json_object('```json\n{"a": 1}\n```'), {"a": 1})

    def test_an_object_buried_in_prose_parses(self):
        self.assertEqual(parse_json_object('Sure!\n{"a": 1}\nHope that helps.'), {"a": 1})

    def test_nothing_usable_raises(self):
        for bad in ("", "no json at all", "[1, 2, 3]"):
            with self.assertRaises(LLMError):
                parse_json_object(bad)


if __name__ == "__main__":
    unittest.main()


class TestYtdlpCommand(unittest.TestCase):
    """How this package talks to YouTube.

    Every yt-dlp call in the package goes through one builder, because metadata,
    captions and frame capture are three separate invocations - a cookie fix that
    reaches only one of them looks like a flaky tool.
    """

    def setUp(self):
        self._node = mock.patch.object(binaries, "node_path", return_value="/bin/node")
        self._ytdlp = mock.patch.object(binaries, "ytdlp_path", return_value="/bin/yt-dlp")
        self._env = mock.patch.dict("os.environ", {}, clear=True)
        for patcher in (self._node, self._ytdlp, self._env):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.addCleanup(binaries.configure)

    def test_a_javascript_runtime_is_offered_by_default(self):
        """Without one, YouTube's n challenge fails and nothing can be extracted."""
        binaries.configure()
        self.assertEqual(binaries.ytdlp_base_args(), ["--js-runtimes", "node:/bin/node"])

    def test_the_runtime_can_be_switched_off_for_diagnosis(self):
        binaries.configure(use_node=False)
        self.assertEqual(binaries.ytdlp_base_args(), [])

    def test_a_cookies_file_wins_over_a_browser(self):
        with tempfile.NamedTemporaryFile(suffix=".txt") as fh:
            binaries.configure(cookies_file=fh.name, cookies_from_browser="firefox")
            args = binaries.ytdlp_base_args()
        self.assertIn("--cookies", args)
        self.assertNotIn("--cookies-from-browser", args)

    def test_a_browser_is_used_when_no_file_is_given(self):
        binaries.configure(cookies_from_browser="firefox")
        self.assertIn("--cookies-from-browser", binaries.ytdlp_base_args())

    def test_a_missing_cookies_file_is_refused_with_the_fix(self):
        """yt-dlp reports this as a raw traceback; the useful line must not be buried."""
        with self.assertRaises(MissingRequirement) as caught:
            binaries.configure(cookies_file="/nope/cookies.txt")
        self.assertIn("--cookies-from-browser", str(caught.exception))

    def test_extra_arguments_pass_through(self):
        binaries.configure(extra_args=["--extractor-args", "youtube:player_client=web"])
        self.assertIn("youtube:player_client=web", binaries.ytdlp_base_args())

    def test_the_environment_configures_a_machine_once(self):
        with mock.patch.dict("os.environ", {"YT_EXTRACT_COOKIES_FROM_BROWSER": "chrome"}):
            binaries.configure()
        self.assertIn("chrome", binaries.ytdlp_base_args())

    def test_shared_flags_come_before_the_call_specific_ones(self):
        binaries.configure()
        self.assertEqual(
            binaries.ytdlp_command("--print", "%(id)s", "URL"),
            ["/bin/yt-dlp", "--js-runtimes", "node:/bin/node", "--print", "%(id)s", "URL"],
        )


class TestFailureExplanation(unittest.TestCase):
    def test_an_authentication_failure_gains_the_actual_fix(self):
        for stderr in (
            "ERROR: Sign in to confirm you're not a bot",
            "ERROR: The page needs to be reloaded",
            "WARNING: n challenge solving failed",
        ):
            self.assertIn("--cookies-from-browser", binaries.explain_ytdlp_failure(stderr), stderr)

    def test_expired_cookies_are_named_as_such(self):
        """"No longer valid" means rotated, and needs a different fix from "no cookies"."""
        explained = binaries.explain_ytdlp_failure(
            "WARNING: The provided YouTube account cookies are no longer valid. "
            "They have likely been rotated in the browser as a security measure."
        )
        self.assertIn("EXPIRED", explained)
        self.assertIn("private window", explained)

    def test_the_chrome_dead_end_is_called_out(self):
        """Chrome on Windows cannot be read at all; suggesting it wastes an hour."""
        explained = binaries.explain_ytdlp_failure("ERROR: Sign in to confirm you're not a bot")
        self.assertIn("firefox", explained)
        self.assertIn("Chrome 127", explained)

    def test_an_unrelated_failure_is_left_alone(self):
        explained = binaries.explain_ytdlp_failure("ERROR: unable to write to disk")
        self.assertNotIn("--cookies-from-browser", explained)
        self.assertIn("unable to write to disk", explained)
