# Working on keel-youtube

Read this before changing anything. It is written for whatever agent or editor is
driving — Claude Code, Cursor, Copilot, Codex, a human.

## What this tool is

One YouTube URL in, one folder out:

```
out/<video-id>/
  transcript.md     readable transcript with timecodes, screenshots placed inline
  screenshots/      the chosen frames, one per moment
  video.json        metadata plus every decision the run made
  work/             intermediates and the two cached model answers
```

That folder shape **is the product**. It is what every caller depends on, so
treat it as frozen: adding a file is fine, renaming or removing one is a breaking
change.

## What this tool is not

It has no database, no CMS, no publishing step, no content model, no notion of
articles, topics, categories or SEO. It does not decide what the video is about
or what should be written from it. If a change would teach it any of that, the
change belongs in the caller, not here.

## Layout

| File | Holds |
|---|---|
| `ids.py` | the only place that knows what a YouTube URL looks like |
| `binaries.py` | finding and running `yt-dlp` / `ffmpeg`; the only `subprocess` helper |
| `subtitles.py` | caption download and parsing into timestamped segments |
| `transcript.py` | segments → `transcript.md` and the thin index; no I/O beyond writing |
| `frames.py` | section download, frame bursts, the detail score, slugs |
| `prompts.py` | both prompts and both JSON schemas — the entire model-facing surface |
| `llm/` | one file per provider, all behind one interface |
| `pipeline.py` | the orchestration, and the only module that knows the folder shape |
| `cli.py` | argument parsing only |

## The run, in order

1. Read metadata, download captions, parse them **keeping timestamps**. Timestamps
   are the whole reason screenshots are possible; never drop them.
2. Write `transcript.md` and `work/thin.txt` (roughly one line per 30s).
3. Ask a model which moments deserve a picture — **before any video is downloaded**.
4. Download only those few seconds, at low resolution, and capture a burst of
   frames around each moment.
5. Shortlist the busiest frames mechanically, then ask a model to pick the winner
   and caption it.
6. Copy winners into `screenshots/`, rewrite `transcript.md` with them in place,
   write `video.json`.

## Rules

- **This repo stays self-contained.** Its dependencies are public PyPI packages and
  nothing else: never add a private, internal or git-URL dependency, never import
  from another of the author's projects, and never copy code in from one. It is
  shared with people who have access to nothing else, and that must stay true.
- **Network access lives in exactly two places:** `binaries.py` (which runs
  `yt-dlp`) and `llm/`. Nothing else may open a socket or shell out.
- **No secret ever appears in code, tests or committed files.** Keys are read from
  the environment inside a provider and nowhere else.
- **Never take one frame per moment.** The burst-then-choose pass is the reason
  the output is usable; a single frame is very often a face or a cross-fade.
- **Both model answers stay cached** in `work/moments.json` and
  `work/selection.json`. They are plain, hand-editable JSON, and a re-run must
  reuse them rather than paying again.
- **Every failure raises a subclass of `KeelYoutubeError`** with a message naming
  the fix. `MissingRequirement` in particular must always print the exact install
  command.
- **Comments explain why, not what.** Do not narrate the code beneath them.
- **English only**, in code, comments, docs and commit messages.

## Running it

```bash
python -m venv .venv && ./.venv/bin/pip install -e .
./.venv/bin/keel-youtube doctor
./.venv/bin/python -m unittest discover -s tests
./.venv/bin/keel-youtube run "<url>" --out ./out
```

Tests are offline and free — they cover parsing, grouping, timecodes, slugs and
the JSON reader, which is where the bugs actually are. Adding a test that needs
the network or a model is not an improvement.

To exercise the pipeline without spending anything, use `--no-llm`, or re-run a
video that already has a `work/` directory.

## The model layer

Specified in [docs/llm-contract.md](docs/llm-contract.md). Read it before touching
anything under `llm/` or in `prompts.py`.
