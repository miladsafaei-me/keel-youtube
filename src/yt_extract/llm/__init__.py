"""Provider selection.

The order below is the whole policy: an explicit choice wins; otherwise the
Claude Code CLI is preferred because a colleague who has it needs no key and no
extra install; API keys come next; and the no-model path is never chosen
automatically, because its output is visibly worse and that should be a decision,
not an accident.
"""

from __future__ import annotations

from ..errors import LLMError
from .anthropic_api import AnthropicProvider
from .base import Provider, parse_json_object
from .claude_cli import ClaudeCLIProvider
from .gemini import GeminiProvider
from .none import NoneProvider

#: Auto-detection order.
PROVIDERS: tuple[type[Provider], ...] = (ClaudeCLIProvider, AnthropicProvider, GeminiProvider)

#: Everything selectable by name via --provider.
BY_NAME: dict[str, type[Provider]] = {
    cls.name: cls for cls in (*PROVIDERS, NoneProvider)
}


def resolve(name: str | None = None, model: str | None = None) -> Provider:
    """The provider to use, by name or by auto-detection."""
    if name:
        cls = BY_NAME.get(name)
        if cls is None:
            raise LLMError(
                f"unknown provider {name!r}. Choose one of: {', '.join(sorted(BY_NAME))}"
            )
        if not cls.available():
            raise LLMError(f"provider {name!r} is not usable here - {cls.setup_hint}")
        return cls(model)

    for cls in PROVIDERS:
        if cls.available():
            return cls(model)

    raise LLMError(
        "no model provider is available. Set one of these up:\n"
        + "\n".join(f"  - {cls.name}: {cls.setup_hint}" for cls in PROVIDERS)
        + "\n  - or run with --no-llm to use the deterministic path (lower quality)."
    )


def status() -> list[tuple[str, bool, str]]:
    """`(name, available, hint)` for every provider, for the doctor command."""
    return [(cls.name, cls.available(), cls.setup_hint) for cls in (*PROVIDERS, NoneProvider)]


__all__ = ["Provider", "PROVIDERS", "BY_NAME", "resolve", "status", "parse_json_object",
           "ClaudeCLIProvider", "AnthropicProvider", "GeminiProvider", "NoneProvider"]
