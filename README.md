# keel-youtube

Turn a YouTube video into a folder: a formatted transcript, and the screenshots
that actually carry the video's meaning.

```
out/dQw4w9WgXcQ/
  transcript.md     readable transcript, timestamped, screenshots placed in it
  screenshots/      00090-opening-range-gap-high-and-low.jpg, ...
  video.json        metadata and every decision the run made
  work/             intermediates; delete freely, or keep to re-run for free
```

It does one job and has no opinion about what you do with the result. There is no
database, no CMS, no publishing step, no content model.

## Install

```bash
pip install git+https://github.com/miladsafaei-me/keel-youtube
keel-youtube doctor
```

`yt-dlp` and `ffmpeg` come with it — both are pip-installable, so there is
nothing to set up by hand. `doctor` tells you if anything is missing anyway.

## Use

```bash
keel-youtube run "https://www.youtube.com/watch?v=VIDEO_ID" --out ./out
```

That is the whole interface. Useful flags:

| Flag | What it does |
|---|---|
| `--shots 10` | How many screenshots to take (default 6) |
| `--out DIR` | Where the per-video folders go (default `./out`) |
| `--provider` | Force `claude-cli`, `anthropic`, `gemini` or `none` |
| `--no-llm` | Run with no model at all — much weaker output, but free |
| `--clean` | Delete `work/` when the run succeeds |
| `--lang de` | Prefer a different caption language |

`keel-youtube plan <url>` stops after the transcript, so you can write
`work/moments.json` yourself and re-run to pick the moments by hand.

## How the screenshots get chosen

A single frame at a given second is usually the presenter's face, a cursor
mid-move, or a cross-fade. So:

1. A model reads the timestamped transcript and names the moments worth a
   picture — before anything is downloaded.
2. Only those few seconds of video are downloaded, at low resolution.
3. Several frames are captured around each moment, not one.
4. The busiest frames are shortlisted mechanically, then a model looks at them
   and picks the winner and writes its caption.

Both model answers are cached in `work/` as plain JSON. Edit either file and
re-run to override a choice at no cost.

## Which model it uses

Auto-detected in this order, and `--provider` overrides it:

1. **`claude-cli`** — an installed, signed-in [Claude Code](https://claude.com/claude-code).
   No API key, no extra install. This is the default.
2. **`anthropic`** — `ANTHROPIC_API_KEY` plus `pip install keel-youtube[anthropic]`.
3. **`gemini`** — `GEMINI_API_KEY`. Uses plain REST; no SDK needed.
4. **`none`** — `--no-llm`. Never chosen automatically.

## Requirements

Python 3.10+. Captions must exist on the video — audio transcription is out of
scope.

## Working on this repo

Read [AGENTS.md](AGENTS.md) first. The model layer is specified in
[docs/llm-contract.md](docs/llm-contract.md).
