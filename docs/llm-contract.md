# The model layer

Everything this tool asks a language model, and everything it will accept back.
Read this before changing `prompts.py` or anything under `src/yt_extract/llm/`.

## A model is used at exactly two points

Nowhere else in the package calls a model, and nothing else may start to.

| # | Question | Sees | Answers with |
|---|---|---|---|
| 1 | Which seconds of this video deserve a screenshot? | `work/thin.txt` — the transcript at about one line per 30s | `MOMENTS_SCHEMA` |
| 2 | Which candidate frame best shows each moment, and what is its caption? | the shortlisted JPEGs | `SELECTION_SCHEMA` |

Question 1 runs **before any video is downloaded** — that is what lets the tool
fetch a few seconds instead of a whole file. Question 2 runs after the frames
exist.

Both are asked **once per video**, covering every moment in a single call
(question 2 in chunks of `SELECTION_CHUNK` moments). One large request costs far
less than many small ones, and a model comparing all the moments at once is more
consistent than one judging each in isolation.

## The two schemas

Both are closed objects (`additionalProperties: false`), defined in `prompts.py`.
They are the contract; the prose in the prompts only explains how to fill them.

```jsonc
// 1 - moments
{"moments": [{
  "timecode": "14:34",                    // MM:SS or HH:MM:SS, inside the video
  "key": "venom-candle-formation",        // kebab-case, unique in this video
  "label": "The Venom candlestick fully drawn on the chart."
}]}

// 2 - selection
{"selections": [{
  "key": "venom-candle-formation",        // the moment this answers
  "winner": "venom-candle-formation_880s.jpg",  // a candidate filename, verbatim
  "caption": "E-mini Nasdaq-100 1-minute chart with the marked candle at 19,020.",
  "usable": true                          // false when nothing was worth keeping
}]}
```

The pipeline never trusts these blindly: timecodes outside the video's length are
dropped, keys are re-slugified and de-duplicated, and a `winner` that does not
name a real candidate falls back to the highest-detail frame.

## Both answers are cached, and both are editable

They are written to `work/moments.json` and `work/selection.json` as plain JSON.
A re-run reads them instead of asking again, so:

- iterating on the rest of the pipeline costs nothing after the first run;
- correcting a bad choice by hand means editing a file and re-running, not
  re-prompting;
- deleting one file re-asks exactly that one question.

`yt-extract plan <url>` stops right after `work/thin.txt` is written, so
`moments.json` can be authored by hand from the start.

## Providers

Four implementations of one interface in `llm/base.py`:

```python
class Provider:
    name: str
    setup_hint: str                       # printed when it is unavailable
    @classmethod
    def available(cls) -> bool            # can it actually run right now?
    def ask(self, prompt, schema, images=None) -> dict
```

| Provider | Auth | Dependencies | Notes |
|---|---|---|---|
| `claude-cli` | an installed, signed-in Claude Code | none | **the default** |
| `anthropic` | `ANTHROPIC_API_KEY` | `yt-extract[anthropic]` | official SDK |
| `gemini` | `GEMINI_API_KEY` | none | plain REST |
| `none` | — | none | `--no-llm`; deterministic, never auto-selected |

Auto-detection order is `claude-cli` → `anthropic` → `gemini`. `claude-cli` leads
because a colleague who already has Claude Code needs no key and no install.
`none` is never chosen automatically: its output is visibly worse, and that
should be a decision rather than a surprise.

### Adding a provider

One new file in `llm/`, and its class added to `PROVIDERS` in `llm/__init__.py`.
Nothing else changes — no other module imports a provider or branches on one.

### Why `claude-cli` is invoked the way it is

Left to its defaults the CLI loads the running user's personal instruction files,
settings, hooks, plugins and MCP servers. That is expensive, and worse, it makes
the tool non-reproducible: two colleagues would get different screenshots from
the same video because of rules neither wrote for this tool. So every call passes
its own `--system-prompt`, `--setting-sources ""`, `--strict-mcp-config`,
`--disable-slash-commands`, and `--allowed-tools Read`. Do not remove these.

Note that `--bare` is **not** usable here: it disables OAuth, so it would break
the very subscription path this provider exists to use.

### How each provider sees images

`claude-cli` is given absolute paths and reads them with its own Read tool. The
API providers inline the bytes as base64. A provider that cannot see images must
raise `LLMError` rather than answer blind.

## Output parsing

`parse_json_object` in `llm/base.py` accepts a bare object, a fenced object, or
an object embedded in prose, and raises `LLMError` otherwise. Models wrap JSON in
explanation often enough that demanding a bare object would reject good answers.
`claude-cli` additionally passes the schema via `--json-schema` and prefers the
CLI's own `structured_output` field when present.

## What the model is deliberately not asked

- What the video is *about*, or what should be written from it. That is the
  caller's decision, and putting it here would make the tool opinionated about a
  domain it does not know.
- To transcribe audio. Captionless videos raise `TranscriptUnavailable`; adding
  Whisper would turn a zero-key tool into one needing a GPU or a budget to start.
- To crop, edit or generate images. Frames are captured as they appear.

## Failure behaviour

If question 2 fails, the run does not abort: it falls back to the highest-detail
frame per moment, logs why, and finishes. A video is worth more with mediocre
screenshots than with none. Question 1 failing does abort, because there is
nothing sensible to capture without moments — except under `--no-llm`, where
moments are spread evenly instead.
