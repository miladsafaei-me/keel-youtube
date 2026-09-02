"""Finding and running the two external programs this tool drives.

Both are pip-installable, so the normal case needs no manual setup at all. Each
resolver still checks a system install first: a distribution's own ffmpeg is
usually newer and better optimized than the bundled one, and a user who set
KEEL_YOUTUBE_FFMPEG meant it.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from functools import lru_cache

from .errors import MissingRequirement

# Per-OS install lines, used only to build a helpful error message.
_FFMPEG_HINT = {
    "linux": "sudo dnf install ffmpeg   (Fedora/RHEL)   |   sudo apt install ffmpeg   (Debian/Ubuntu)",
    "darwin": "brew install ffmpeg",
    "win32": "winget install Gyan.FFmpeg",
}


def _platform_hint() -> str:
    return _FFMPEG_HINT.get(sys.platform, _FFMPEG_HINT["linux"])


@lru_cache(maxsize=1)
def ffmpeg_path() -> str:
    """Absolute path to an ffmpeg binary.

    Order: an explicit KEEL_YOUTUBE_FFMPEG override, then a system ffmpeg on
    PATH, then the copy bundled by the imageio-ffmpeg dependency.
    """
    override = (os.environ.get("KEEL_YOUTUBE_FFMPEG") or "").strip()
    if override:
        if not os.path.isfile(override):
            raise MissingRequirement(
                f"KEEL_YOUTUBE_FFMPEG points at {override!r}, which is not a file."
            )
        return override

    found = shutil.which("ffmpeg")
    if found:
        return found

    try:
        import imageio_ffmpeg
    except ImportError:
        raise MissingRequirement(
            "ffmpeg is required to capture frames but was not found.\n"
            f"  install it with:  pip install imageio-ffmpeg\n"
            f"  or system-wide:   {_platform_hint()}"
        ) from None
    return imageio_ffmpeg.get_ffmpeg_exe()


@lru_cache(maxsize=1)
def ffprobe_path() -> str | None:
    """A system ffprobe if there is one, else None.

    imageio-ffmpeg bundles ffmpeg without ffprobe, so this is genuinely optional
    and every caller must cope with None.
    """
    return shutil.which("ffprobe")


@lru_cache(maxsize=1)
def ytdlp_path() -> str:
    """Absolute path to the yt-dlp executable.

    yt-dlp is a declared dependency, so it lands in the same environment as this
    package; the PATH lookup is only a fallback for odd installs.
    """
    found = shutil.which("yt-dlp")
    if found:
        return found
    candidate = os.path.join(os.path.dirname(sys.executable), "yt-dlp")
    if os.path.isfile(candidate):
        return candidate
    raise MissingRequirement(
        "yt-dlp was not found. Install it with:  pip install -U yt-dlp"
    )


def run(cmd: list[str], *, timeout: int = 900, check: bool = False) -> subprocess.CompletedProcess:
    """Run a command, capturing both streams as text.

    `check=True` converts a non-zero exit into a MissingRequirement carrying the
    tail of stderr, which is what actually tells the user what went wrong.
    """
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if check and proc.returncode != 0:
        raise MissingRequirement(
            f"command failed ({os.path.basename(cmd[0])}): {proc.stderr.strip()[-400:]}"
        )
    return proc
