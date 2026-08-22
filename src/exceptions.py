"""
exceptions.py
-------------
Custom exceptions so failures are explained clearly to the user
instead of surfacing as raw stack traces (per the "Error Handling"
requirements: "Never crash silently").
"""


class RedditVideoGenError(Exception):
    """Base class for all application-specific errors."""


class AssetError(RedditVideoGenError):
    """Raised when required input assets (image/background/music) are
    missing or invalid."""


class OCRError(RedditVideoGenError):
    """Raised when OCR fails to run or returns no usable text."""


class TTSError(RedditVideoGenError):
    """Raised when narration cannot be generated with a valid offline
    male voice model."""


class AlignmentError(RedditVideoGenError):
    """Raised when narration audio cannot be aligned to OCR lines."""


class RenderError(RedditVideoGenError):
    """Raised when ffmpeg rendering fails."""


class FFmpegNotFoundError(RenderError):
    """Raised when the ffmpeg binary cannot be located on PATH."""
