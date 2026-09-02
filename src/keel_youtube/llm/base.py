"""The provider contract.

Everything the rest of the package knows about language models is this one
method. Adding a model means adding a file here that implements it; no other
module in the package imports a provider directly, and none of them contains a
provider-specific branch.
"""

from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod
from pathlib import Path

from ..errors import LLMError

_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


class Provider(ABC):
    """A model that can answer a prompt with JSON, optionally after looking at images."""

    name: str = "base"
    #: Human-readable instruction shown when this provider is unavailable.
    setup_hint: str = ""

    def __init__(self, model: str | None = None) -> None:
        self.model = model or self.default_model

    @property
    def default_model(self) -> str:
        return ""

    @classmethod
    @abstractmethod
    def available(cls) -> bool:
        """True when this provider can actually run right now."""

    @abstractmethod
    def ask(self, prompt: str, schema: dict, images: list[Path] | None = None) -> dict:
        """Answer `prompt` as a JSON object matching `schema`.

        `images` are local files the model must look at. A provider that cannot
        see images raises LLMError rather than silently answering blind.
        """


def parse_json_object(raw: str) -> dict:
    """The first JSON object in a model's reply.

    Models wrap JSON in prose or code fences often enough that demanding a bare
    object would fail on perfectly good answers.
    """
    text = (raw or "").strip()
    if not text:
        raise LLMError("the model returned an empty response")

    fenced = _FENCE_RE.search(text)
    if fenced:
        text = fenced.group(1).strip()

    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end <= start:
            raise LLMError(f"no JSON object in the model's response: {text[:300]!r}") from None
        try:
            value = json.loads(text[start:end + 1])
        except json.JSONDecodeError as exc:
            raise LLMError(f"the model's JSON did not parse: {exc}") from exc

    if not isinstance(value, dict):
        raise LLMError(f"expected a JSON object, got {type(value).__name__}")
    return value
