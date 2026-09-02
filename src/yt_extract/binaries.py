"""Finding and running the external programs this tool drives.

Three of them, all pip-installable so a normal install needs no manual setup:

- **yt-dlp** — reads YouTube. It is also the piece that breaks when YouTube
  changes, so it is not pinned tight; `pip install -U yt-dlp` is the first fix
  for almost any extraction failure.
- **ffmpeg** — cuts frames out of video.
- **node** — YouTube now hands out a JavaScript "n challenge" that must be
  executed before it will serve formats, and increasingly before it will serve
  metadata at all. yt-dlp solves it with a JS runtime plus the `yt-dlp-ejs`
  script distribution; without one, extraction fails with messages like
  "n challenge solving failed" or "The page needs to be reloaded".

Each resolver prefers an explicit override, then a system install (usually newer
and better optimised), then the bundled copy.

This module is also the single place that builds a yt-dlp command line, so a
cookie or runtime setting applies to every call the package makes rather than
only to the one that happened to be edited.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from .errors import MissingRequirement

_FFMPEG_HINT = {
    "linux": "sudo dnf install ffmpeg   (Fedora/RHEL)   |   sudo apt install ffmpeg   (Debian/Ubuntu)",
    "darwin": "brew install ffmpeg",
    "win32": "winget install Gyan.FFmpeg",
}


def _platform_hint() -> str:
    return _FFMPEG_HINT.get(sys.platform, _FFMPEG_HINT["linux"])


@dataclass
class YtdlpSettings:
    """How this run should talk to YouTube.

    Set once by the CLI and read by every yt-dlp call. Cookies matter because
    YouTube increasingly refuses anonymous requests - the failure reads as
    "Sign in to confirm you're not a bot", "The page needs to be reloaded", or a
    bare "could not read metadata", and no amount of retrying fixes it.
    """

    cookies_file: str = ""
    cookies_from_browser: str = ""
    extra_args: list[str] = field(default_factory=list)
    use_node: bool = True


_settings = YtdlpSettings()


def configure(*, cookies_file: str = "", cookies_from_browser: str = "",
              extra_args: list[str] | None = None, use_node: bool = True) -> None:
    """Set the yt-dlp options for this process.

    Anything not passed falls back to an environment variable, so a machine can
    be configured once instead of on every command.
    """
    global _settings
    cookies = cookies_file or os.environ.get("YT_EXTRACT_COOKIES", "")
    if cookies and not os.path.isfile(cookies):
        # Caught here rather than left to yt-dlp, which reports a missing cookie
        # file as a raw Python traceback that buries the one useful line.
        raise MissingRequirement(
            f"the cookies file {cookies!r} does not exist.\n"
            "  Export one with a 'cookies.txt' browser extension while signed in to YouTube,\n"
            "  or skip the file entirely and use:  --cookies-from-browser firefox"
        )
    _settings = YtdlpSettings(
        cookies_file=cookies,
        cookies_from_browser=(
            cookies_from_browser or os.environ.get("YT_EXTRACT_COOKIES_FROM_BROWSER", "")
        ),
        extra_args=list(extra_args or []) or os.environ.get("YT_EXTRACT_YTDLP_ARGS", "").split(),
        use_node=use_node,
    )


def settings() -> YtdlpSettings:
    return _settings


@lru_cache(maxsize=1)
def ffmpeg_path() -> str:
    """Absolute path to an ffmpeg binary."""
    override = (os.environ.get("YT_EXTRACT_FFMPEG") or "").strip()
    if override:
        if not os.path.isfile(override):
            raise MissingRequirement(
                f"YT_EXTRACT_FFMPEG points at {override!r}, which is not a file."
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
    """A system ffprobe if there is one, else None (the bundled ffmpeg has none)."""
    return shutil.which("ffprobe")


def _beside_interpreter(*names: str) -> str | None:
    """A console script installed next to this interpreter.

    On Windows these land in `...\\Scripts\\`, which is frequently not on PATH -
    the single most common reason a freshly pip-installed tool "does not exist".
    """
    for name in names:
        for folder in (Path(sys.executable).parent, Path(sys.executable).parent / "Scripts"):
            candidate = folder / name
            if candidate.is_file():
                return str(candidate)
    return None


@lru_cache(maxsize=1)
def ytdlp_path() -> str:
    """Absolute path to the yt-dlp executable."""
    found = shutil.which("yt-dlp") or _beside_interpreter("yt-dlp.exe", "yt-dlp")
    if found:
        return found
    raise MissingRequirement("yt-dlp was not found. Install it with:  pip install -U yt-dlp")


@lru_cache(maxsize=1)
def node_path() -> str | None:
    """A JavaScript runtime for yt-dlp's challenge solver, or None."""
    override = (os.environ.get("YT_EXTRACT_NODE") or "").strip()
    if override:
        return override if os.path.isfile(override) else None

    found = shutil.which("node")
    if found:
        return found

    try:
        import nodejs_wheel.executable as bundled
    except ImportError:
        return None
    root = Path(bundled.ROOT_DIR)
    for candidate in (root / "bin" / "node", root / "node.exe", root / "node"):
        if candidate.is_file():
            return str(candidate)
    return None


