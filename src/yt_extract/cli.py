"""The command line.

    yt-extract run <url> --out ./out      the whole thing
    yt-extract plan <url> --out ./out     stop after the transcript
    yt-extract doctor                     what is installed, what is missing
    yt-extract doctor --fix               install what pip can install

`ytx` is a shorter alias for all of it, and `python -m yt_extract ...` works when
pip put the console scripts somewhere that is not on PATH.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

from . import __version__, llm
from .binaries import (configure, ffmpeg_path, ffprobe_path, has_ejs, node_path,
                       settings, ytdlp_path)
from .errors import ExtractError
from .pipeline import run as run_pipeline

# What `doctor --fix` may install. Everything here is a normal PyPI wheel; the
# command never touches the system package manager, never asks for admin rights,
# and never installs outside the environment it is running in.
_FIXABLE = {
    "yt-dlp": "yt-dlp",
    "ffmpeg": "imageio-ffmpeg",
    "node": "nodejs-wheel-binaries",
    "challenge solver": "yt-dlp-ejs",
}


def _add_run_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("urls", nargs="+", metavar="URL", help="One or more YouTube URLs.")
    parser.add_argument("--out", default="./out", help="Where the per-video folders go (default: ./out).")
    parser.add_argument("--shots", type=int, default=6, help="How many screenshots to take (default: 6).")
    parser.add_argument("--lang", default="en", help="Caption language to prefer (default: en).")

    youtube = parser.add_argument_group(
        "talking to YouTube",
        "YouTube refuses many anonymous requests. If extraction fails with "
        "'sign in to confirm', 'page needs to be reloaded' or a bare metadata "
        "error, give it a browser session with one of these.",
    )
    youtube.add_argument("--cookies-from-browser", metavar="BROWSER",
                         help="Read cookies straight from an installed browser: "
                              "firefox, chrome, edge, brave, opera, vivaldi, safari, chromium.")
    youtube.add_argument("--cookies", metavar="FILE",
                         help="A Netscape-format cookies.txt exported from your browser.")
    youtube.add_argument("--ytdlp-arg", action="append", default=[], metavar="ARG",
                         help="Pass one more argument through to yt-dlp. Repeatable; "
                              "the escape hatch for any yt-dlp option this tool does not wrap.")
    youtube.add_argument("--no-node", action="store_true",
                         help="Do not offer yt-dlp a JavaScript runtime (diagnostics only).")

    model = parser.add_argument_group("choosing the model")
    model.add_argument("--provider", choices=sorted(llm.BY_NAME),
                       help="Force a model provider instead of auto-detecting.")
    model.add_argument("--model", help="Model name for the chosen provider.")
    model.add_argument("--no-llm", action="store_true",
                       help="Run without any model: evenly spaced moments, busiest frame wins.")

    tuning = parser.add_argument_group("tuning the capture")
    tuning.add_argument("--burst", type=int, default=5,
                        help="Frames captured around each moment (default: 5).")
    tuning.add_argument("--shortlist", type=int, default=3,
                        help="How many of those frames the model is shown (default: 3).")
    tuning.add_argument("--spread", type=float, default=6.0,
                        help="Seconds either side of a moment to sample (default: 6).")
    tuning.add_argument("--clean", action="store_true", help="Delete work/ when the run succeeds.")


def _pip_install(packages: list[str]) -> int:
    """Install into the environment this tool is running in, never elsewhere."""
    print(f"\ninstalling: {' '.join(packages)}")
    # pip writes straight to the terminal, so anything still sitting in our own
    # buffer would appear after it and read as though the order were reversed.
    sys.stdout.flush()
    proc = subprocess.run([sys.executable, "-m", "pip", "install", "--upgrade", *packages])
    return proc.returncode


def _probe() -> tuple[list[tuple[str, bool, str]], list[str]]:
    """`(rows, missing_package_names)` describing the external programs."""
    rows: list[tuple[str, bool, str]] = []
    missing: list[str] = []

    for label, resolver in (("yt-dlp", ytdlp_path), ("ffmpeg", ffmpeg_path)):
        try:
            rows.append((label, True, resolver()))
        except ExtractError as exc:
            rows.append((label, False, str(exc).splitlines()[0]))
            missing.append(_FIXABLE[label])

    node = node_path()
    rows.append(("node", bool(node), node or
                 "no JavaScript runtime - YouTube's challenge cannot be solved"))
    if not node:
        missing.append(_FIXABLE["node"])

    rows.append(("challenge solver", has_ejs(), "yt-dlp-ejs" if has_ejs() else
                 "yt-dlp-ejs is not installed - the JS runtime has no script to run"))
    if not has_ejs():
        missing.append(_FIXABLE["challenge solver"])

    probe = ffprobe_path()
    rows.append(("ffprobe", bool(probe), probe or
                 "not found (optional; only used to sanity-check clip lengths)"))
    return rows, missing


def _doctor(fix: bool) -> int:
    print(f"yt-extract {__version__}   ·   python {sys.version.split()[0]} on {sys.platform}\n")

    rows, missing = _probe()
    print("external programs")
    for label, ok, detail in rows:
        mark = "ok" if ok else ("--" if label == "ffprobe" else "MISS")
        print(f"  [{mark:4}] {label:17} {detail}")

    if missing and fix:
        code = _pip_install(sorted(set(missing)))
        if code != 0:
            print("\npip failed - see its output above")
            return code
        # The resolvers cache their answers, so re-probe in a fresh process.
        print("\nre-checking...")
        sys.stdout.flush()
        return subprocess.run([sys.executable, "-m", "yt_extract", "doctor"]).returncode

    print("\ntalking to YouTube")
    current = settings()
    if current.cookies_file:
        print(f"  [ok  ] cookies           file: {current.cookies_file}")
    elif current.cookies_from_browser:
        print(f"  [ok  ] cookies           browser: {current.cookies_from_browser}")
    else:
        print("  [--  ] cookies           none configured - fine until YouTube refuses you, then")
        print("                           use --cookies-from-browser firefox (or set")
        print("                           YT_EXTRACT_COOKIES_FROM_BROWSER=firefox)")

    print("\nmodel providers")
    statuses = llm.status()
    for name, available, hint in statuses:
        print(f"  [{'ok  ' if available else '--  '}] {name:17} {hint}")
    if not any(ok for name, ok, _ in statuses if name != "none"):
        print("\n  No model provider is set up. The tool still runs with --no-llm,")
        print("  but the screenshots are then chosen mechanically and are much weaker.")

    if missing:
        print(f"\nmissing: {', '.join(sorted(set(missing)))}")
        print("run `yt-extract doctor --fix` to install them into this environment")
        return 1
    print("\nready")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="yt-extract",
        description="Turn a YouTube video into a folder: a formatted transcript plus the "
                    "screenshots that matter.",
    )
    parser.add_argument("--version", action="version", version=f"yt-extract {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    _add_run_arguments(sub.add_parser("run", help="Transcript and screenshots for each URL."))
    _add_run_arguments(sub.add_parser("plan", help="Transcript and thin index only; no download."))
    doctor = sub.add_parser("doctor", help="Check requirements and report what is missing.")
    doctor.add_argument("--fix", action="store_true",
                        help="pip-install whatever is missing, into this environment.")

    args = parser.parse_args(argv)
    if args.command == "doctor":
        configure()
        return _doctor(args.fix)

    try:
        configure(
            cookies_file=args.cookies or "",
            cookies_from_browser=args.cookies_from_browser or "",
            extra_args=args.ytdlp_arg,
            use_node=not args.no_node,
        )
    except ExtractError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    failures = 0
    for url in args.urls:
        try:
            run_pipeline(
                url,
                Path(args.out),
                shots=args.shots,
                provider=args.provider,
                model=args.model,
                use_llm=not args.no_llm,
                lang=args.lang,
                burst=args.burst,
                shortlist=args.shortlist,
                spread=args.spread,
                keep_work=not args.clean,
                plan_only=args.command == "plan",
                log=lambda message: print(message, flush=True),
            )
        except ExtractError as exc:
            failures += 1
            print(f"\nerror: {url}\n{exc}\n", file=sys.stderr)
        except KeyboardInterrupt:
            print("\ninterrupted", file=sys.stderr)
            return 130
    return 1 if failures else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
