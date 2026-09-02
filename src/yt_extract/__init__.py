"""yt-extract — a YouTube video becomes one folder: a formatted transcript and
the screenshots that carry the video's meaning.

Nothing in this package knows about any CMS, database, publishing pipeline or
content model. Its whole contract is the output folder described in AGENTS.md.
"""

from .pipeline import run
from .errors import ExtractError, TranscriptUnavailable, MissingRequirement, LLMError

__version__ = "0.1.0"
__all__ = [
    "run",
    "ExtractError",
    "TranscriptUnavailable",
    "MissingRequirement",
    "LLMError",
]
