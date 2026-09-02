"""The no-model provider.

Selected with `--no-llm`, and used automatically in tests. It answers both of the
tool's questions without a model at all:

- which moments matter -> spread evenly across the video, since with no
  understanding of the content one position is as defensible as another;
- which candidate frame wins -> the one with the most visual detail, which the
  caller has already sorted to the front.

The results are workable, not good. That is the honest trade of running for free,
and it is why this is not the default.
"""

from __future__ import annotations

from pathlib import Path

from .base import Provider


class NoneProvider(Provider):
    name = "none"
    setup_hint = "always available"

    @classmethod
    def available(cls) -> bool:
        return True

    def ask(self, prompt: str, schema: dict, images: list[Path] | None = None) -> dict:
        raise NotImplementedError(
            "NoneProvider answers through the pipeline's deterministic path, not ask()"
        )
