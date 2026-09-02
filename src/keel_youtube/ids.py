"""YouTube URL handling — the only place that knows what a YouTube link looks
like."""

from __future__ import annotations

import re

_ID_RE = re.compile(
    r"(?:youtube(?:-nocookie)?\.com/(?:watch\?(?:[^#\s]*&)?v=|embed/|shorts/|live/)|youtu\.be/)"
    r"([A-Za-z0-9_-]{11})"
)


def video_id(url: str) -> str:
    """The 11-character video id from any watch / shorts / embed / youtu.be URL.

    Returns "" when the string is not a recognizable YouTube link, so callers can
    test it as a boolean instead of catching an exception.
    """
    match = _ID_RE.search(str(url or ""))
    return match.group(1) if match else ""


def canonical_url(url: str) -> str:
    """Any YouTube URL form normalized to `https://www.youtube.com/watch?v=<id>`."""
    vid = video_id(url)
    return f"https://www.youtube.com/watch?v={vid}" if vid else str(url or "").strip()
