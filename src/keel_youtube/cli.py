"""The command line.

    keel-youtube run <url> --out ./out      the whole thing
    keel-youtube plan <url> --out ./out     stop after the transcript
    keel-youtube doctor                     what is installed, what is missing
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__, llm
from .binaries import ffmpeg_path, ffprobe_path, ytdlp_path
from .errors import KeelYoutubeError
from .pipeline import run as run_pipeline


def _add_run_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("urls", nargs="+", metavar="URL", help="One or more YouTube URLs.")
    parser.add_argument("--out", default="./out", help="Where the per-video folders go (default: ./out).")
    parser.add_argument("--shots", type=int, default=6, help="How many screenshots to take (default: 6).")
    parser.add_argument("--lang", default="en", help="Caption language to prefer (default: en).")
    parser.add_argument("--provider", choices=sorted(llm.BY_NAME),
                        help="Force a model provider instead of auto-detecting.")
    parser.add_argument("--model", help="Model name for the chosen provider.")
    parser.add_argument("--no-llm", action="store_true",
                        help="Run without any model: evenly spaced moments, busiest frame wins.")
    parser.add_argument("--burst", type=int, default=5,
                        help="Frames captured around each moment (default: 5).")
    parser.add_argument("--shortlist", type=int, default=3,
                        help="How many of those frames the model is shown (default: 3).")
    parser.add_argument("--spread", type=float, default=6.0,
                        help="Seconds either side of a moment to sample (default: 6).")
    parser.add_argument("--clean", action="store_true", help="Delete work/ when the run succeeds.")


def _doctor() -> int:
    print(f"keel-youtube {__version__}\n")
    ok = True

    print("external programs")
    for label, resolver in (("yt-dlp", ytdlp_path), ("ffmpeg", ffmpeg_path)):
        try:
            print(f"  [ok]   {label:8} {resolver()}")
        except KeelYoutubeError as exc:
            ok = False
            print(f"  [MISS] {label:8} {exc}")
    probe = ffprobe_path()
    print(f"  [ok]   {'ffprobe':8} {probe}" if probe
          else "  [--]   ffprobe  not found (optional; only used to sanity-check clip lengths)")

    print("\nmodel providers")
    for name, available, hint in llm.status():
        print(f"  [{'ok' if available else '--'}]   {name:12} {hint}")
    if not any(available for name, available, _ in llm.status() if name != "none"):
        print("\n  No model provider is set up. The tool still runs with --no-llm,")
        print("  but the screenshots will be chosen mechanically and are much weaker.")

    print("\nready" if ok else "\nsomething is missing - see the lines marked MISS above")
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="keel-youtube",
        description="Turn a YouTube video into a folder: a formatted transcript plus the "
                    "screenshots that matter.",
    )
    parser.add_argument("--version", action="version", version=f"keel-youtube {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    _add_run_arguments(sub.add_parser("run", help="Transcript and screenshots for each URL."))
    plan = sub.add_parser("plan", help="Transcript and thin index only; stop before any download.")
    _add_run_arguments(plan)
    sub.add_parser("doctor", help="Check requirements and report what is missing.")

    args = parser.parse_args(argv)
    if args.command == "doctor":
        return _doctor()

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
        except KeelYoutubeError as exc:
            failures += 1
            print(f"error: {url}: {exc}", file=sys.stderr)
        except KeyboardInterrupt:
            print("\ninterrupted", file=sys.stderr)
            return 130
    return 1 if failures else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
