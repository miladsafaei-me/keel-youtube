"""The two questions this tool asks a model, and the exact JSON it expects back.

They live together in one file on purpose: these prompts and schemas are the
whole model-facing surface of the package, and keeping them in one readable place
is what lets someone change the tool's behaviour without reading its code.

Question 1 - "which seconds of this video are worth a picture?" - is answered
from the thin transcript alone; no video has been downloaded yet, which is why
only the chosen sections ever get fetched.

Question 2 - "which of these candidate frames is the best one?" - is answered by
looking at images. Both questions are asked once per video, covering every moment
in a single call, because one large request is far cheaper than many small ones.
"""

from __future__ import annotations

from pathlib import Path

MOMENTS_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["moments"],
    "properties": {
        "moments": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["timecode", "key", "label"],
                "properties": {
                    "timecode": {
                        "type": "string",
                        "description": "When the moment is on screen, as MM:SS or HH:MM:SS.",
                    },
                    "key": {
                        "type": "string",
                        "description": "Short kebab-case identifier, unique within this video.",
                    },
                    "label": {
                        "type": "string",
                        "description": "One plain sentence naming what should be visible.",
                    },
                },
            },
        }
    },
}

SELECTION_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["selections"],
    "properties": {
        "selections": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["key", "winner", "caption", "usable"],
                "properties": {
                    "key": {"type": "string", "description": "The moment key this answers."},
                    "winner": {
                        "type": "string",
                        "description": "Filename of the chosen candidate, exactly as given.",
                    },
                    "caption": {
                        "type": "string",
                        "description": "One short sentence describing what the image shows.",
                    },
                    "usable": {
                        "type": "boolean",
                        "description": "False when no candidate shows anything worth keeping.",
                    },
                },
            },
        }
    },
}


def moments_prompt(meta: dict, thin_path: Path, count: int) -> str:
    """Ask which seconds of the video deserve a screenshot."""
    return "\n".join([
        f"Read this timestamped transcript index: {thin_path.resolve()}",
        "",
        f"It is a video titled {meta.get('title', 'unknown')!r}"
        + (f" from the channel {meta['channel']!r}" if meta.get("channel") else "")
        + f", {int(meta.get('duration_seconds') or 0)} seconds long.",
        "",
        f"Choose the {count} moments where a screenshot of the video would add the most to a",
        "written article about it. Judge by what is being SHOWN, not by what sounds important:",
        "",
        "  - Prefer moments where the speaker is walking through something visual - a chart, a",
        "    diagram, a table of numbers, a settings panel, a result, a worked example.",
        "  - Prefer the moment the thing is fully drawn and explained over the moment it is",
        "    first mentioned. A few seconds later is usually the better picture.",
        "  - Skip introductions, sign-offs, sponsor reads, subscribe requests, and long stretches",
        "    of the speaker talking to the camera with nothing on screen.",
        "  - Spread the moments across the video rather than clustering them in one section.",
        "",
        "For each moment give:",
        "  timecode - when it is on screen, MM:SS or HH:MM:SS, inside the video's length.",
        "  key      - a short kebab-case id, unique in this video, e.g. 'opening-range-gap'.",
        "  label    - one plain sentence saying what should be visible at that moment.",
        "",
        "Return only the JSON object.",
    ])


def selection_prompt(moments: list[dict], candidates: dict[str, list[Path]]) -> str:
    """Ask which candidate frame best shows each moment."""
    lines = [
        "For each moment below, look at its candidate frames and choose the single best one.",
        "",
        "These are frames sampled a few seconds either side of one point in a video, so most",
        "moments have at least one good frame and one bad one. Judge them on this order:",
        "",
        "  1. Does it actually show the thing the moment's label describes?",
        "  2. Is the visual complete - the whole chart or panel in view, labels readable, not",
        "     cut off, not mid-scroll, not mid-transition, not blurred?",
        "  3. Is it free of clutter that does not belong in an article - a menu being dragged,",
        "     a half-open dialog, a webcam overlay covering the content?",
        "",
        "Prefer a frame showing the subject over a frame showing the presenter's face. If none",
        "of a moment's candidates is worth publishing, still name the least bad one as the",
        "winner but set usable to false.",
        "",
        "Write the caption as one plain sentence describing what the image shows, under 140",
        "characters. Do not mention the video, the presenter, or that it is a screenshot.",
        "",
    ]
    by_key = {m["key"]: m for m in moments}
    for key, files in candidates.items():
        label = by_key.get(key, {}).get("label", "")
        lines.append(f"MOMENT {key} - {label}")
        for path in files:
            lines.append(f"  {path.resolve()}")
        lines.append("")
    lines.append("Return one selection per moment, keyed by the moment id. Return only the JSON object.")
    return "\n".join(lines)


def parse_timecode(value: str) -> float:
    """`MM:SS` or `HH:MM:SS` (or a bare number of seconds) as seconds."""
    text = str(value or "").strip()
    if not text:
        return 0.0
    parts = text.split(":")
    try:
        numbers = [float(p) for p in parts]
    except ValueError:
        return 0.0
    seconds = 0.0
    for number in numbers:
        seconds = seconds * 60 + number
    return seconds
