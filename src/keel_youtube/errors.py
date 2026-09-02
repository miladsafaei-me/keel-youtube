"""Every failure this package raises. One base class so a caller can catch the
whole family, and specific subclasses where the caller can actually do something
different about it."""

from __future__ import annotations


class KeelYoutubeError(RuntimeError):
    """Base class for every error raised by keel-youtube."""


class MissingRequirement(KeelYoutubeError):
    """An external program (yt-dlp, ffmpeg) or credential is not available.

    The message always names the exact command that fixes it, because this is
    the error a first-time user is most likely to hit.
    """


class TranscriptUnavailable(KeelYoutubeError):
    """The video has no usable caption track, or yt-dlp could not read it.

    Audio transcription (Whisper and friends) is deliberately out of scope: it
    would turn a zero-cost, zero-key tool into one that needs a GPU or an API
    budget just to start.
    """


class LLMError(KeelYoutubeError):
    """A model provider failed, or returned something that is not the JSON the
    caller asked for."""
