"""Anthropic through an API key, using the official SDK.

Installed on demand (`pip install keel-youtube[anthropic]`) so the base package
keeps no model dependency at all.
"""

from __future__ import annotations

import base64
import os
from pathlib import Path

from ..errors import LLMError
from .base import Provider, parse_json_object

_MEDIA_TYPES = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}


class AnthropicProvider(Provider):
    name = "anthropic"
    setup_hint = "export ANTHROPIC_API_KEY=... and run: pip install keel-youtube[anthropic]"

    @property
    def default_model(self) -> str:
        return "claude-sonnet-5"

    @classmethod
    def available(cls) -> bool:
        if not os.environ.get("ANTHROPIC_API_KEY"):
            return False
        try:
            import anthropic  # noqa: F401
        except ImportError:
            return False
        return True

    def ask(self, prompt: str, schema: dict, images: list[Path] | None = None) -> dict:
        try:
            import anthropic
        except ImportError as exc:
            raise LLMError(f"the anthropic package is not installed - {self.setup_hint}") from exc

        content: list[dict] = []
        for path in images or []:
            media_type = _MEDIA_TYPES.get(path.suffix.lower())
            if not media_type:
                raise LLMError(f"unsupported image type for {path.name}")
            content.append({
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": media_type,
                    "data": base64.standard_b64encode(path.read_bytes()).decode("ascii"),
                },
            })
            content.append({"type": "text", "text": f"(the image above is {path.name})"})
        content.append({"type": "text", "text": _with_schema(prompt, schema)})

        client = anthropic.Anthropic()
        try:
            response = client.messages.create(
                model=self.model,
                max_tokens=8000,
                messages=[{"role": "user", "content": content}],
            )
        except Exception as exc:  # the SDK raises a family of API errors
            raise LLMError(f"the Anthropic API call failed: {exc}") from exc

        text = "".join(block.text for block in response.content if block.type == "text")
        return parse_json_object(text)


def _with_schema(prompt: str, schema: dict) -> str:
    import json

    return (
        f"{prompt}\n\nReply with a single JSON object and nothing else. "
        f"It must match this JSON Schema:\n{json.dumps(schema, indent=2)}"
    )
