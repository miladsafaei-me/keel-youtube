"""Caption download and parsing — the transcript half of the tool.

Timestamps are kept all the way through. That is the difference that makes
screenshots possible at all: without a start time per line there is no way to
know which second of video a sentence belongs to.

json3 is preferred over vtt because it carries clean per-event text; vtt is the
fallback for the videos where YouTube serves nothing else.
"""

from __future__ import annotations

import html
import json
import re
from pathlib import Path

from .binaries import run, ytdlp_path
from .errors import TranscriptUnavailable

_WS_RE = re.compile(r"\s+")
_VTT_TIME_RE = re.compile(
    r"(\d{2}):(\d{2}):(\d{2})[.,](\d{3})\s*-->\s*(\d{2}):(\d{2}):(\d{2})[.,](\d{3})"
)
_VTT_TAG_RE = re.compile(r"<[^>]+>")


class Segment:
    """One caption line: when it starts, and what is said."""

    __slots__ = ("start", "text")

    def __init__(self, start: float, text: str) -> None:
        self.start = float(start)
        self.text = text

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"Segment({self.start:.1f}, {self.text[:40]!r})"


def fetch_metadata(url: str, *, timeout: int = 180) -> dict:
    """Title, channel, duration and upload date, in one yt-dlp call."""
    fields = "%(id)s\t%(title)s\t%(channel)s\t%(duration)s\t%(upload_date)s"
    proc = run([ytdlp_path(), "--skip-download", "--print", fields, url], timeout=timeout)
    if proc.returncode != 0:
        raise TranscriptUnavailable(
            f"yt-dlp could not read metadata for {url!r}: {proc.stderr.strip()[-300:]}"
        )
    parts = (proc.stdout.strip().split("\t") + [""] * 5)[:5]
    vid, title, channel, duration, upload_date = parts
    try:
        seconds = int(float(duration))
    except (TypeError, ValueError):
        seconds = 0
    return {
        "video_id": vid,
        "title": title,
        "channel": channel,
        "duration_seconds": seconds,
        "upload_date": upload_date,
    }


def download_captions(url: str, workdir: Path, *, lang: str = "en", timeout: int = 300) -> Path:
    """Download a caption track into `workdir` and return the file.

    Manual captions are tried before auto-generated ones (a human-written track
    is punctuated and far cleaner), and json3 before vtt.
    """
    workdir.mkdir(parents=True, exist_ok=True)
    base = str(workdir / "captions")
    for sub_flag in ("--write-subs", "--write-auto-subs"):
        for fmt in ("json3", "vtt"):
            run(
                [
                    ytdlp_path(), "--skip-download", sub_flag,
                    "--sub-langs", f"{lang},{lang}-orig,{lang}.*",
                    "--sub-format", fmt,
                    "-o", base + ".%(ext)s",
                    url,
                ],
                timeout=timeout,
            )
            hits = sorted(
                workdir.glob(f"captions*.{fmt}"),
                # Prefer the exact-language file over an -orig alias when both landed.
                key=lambda p: (f".{lang}." not in p.name, len(p.name)),
            )
            if hits:
                return hits[0]
    raise TranscriptUnavailable(
        f"no {lang} caption track for {url!r}. Audio transcription is out of scope for "
        "this tool - pick a video that has captions, or supply a transcript yourself."
    )


def parse(path: Path) -> list[Segment]:
    """A caption file (json3 or vtt) as timestamped segments."""
    segments = _parse_json3(path) if path.suffix == ".json3" else _parse_vtt(path)
    if not segments:
        raise TranscriptUnavailable(f"caption file {path.name} parsed to nothing")
    return segments


def _clean(text: str) -> str:
    return _WS_RE.sub(" ", html.unescape(text).replace("\n", " ")).strip()


def _dedupe(segments: list[Segment]) -> list[Segment]:
    """Drop a line that only repeats the one before it.

    YouTube's auto-captions scroll: each event often restates the tail of the
    previous one, which would otherwise triple the transcript's length.
    """
    out: list[Segment] = []
    for seg in segments:
        if not seg.text:
            continue
        if out and (seg.text == out[-1].text or seg.text in out[-1].text):
            continue
        if out and out[-1].text in seg.text:
            out[-1] = seg
            continue
        out.append(seg)
    return out


def _parse_json3(path: Path) -> list[Segment]:
    data = json.loads(path.read_text(encoding="utf-8"))
    segments: list[Segment] = []
    for event in data.get("events", []):
        parts = event.get("segs")
        if not parts:
            continue
        text = _clean("".join(p.get("utf8", "") for p in parts))
        if text:
            segments.append(Segment(int(event.get("tStartMs", 0)) / 1000.0, text))
    return _dedupe(segments)


def _parse_vtt(path: Path) -> list[Segment]:
    segments: list[Segment] = []
    start: float | None = None
    buffer: list[str] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        match = _VTT_TIME_RE.search(line)
        if match:
            if start is not None and buffer:
                segments.append(Segment(start, _clean(" ".join(buffer))))
            h, m, s, ms = (int(match.group(i)) for i in (1, 2, 3, 4))
            start = h * 3600 + m * 60 + s + ms / 1000.0
            buffer = []
        elif start is not None and line.strip() and not line.startswith(("WEBVTT", "Kind:", "Language:", "NOTE")):
            buffer.append(_VTT_TAG_RE.sub("", line))
    if start is not None and buffer:
        segments.append(Segment(start, _clean(" ".join(buffer))))
    return _dedupe(segments)
