"""Screenshot capture — download only what is needed, then take several frames
per moment instead of one.

Two ideas carry the quality of the output:

1. **Only the interesting seconds are downloaded.** Once the moments are known,
   each one is fetched as a short section of low-resolution video. A long video
   costs a few megabytes instead of a hundred.

2. **Each moment yields a burst of candidate frames, not one frame.** The exact
   second a sentence starts is very often the presenter's face, a cursor mid-move
   or a cross-fade. Sampling a few seconds either side and then choosing gives a
   usable image nearly every time; taking a single frame does not.
"""

from __future__ import annotations

import re
from pathlib import Path

from .binaries import ffmpeg_path, ffprobe_path, run, ytdlp_path
from .errors import ExtractError

# Video-only, capped height: frames are for reading charts and slides, and audio
# would double the download for nothing.
_FORMAT = "bv*[height<=720][ext=mp4]/bv*[height<=720]/best[height<=720]/best"

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def slugify(text: str, *, max_length: int = 60) -> str:
    """A lowercase ASCII slug safe to use as a filename."""
    slug = _SLUG_RE.sub("-", str(text or "").lower()).strip("-")
    return slug[:max_length].strip("-") or "frame"


def burst_offsets(count: int, spread: float) -> list[float]:
    """`count` offsets in seconds, centred on zero and spanning ±`spread`."""
    if count <= 1:
        return [0.0]
    step = (2 * spread) / (count - 1)
    return [round(-spread + step * i, 2) for i in range(count)]


def probe_duration(path: Path) -> float | None:
    """Length of a local media file, or None when ffprobe is unavailable."""
    probe = ffprobe_path()
    if not probe:
        return None
    proc = run(
        [probe, "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        timeout=60,
    )
    try:
        return float(proc.stdout.strip())
    except (TypeError, ValueError):
        return None


def download_section(url: str, start: float, end: float, workdir: Path, name: str,
                     *, timeout: int = 600) -> Path:
    """Download `[start, end]` of the video and return the local file.

    `--force-keyframes-at-cuts` makes the section begin exactly at `start`;
    without it yt-dlp cuts at the previous keyframe and every later seek is off
    by an unknown amount.
    """
    workdir.mkdir(parents=True, exist_ok=True)
    start = max(0.0, start)
    target = workdir / name
    proc = run(
        [
            ytdlp_path(), "--quiet", "--no-warnings",
            "--download-sections", f"*{start:.2f}-{end:.2f}",
            "--force-keyframes-at-cuts",
            "-f", _FORMAT,
            "-o", str(workdir / (name + ".%(ext)s")),
            url,
        ],
        timeout=timeout,
    )
    hits = sorted(workdir.glob(name + ".*"))
    if not hits:
        raise ExtractError(
            f"yt-dlp downloaded no video for section {start:.0f}-{end:.0f}s: "
            f"{proc.stderr.strip()[-300:]}"
        )
    return hits[0]


def grab_frame(video: Path, offset: float, out_path: Path, *, timeout: int = 120) -> Path | None:
    """One JPEG at `offset` seconds into `video`, or None if there is no frame there.

    `-ss` is placed before `-i` so ffmpeg seeks rather than decoding from the
    start, which matters when the same section is sampled several times.
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)
    run(
        [
            ffmpeg_path(), "-y", "-loglevel", "error",
            "-ss", f"{max(0.0, offset):.2f}", "-i", str(video),
            "-frames:v", "1", "-q:v", "2", str(out_path),
        ],
        timeout=timeout,
    )
    return out_path if out_path.is_file() and out_path.stat().st_size > 0 else None


def detail_score(path: Path) -> int:
    """How much visual detail a JPEG holds, approximated by its encoded size.

    A chart full of candles, gridlines and text does not compress well; a talking
    head against a plain wall, a title card or a cross-fade does. Comparing sizes
    of frames written with identical settings therefore ranks "busy" images above
    "empty" ones - which is exactly the preference wanted here, and it needs no
    image library at all.
    """
    try:
        return path.stat().st_size
    except OSError:
        return 0


def capture_moment(url: str, second: float, key: str, workdir: Path,
                   *, count: int = 5, spread: float = 6.0,
                   duration: float | None = None) -> list[Path]:
    """Candidate frames around one moment, best-detail first.

    Returns an empty list when the section cannot be downloaded, so one bad
    moment never aborts a whole video.
    """
    section_start = max(0.0, second - spread - 2.0)
    section_end = second + spread + 2.0
    if duration:
        section_end = min(section_end, duration)
    if section_end <= section_start:
        return []

    # A re-run of the same video should cost nothing: frames already captured for
    # this moment are reused rather than downloaded and cut again.
    existing = sorted((workdir / "candidates").glob(f"{key}_*.jpg"))
    if existing:
        return sorted(existing, key=detail_score, reverse=True)

    sections = workdir / "sections"
    try:
        clip = download_section(url, section_start, section_end, sections, f"{key}")
    except ExtractError:
        return []

    candidates_dir = workdir / "candidates"
    frames: list[Path] = []
    for offset in burst_offsets(count, spread):
        absolute = second + offset
        if absolute < 0 or (duration and absolute > duration):
            continue
        local = absolute - section_start
        out = candidates_dir / f"{key}_{int(round(absolute))}s.jpg"
        got = grab_frame(clip, local, out)
        if got:
            frames.append(got)
    return sorted(frames, key=detail_score, reverse=True)


def second_from_name(path: Path) -> float:
    """The absolute video second encoded in a candidate filename."""
    match = re.search(r"_(\d+)s\.jpg$", path.name)
    return float(match.group(1)) if match else 0.0
