"""Turning timestamped caption segments into the two text artefacts.

`transcript.md` is for a human (and for whatever writes from it later): metadata
at the top, then readable paragraphs, each anchored to the second it starts at.

`thin.txt` is for a model: the same video reduced to roughly one line per
half-minute, so a forty-minute video can be read in a single cheap request when
the tool asks which moments matter.
"""

from __future__ import annotations

from pathlib import Path

from .subtitles import Segment


def timecode(seconds: float) -> str:
    """Seconds as `MM:SS`, or `HH:MM:SS` once the video passes an hour."""
    total = int(max(0.0, seconds))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes:02d}:{secs:02d}"


def full_text(segments: list[Segment]) -> str:
    """Every caption line joined into one running string."""
    return " ".join(seg.text for seg in segments).strip()


def paragraphs(segments: list[Segment], *, target_seconds: float = 45.0) -> list[tuple[float, str]]:
    """Group segments into `(start_second, text)` paragraphs.

    Captions arrive as a few words at a time, which is unreadable in a document.
    A paragraph closes once it has covered about `target_seconds` of video AND
    the last line ended on sentence punctuation, so paragraphs break where the
    speaker actually stopped rather than on a fixed clock.
    """
    out: list[tuple[float, str]] = []
    start: float | None = None
    buffer: list[str] = []
    for seg in segments:
        if start is None:
            start = seg.start
        buffer.append(seg.text)
        long_enough = seg.start - start >= target_seconds
        if long_enough and (seg.text.endswith((".", "?", "!")) or seg.start - start >= target_seconds * 2):
            out.append((start, " ".join(buffer).strip()))
            start, buffer = None, []
    if buffer and start is not None:
        out.append((start, " ".join(buffer).strip()))
    return out


def thin_index(segments: list[Segment], *, every_seconds: float = 30.0) -> str:
    """A downsampled `[MM:SS] text` index of the whole video.

    One line per `every_seconds` keeps a long video inside a small prompt while
    preserving enough wording for a model to tell what is happening when.
    """
    lines: list[str] = []
    next_at = 0.0
    for seg in segments:
        if seg.start >= next_at:
            lines.append(f"[{timecode(seg.start)}] {seg.text}")
            next_at = seg.start + every_seconds
    return "\n".join(lines)


def render_markdown(meta: dict, segments: list[Segment], shots: list[dict] | None = None) -> str:
    """The final `transcript.md`.

    `shots` are the selected screenshots as `{"second": float, "file": str,
    "caption": str}`. Each is emitted directly after the paragraph whose span
    covers its second, so the reader meets the image having just read the words
    that explain it. Placing it before that paragraph instead would show the
    picture ahead of its own explanation - and because a paragraph can cover a
    minute of speech, "before the next paragraph that starts later" is not the
    same rule and gets it wrong whenever a paragraph runs long.
    """
    pending = sorted(shots or [], key=lambda s: s["second"])
    lines: list[str] = [
        f"# {meta.get('title') or meta.get('video_id') or 'Untitled video'}",
        "",
        f"- **Channel:** {meta.get('channel') or 'unknown'}",
        f"- **Source:** {meta.get('url', '')}",
        f"- **Duration:** {timecode(meta.get('duration_seconds') or 0)}",
    ]
    if meta.get("upload_date"):
        raw = str(meta["upload_date"])
        pretty = f"{raw[0:4]}-{raw[4:6]}-{raw[6:8]}" if len(raw) == 8 else raw
        lines.append(f"- **Published:** {pretty}")
    lines += ["", "---", ""]

    grouped = paragraphs(segments)
    for index, (start, text) in enumerate(grouped):
        lines += [f"**[{timecode(start)}]** {text}", ""]
        # This paragraph covers everything said before the next one begins; the
        # last paragraph covers whatever is left.
        covers_until = grouped[index + 1][0] if index + 1 < len(grouped) else float("inf")
        while pending and pending[0]["second"] < covers_until:
            lines += _shot_lines(pending.pop(0))

    for shot in pending:
        lines += _shot_lines(shot)
    return "\n".join(lines).rstrip() + "\n"


def _shot_lines(shot: dict) -> list[str]:
    caption = shot.get("caption", "")
    return [
        f"![{caption}](screenshots/{shot['file']})",
        "",
        f"*{caption} — {timecode(shot['second'])}*",
        "",
    ]


def write_text(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path