@lru_cache(maxsize=1)
def has_ejs() -> bool:
    """Whether yt-dlp's challenge-solver script distribution is installed."""
    try:
        import yt_dlp_ejs  # noqa: F401
    except ImportError:
        return False
    return True


def ytdlp_base_args() -> list[str]:
    """The yt-dlp flags every call in this package shares.

    Built here rather than inline at each call site, because metadata, captions
    and frame capture are three separate yt-dlp invocations: a cookie fix applied
    to only one of them looks like a flaky tool.
    """
    args: list[str] = []
    current = settings()

    if current.use_node:
        node = node_path()
        if node:
            # Naming the path explicitly rather than just "node" - a node that
            # came from a pip wheel is not on PATH.
            args += ["--js-runtimes", f"node:{node}"]

    if current.cookies_file:
        args += ["--cookies", current.cookies_file]
    elif current.cookies_from_browser:
        args += ["--cookies-from-browser", current.cookies_from_browser]

    args += current.extra_args
    return args


def ytdlp_command(*args: str) -> list[str]:
    """A full yt-dlp command line: the binary, the shared flags, then `args`."""
    return [ytdlp_path(), *ytdlp_base_args(), *args]


# Signatures in yt-dlp's stderr meaning "YouTube refused you", not "this video is
# broken". They need a completely different fix from every other failure, and the
# raw message does not make that obvious enough to act on.
_AUTH_SIGNATURES = (
    "sign in to confirm",
    "--cookies",
    "cookies-from-browser",
    "not a bot",
    "age-restricted",
    "login required",
    "the page needs to be reloaded",
    "challenge solving failed",
    "confirm your age",
    "no supported javascript runtime",
)

# YouTube rotates the session on any open YouTube tab, which silently invalidates
# a cookies.txt exported earlier from that same browser. This is the single most
# common way a cookie setup that "worked yesterday" stops working, and the fix is
# not obvious from the message.
_ROTATED_SIGNATURE = "no longer valid"

COOKIE_HELP = (
    "YouTube refused this request. Fixes, in the order worth trying:\n"
    "\n"
    "  1. Try again with NO cookies at all. Invalid cookies are worse than none,\n"
    "     and this tool now supplies the JavaScript runtime YouTube requires.\n"
    "\n"
    "  2. Use Firefox:  --cookies-from-browser firefox\n"
    "     Log in to YouTube in Firefox, CLOSE Firefox completely, then run this.\n"
    "     Chrome does not work for this on Windows: since Chrome 127 its cookies\n"
    "     are encrypted with a key bound to the Chrome process, so they cannot be\n"
    "     read at all - that is the 'Could not copy Chrome cookie database' error,\n"
    "     and it has no workaround.\n"
    "\n"
    "  3. Export a cookies.txt the way that survives:  --cookies <file>\n"
    "     a. open a PRIVATE / incognito window and log in to YouTube\n"
    "     b. in that same window go to  https://www.youtube.com/robots.txt\n"
    "     c. export youtube.com cookies with a cookies.txt extension\n"
    "     d. CLOSE the private window without logging out\n"
    "     Exporting from a normal window gives a file YouTube invalidates within\n"
    "     minutes, because it rotates the session on every open YouTube tab.\n"
    "\n"
    "  4. Update yt-dlp:  pip install -U yt-dlp\n"
    "\n"
    "Run `yt-extract doctor` to confirm the runtime and solver scripts are present."
)

ROTATED_HELP = (
    "The cookies you supplied have EXPIRED - YouTube rotated that session.\n"
    "This happens whenever the cookies were exported from a browser that then\n"
    "kept a YouTube tab open. Re-export them from a private window (step 3 below),\n"
    "or drop the cookie flag entirely and try without."
)


def explain_ytdlp_failure(stderr: str) -> str:
    """Append the actual fix when yt-dlp's failure is an authentication one."""
    text = stderr or ""
    lowered = text.lower()
    tail = text.strip()[-400:]
    if _ROTATED_SIGNATURE in lowered and "cookies" in lowered:
        return f"{tail}\n\n{ROTATED_HELP}\n\n{COOKIE_HELP}"
    if any(sig in lowered for sig in _AUTH_SIGNATURES):
        return f"{tail}\n\n{COOKIE_HELP}"
    return tail


def run(cmd: list[str], *, timeout: int = 900, check: bool = False) -> subprocess.CompletedProcess:
    """Run a command, capturing both streams as text."""
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if check and proc.returncode != 0:
        raise MissingRequirement(
            f"command failed ({os.path.basename(cmd[0])}): {proc.stderr.strip()[-400:]}"
        )
    return proc
