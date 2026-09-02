# yt-extract

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
pip install git+https://github.com/miladsafaei-me/yt-extract
yt-extract doctor
```

Everything it needs comes with it — `yt-dlp`, `ffmpeg`, a JavaScript runtime and
YouTube's challenge-solver scripts are all pip-installable, so there is nothing
to set up by hand. `doctor` reports anything missing, and `doctor --fix`
installs it into the same environment.

`ytx` is a shorter alias for every command below.

### On Windows

```powershell
py -m pip install git+https://github.com/miladsafaei-me/yt-extract
py -m yt_extract doctor
py -m yt_extract run "https://www.youtube.com/watch?v=VIDEO_ID" --out .\out
```

Use `py -m yt_extract` rather than the `yt-extract` command: pip puts console
scripts in a `Scripts\` folder that is usually not on PATH, and `python` is often
not a recognised command on Windows while `py` always is. Chain commands with
`;`, not `&` — PowerShell reserves `&`.

## Use

```bash
yt-extract run "https://www.youtube.com/watch?v=VIDEO_ID" --out ./out
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

`yt-extract plan <url>` stops after the transcript, so you can write
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
2. **`anthropic`** — `ANTHROPIC_API_KEY` plus `pip install yt-extract[anthropic]`.
3. **`gemini`** — `GEMINI_API_KEY`. Uses plain REST; no SDK needed.
4. **`none`** — `--no-llm`. Never chosen automatically.

## When YouTube refuses

YouTube does not serve every request anonymously. When it refuses, extraction
fails with `Sign in to confirm you're not a bot`, `The page needs to be
reloaded`, or a bare "could not read metadata". Retrying does not help; give it a
browser session instead:

```bash
yt-extract run "<url>" --out ./out --cookies-from-browser firefox
```

Try it in this order:

**1. No cookies at all.** Invalid cookies are worse than none, and this tool
supplies the JavaScript runtime YouTube requires. Try a plain run first.

**2. Firefox.** Log in to YouTube in Firefox, **close Firefox completely**, then
run with `--cookies-from-browser firefox`.

**Chrome does not work for this on Windows.** Since Chrome 127 its cookies are
encrypted with a key bound to the Chrome process, so nothing outside Chrome can
read them — that is the `Could not copy Chrome cookie database` error, and it
has no workaround. Use Firefox or an exported file instead.

**3. An exported `cookies.txt`.** The export has to be done a specific way or
YouTube invalidates it within minutes, because it rotates the session on every
open YouTube tab:

1. Open a **private / incognito** window and log in to YouTube.
2. In that same window, go to `https://www.youtube.com/robots.txt`.
3. Export `youtube.com` cookies with a cookies.txt browser extension.
4. **Close the private window** without logging out.

```bash
yt-extract run "<url>" --out ./out --cookies /path/to/cookies.txt
```

If a cookie file that used to work stops working, this is why — the message is
`The provided YouTube account cookies are no longer valid`. Re-export it the
same way.

To set it once instead of on every command, use an environment variable:
`YT_EXTRACT_COOKIES_FROM_BROWSER=firefox` or `YT_EXTRACT_COOKIES=/path/to/cookies.txt`.

Two more things worth knowing:

- **`pip install -U yt-dlp` is the first fix for almost any extraction failure.**
  YouTube changes often, and yt-dlp is the piece that tracks those changes.
- **`--ytdlp-arg` passes anything straight through to yt-dlp**, repeatable, for
  options this tool does not wrap: `--ytdlp-arg --extractor-args --ytdlp-arg
  youtube:player_client=web`.

## Requirements

Python 3.10+ and nothing else installed by hand. Captions must exist on the
video — audio transcription is out of scope.

## Working on this repo

Read [AGENTS.md](AGENTS.md) first. The model layer is specified in
[docs/llm-contract.md](docs/llm-contract.md).

## License

MIT — see [LICENSE](LICENSE). Use it, change it, ship it; just keep the copyright
notice.
