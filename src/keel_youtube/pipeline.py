"""The run: one YouTube URL in, one folder out.

    out/<video-id>/
      transcript.md     the readable transcript, screenshots placed in it
      screenshots/      the chosen frames, named after what they show
      video.json        metadata plus every decision this run made
      work/             intermediates (thin index, candidates, sections)

`work/` is what makes a second run of the same video nearly free: both model
answers are cached there as JSON, and both are plain files anyone can edit by
hand to correct a choice and re-run.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from . import frames as frames_mod
from . import prompts, subtitles, transcript
from .errors import KeelYoutubeError, LLMError
from .ids import canonical_url, video_id
from .llm import resolve as resolve_provider
from .llm.none import NoneProvider

#: How many moments are judged in one model call. Keeping a call bounded stops a
#: two-hour video from building a request nothing will answer.
SELECTION_CHUNK = 6


def _noop(message: str) -> None:
    pass


def run(
    url: str,
    out_dir: Path | str,
    *,
    shots: int = 6,
    provider: str | None = None,
    model: str | None = None,
    use_llm: bool = True,
    lang: str = "en",
    burst: int = 5,
    shortlist: int = 3,
    spread: float = 6.0,
    keep_work: bool = True,
    plan_only: bool = False,
    log=_noop,
) -> dict:
    """Produce the output folder for one video and return its manifest."""
    vid = video_id(url)
    if not vid:
        raise KeelYoutubeError(f"not a recognizable YouTube URL: {url!r}")
    url = canonical_url(url)

    root = Path(out_dir).expanduser().resolve() / vid
    work = root / "work"
    shots_dir = root / "screenshots"
    work.mkdir(parents=True, exist_ok=True)

    log(f"[1/6] reading video metadata ({vid})")
    meta = subtitles.fetch_metadata(url)
    meta["url"] = url
    meta["video_id"] = vid

    log("[2/6] downloading captions")
    caption_file = subtitles.download_captions(url, work, lang=lang)
    segments = subtitles.parse(caption_file)
    log(f"      {len(segments)} caption lines, {len(transcript.full_text(segments).split())} words")

    thin_path = transcript.write_text(work / "thin.txt", transcript.thin_index(segments))
    transcript.write_text(root / "transcript.md", transcript.render_markdown(meta, segments))
    if plan_only:
        log(f"      wrote {thin_path} - add work/moments.json and re-run to continue")
        return _manifest(root, meta, [], [], written=["transcript.md", "work/thin.txt"])

    engine = None if not use_llm else resolve_provider(provider, model)
    if engine is not None and isinstance(engine, NoneProvider):
        engine = None
    log(f"[3/6] choosing {shots} moments" + (f" via {engine.name}/{engine.model}" if engine else " evenly (no model)"))
    moments = _choose_moments(engine, meta, thin_path, shots, work, log)
    if not moments:
        log("      no moments chosen - finishing with the transcript only")
        return _manifest(root, meta, [], [], written=["transcript.md"])

    log(f"[4/6] capturing {burst} candidate frames around each of {len(moments)} moments")
    duration = float(meta.get("duration_seconds") or 0) or None
    candidates: dict[str, list[Path]] = {}
    for moment in moments:
        found = frames_mod.capture_moment(
            url, moment["second"], moment["key"], work,
            count=burst, spread=spread, duration=duration,
        )
        if found:
            candidates[moment["key"]] = found[:max(1, shortlist)]
            log(f"      {moment['key']}: {len(found)} frames")
        else:
            log(f"      {moment['key']}: no frames (section download failed)")
    if not candidates:
        raise KeelYoutubeError("no frames could be captured for any moment")

    log("[5/6] choosing the best frame per moment")
    selections = _choose_frames(engine, moments, candidates, work, log)

    log("[6/6] assembling the output folder")
    chosen = _place_screenshots(moments, candidates, selections, shots_dir)
    transcript.write_text(root / "transcript.md", transcript.render_markdown(meta, segments, chosen))
    manifest = _manifest(root, meta, moments, chosen,
                         written=["transcript.md", "screenshots/", "video.json"])
    (root / "video.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")

    if not keep_work:
        shutil.rmtree(work, ignore_errors=True)
    log(f"done: {root}")
    return manifest


def _choose_moments(engine, meta: dict, thin_path: Path, count: int, work: Path, log) -> list[dict]:
    """The moments to screenshot, from cache, from a model, or evenly spread."""
    cache = work / "moments.json"
    if cache.is_file():
        log("      reusing work/moments.json")
        raw = json.loads(cache.read_text(encoding="utf-8"))
    elif engine is None:
        raw = {"moments": _even_moments(float(meta.get("duration_seconds") or 0), count)}
    else:
        raw = engine.ask(prompts.moments_prompt(meta, thin_path, count), prompts.MOMENTS_SCHEMA)
        cache.write_text(json.dumps(raw, indent=2, ensure_ascii=False), encoding="utf-8")

    duration = float(meta.get("duration_seconds") or 0)
    out: list[dict] = []
    seen: set[str] = set()
    for entry in raw.get("moments", []):
        second = prompts.parse_timecode(entry.get("timecode", ""))
        if duration and not 0 < second < duration:
            continue
        key = frames_mod.slugify(entry.get("key") or entry.get("label") or f"moment-{len(out) + 1}", max_length=40)
        while key in seen:
            key = f"{key}-2"
        seen.add(key)
        out.append({"second": second, "key": key, "label": str(entry.get("label") or "").strip()})
    return sorted(out, key=lambda m: m["second"])


def _even_moments(duration: float, count: int) -> list[dict]:
    """Moments spread evenly across the video - the no-model fallback."""
    if duration <= 0 or count <= 0:
        return []
    step = duration / (count + 1)
    return [
        {
            "timecode": transcript.timecode(step * (i + 1)),
            "key": f"moment-{i + 1}",
            "label": f"whatever is on screen at {transcript.timecode(step * (i + 1))}",
        }
        for i in range(count)
    ]


def _choose_frames(engine, moments: list[dict], candidates: dict[str, list[Path]],
                   work: Path, log) -> dict[str, dict]:
    """The winning frame per moment, from cache, from a model, or by detail score."""
    cache = work / "selection.json"
    if cache.is_file():
        log("      reusing work/selection.json")
        raw = json.loads(cache.read_text(encoding="utf-8"))
        return {s["key"]: s for s in raw.get("selections", []) if s.get("key")}

    by_key = {m["key"]: m for m in moments}
    if engine is None:
        # Candidates arrive sorted by detail, so the first is the busiest frame.
        selections = [
            {"key": key, "winner": files[0].name,
             "caption": by_key.get(key, {}).get("label", ""), "usable": True}
            for key, files in candidates.items() if files
        ]
    else:
        selections = []
        keys = list(candidates)
        for start in range(0, len(keys), SELECTION_CHUNK):
            chunk = {k: candidates[k] for k in keys[start:start + SELECTION_CHUNK]}
            images = [path for files in chunk.values() for path in files]
            chunk_moments = [by_key[k] for k in chunk if k in by_key]
            try:
                answer = engine.ask(
                    prompts.selection_prompt(chunk_moments, chunk),
                    prompts.SELECTION_SCHEMA,
                    images=images,
                )
            except LLMError as exc:
                log(f"      model could not choose ({exc}); falling back to detail score")
                answer = {"selections": [
                    {"key": k, "winner": v[0].name,
                     "caption": by_key.get(k, {}).get("label", ""), "usable": True}
                    for k, v in chunk.items() if v
                ]}
            selections.extend(answer.get("selections", []))
        cache.write_text(json.dumps({"selections": selections}, indent=2, ensure_ascii=False),
                         encoding="utf-8")
    return {s["key"]: s for s in selections if s.get("key")}


def _place_screenshots(moments: list[dict], candidates: dict[str, list[Path]],
                       selections: dict[str, dict], shots_dir: Path) -> list[dict]:
    """Copy each winner into `screenshots/` under a name that says what it shows.

    The filename leads with the video second, zero-padded, so a directory listing
    is in the order the images appear in the video.
    """
    shots_dir.mkdir(parents=True, exist_ok=True)
    placed: list[dict] = []
    for moment in moments:
        key = moment["key"]
        files = candidates.get(key) or []
        if not files:
            continue
        choice = selections.get(key) or {}
        winner = next((p for p in files if p.name == choice.get("winner")), files[0])
        caption = str(choice.get("caption") or moment.get("label") or key).strip()
        second = frames_mod.second_from_name(winner) or moment["second"]
        # Named from the moment key, not the caption: a caption is a sentence and
        # would truncate mid-word. The second leads so a listing sorts in video order.
        name = f"{int(second):05d}-{frames_mod.slugify(key)}.jpg"
        shutil.copy2(winner, shots_dir / name)
        placed.append({
            "key": key,
            "second": second,
            "timecode": transcript.timecode(second),
            "file": name,
            "caption": caption,
            "usable": bool(choice.get("usable", True)),
            "candidates": [p.name for p in files],
        })
    return sorted(placed, key=lambda s: s["second"])


def _manifest(root: Path, meta: dict, moments: list[dict], shots: list[dict],
              *, written: list[str]) -> dict:
    return {
        "video": meta,
        "output_dir": str(root),
        "written": written,
        "moments": moments,
        "screenshots": shots,
    }
