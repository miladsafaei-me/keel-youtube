"""Google Gemini through an API key.

Spoken over plain REST with the standard library rather than through Google's
SDK, so choosing Gemini still costs this package zero dependencies. The request
shape used here (`contents` -> `parts`, with `inline_data` for images) is the
long-stable v1beta generateContent contract.
"""

from __future__ import annotations

import base64
import json
import os
import urllib.error
import urllib.request
from pathlib import Path

from ..errors import LLMError
from .base import Provider, parse_json_object

_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
_MEDIA_TYPES = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}


class GeminiProvider(Provider):
    name = "gemini"
    setup_hint = "export GEMINI_API_KEY=... (get one at https://aistudio.google.com/apikey)"

    @property
    def default_model(self) -> str:
        # Overridable with --model; Google renames models faster than this file
        # is likely to be revised.
        return os.environ.get("GEMINI_MODEL") or "gemini-2.5-flash"

    @classmethod
    def available(cls) -> bool:
        return bool(os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"))

    def ask(self, prompt: str, schema: dict, images: list[Path] | None = None) -> dict:
        key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        if not key:
            raise LLMError(f"no Gemini API key - {self.setup_hint}")

        parts: list[dict] = []
        for path in images or []:
            media_type = _MEDIA_TYPES.get(path.suffix.lower())
            if not media_type:
                raise LLMError(f"unsupported image type for {path.name}")
            parts.append({
                "inline_data": {
                    "mime_type": media_type,
                    "data": base64.standard_b64encode(path.read_bytes()).decode("ascii"),
                }
            })
            parts.append({"text": f"(the image above is {path.name})"})
        parts.append({"text": prompt})

        payload = {
            "contents": [{"role": "user", "parts": parts}],
            "generationConfig": {
                "responseMimeType": "application/json",
                "responseSchema": _to_gemini_schema(schema),
            },
        }
        request = urllib.request.Request(
            _ENDPOINT.format(model=self.model),
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", "x-goog-api-key": key},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=600) as response:
                body = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raise LLMError(f"the Gemini API returned {exc.code}: {exc.read()[:300]!r}") from exc
        except urllib.error.URLError as exc:
            raise LLMError(f"could not reach the Gemini API: {exc.reason}") from exc

        try:
            text = body["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMError(f"unexpected Gemini response shape: {json.dumps(body)[:300]}") from exc
        return parse_json_object(text)


def _to_gemini_schema(schema: dict) -> dict:
    """Strip the JSON Schema keywords Gemini's response schema rejects."""
    if not isinstance(schema, dict):
        return schema
    out = {k: v for k, v in schema.items() if k not in ("additionalProperties", "$schema", "title")}
    if isinstance(out.get("properties"), dict):
        out["properties"] = {k: _to_gemini_schema(v) for k, v in out["properties"].items()}
    if isinstance(out.get("items"), dict):
        out["items"] = _to_gemini_schema(out["items"])
    return out
