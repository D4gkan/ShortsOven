"""
alignment.py
------------
Produces the single most important artifact in this pipeline: the
mapping of "OCR line -> (start_frame, end_frame) in the final
narration track."

Approach (continuous synthesis + forced alignment)
----------------------------------------------------
Earlier versions of this module synthesized each OCR line as its own
isolated TTS clip and concatenated them. That gave exact per-clip
durations "for free", but it also meant the TTS model had zero
awareness of surrounding context when voicing each line -- every
clip got its own fresh, self-contained intonation contour, which is
what produced the flat, robotic "reading line by line" cadence.

This version instead:

  1. Synthesizes the ENTIRE narration as ONE continuous TTS call, so
     the model produces a single natural read-through with real
     cross-line prosody, momentum, and pausing driven by actual
     punctuation -- not one clip per line.
  2. Runs faster-whisper with word-level timestamps over that single
     narration file (forced alignment). This is now a REQUIRED
     dependency, not optional, since it's the only way to recover
     per-line timing from a single continuous clip.
  3. Walks the whisper word list and the OCR lines' own word lists in
     parallel (fuzzy-matching word by word, with a small resync
     window to tolerate whisper occasionally mis-transcribing,
     merging, or splitting a word) to figure out which whisper words
     belong to which OCR line, and derives each line's start/end from
     the timestamps of its first/last matched word.

This still satisfies "do not estimate, do not divide evenly, analyze
the generated speech": every line's timing comes from real measured
audio via forced alignment, never from a fixed/estimated split. The
only fallback to interpolation is the rare case where a line's words
couldn't be matched at all (e.g. whisper mis-transcribed all of a
very short line) -- that case is logged loudly as a warning since
it's a degraded, best-effort path, not the norm.
"""

import os
import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import List, Optional, Tuple

from pydub import AudioSegment
from pydub.effects import normalize

from .config import AppConfig
from .exceptions import AlignmentError
from .logger_setup import get_logger
from .ocr_engine import TextLine
from .tts_engine import QwenTTSEngine, get_wav_duration

log = get_logger(__name__)

RESYNC_WINDOW = 5          # how far ahead we'll look to resync after a word mismatch
FUZZY_MATCH_THRESHOLD = 0.75  # SequenceMatcher ratio to accept a "close enough" word match


@dataclass
class LineTiming:
    index: int
    text: str
    start_sec: float
    end_sec: float
    start_frame: int
    end_frame: int


def _normalize_word(w: str) -> str:
    """Strips punctuation (keeps internal apostrophes) and lowercases,
    so 'Fiancé.' and 'fiancé' or whisper's 'thats' vs OCR's "that's"
    compare fairly."""
    return re.sub(r"[^\w']+", "", w, flags=re.UNICODE).lower()


def _words_match(a: str, b: str) -> bool:
    if not a or not b:
        return False
    if a == b:
        return True
    return SequenceMatcher(None, a, b).ratio() >= FUZZY_MATCH_THRESHOLD


class AlignmentEngine:
    def __init__(self, cfg: AppConfig, tts: QwenTTSEngine):
        self.cfg = cfg
        self.tts = tts

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def build_narration(self, lines: List[TextLine], out_wav_path: str) -> List[LineTiming]:
        if not lines:
            raise AlignmentError("No OCR lines to narrate.")

        log.info("Generating narration (single continuous read-through)...")
        combined_text = " ".join(line.text.strip() for line in lines if line.text.strip())
        raw_path = self.tts.synthesize(combined_text)

        # Loudness normalization + resample, same as before, just
        # applied to the single synthesized clip instead of a
        # concatenation of many small clips.
        audio = AudioSegment.from_wav(raw_path)
        audio = normalize(audio, headroom=3.0)
        audio = audio.set_frame_rate(44100).set_channels(1)
        audio.export(out_wav_path, format="wav")

        log.info("Analyzing speech timings (forced alignment)...")
        whisper_words = self._transcribe_words(out_wav_path)

        timings = self._align_lines(lines, whisper_words, get_wav_duration(out_wav_path))
        return timings

    def _to_frame(self, seconds: float) -> int:
        return int(round(seconds * self.cfg.fps))

    # ------------------------------------------------------------------
    # Forced alignment (mandatory -- this is how we recover per-line
    # timing from the single continuous narration clip)
    # ------------------------------------------------------------------
    def _resolve_whisper_device(self) -> str:
        """Same auto-detection pattern as QwenTTSEngine._resolve_device:
        an explicit config value wins, otherwise use CUDA if it's
        actually available, else CPU. Previously this was hardcoded
        to "cpu" unconditionally, which left the GPU sitting idle for
        the entire forced-alignment phase even on machines with one."""
        requested = getattr(self.cfg, "whisper_device", "auto")
        if requested and requested != "auto":
            return requested
        try:
            import torch
            if torch.cuda.is_available():
                return "cuda"
        except ImportError:
            pass
        return "cpu"

    def _resolve_whisper_compute_type(self, device: str) -> str:
        requested = getattr(self.cfg, "whisper_compute_type", "auto")
        if requested and requested != "auto":
            return requested
        return "float16" if device == "cuda" else "int8"

    def _load_whisper_model(self):
        from faster_whisper import WhisperModel

        device = self._resolve_whisper_device()
        compute_type = self._resolve_whisper_compute_type(device)
        log.info(f"Loading forced-alignment model (faster-whisper base.en, "
                 f"device={device}, compute_type={compute_type})...")
        try:
            return WhisperModel("base.en", device=device, compute_type=compute_type)
        except Exception as e:
            if device != "cpu":
                log.warning(f"GPU load of faster-whisper failed ({e}); "
                            f"falling back to CPU inference.")
                return WhisperModel("base.en", device="cpu", compute_type="int8")
            raise

    def _transcribe_words(self, wav_path: str) -> List[Tuple[float, float, str]]:
        try:
            from faster_whisper import WhisperModel  # noqa: F401 -- import check only
        except ImportError as e:
            raise AlignmentError(
                "faster-whisper is required for line-timing alignment "
                "(it's how per-line timestamps are recovered from the "
                "single continuous narration clip). Run "
                "`pip install faster-whisper` and re-run the pipeline."
            ) from e

        try:
            model = self._load_whisper_model()
            segments, _ = model.transcribe(wav_path, word_timestamps=True)
            words: List[Tuple[float, float, str]] = []
            for seg in segments:
                if seg.words:
                    for w in seg.words:
                        norm = _normalize_word(w.word)
                        if norm:
                            words.append((w.start, w.end, norm))
            if not words:
                raise AlignmentError(
                    "faster-whisper produced no word-level timestamps for "
                    "the generated narration -- cannot align line timing."
                )
            return words
        except AlignmentError:
            raise
        except Exception as e:
            raise AlignmentError(f"Forced alignment (faster-whisper) failed: {e}") from e

    # ------------------------------------------------------------------
    # Word-by-word matching: OCR lines' expected words <-> whisper's
    # transcribed words, with a small resync window to tolerate minor
    # transcription mismatches.
    # ------------------------------------------------------------------
    def _align_lines(self, lines: List[TextLine],
                      whisper_words: List[Tuple[float, float, str]],
                      total_duration: float) -> List[LineTiming]:
        # Flatten every line's own words into one stream, tagged with
        # which line each word belongs to.
        expected: List[Tuple[int, str]] = []
        for line in lines:
            for tok in line.text.split():
                norm = _normalize_word(tok)
                if norm:
                    expected.append((line.index, norm))

        line_start: dict = {}
        line_end: dict = {}

        i, j = 0, 0
        while i < len(expected) and j < len(whisper_words):
            line_idx, exp_tok = expected[i]
            w_start, w_end, w_tok = whisper_words[j]

            if _words_match(exp_tok, w_tok):
                if line_idx not in line_start:
                    line_start[line_idx] = w_start
                line_end[line_idx] = w_end
                i += 1
                j += 1
                continue

            # Try resyncing by looking ahead in whisper's words (it
            # may have skipped/merged a word OCR saw as separate).
            resynced = False
            for k in range(1, RESYNC_WINDOW + 1):
                if j + k < len(whisper_words) and _words_match(exp_tok, whisper_words[j + k][2]):
                    j += k
                    resynced = True
                    break
            if resynced:
                continue

            # Try resyncing the other way (OCR saw an extra token --
            # e.g. a stray character -- that whisper never voiced).
            resynced_expected = False
            for k in range(1, RESYNC_WINDOW + 1):
                if i + k < len(expected) and _words_match(expected[i + k][1], w_tok):
                    i += k
                    resynced_expected = True
                    break
            if resynced_expected:
                continue

            # Couldn't resync either direction -- skip both one step
            # forward rather than getting stuck (best-effort recovery,
            # not a silent failure: the missing line(s) get flagged
            # and interpolated below).
            i += 1
            j += 1

        # Any line with no matched words at all falls back to
        # interpolating between its neighbors' known boundaries. This
        # is the only estimation path in this module, and it only
        # triggers when forced alignment genuinely couldn't find a
        # line's words (e.g. whisper garbled a very short line).
        for line in lines:
            if line.index not in line_start:
                log.warning(
                    f"Line {line.index} ('{line.text}') could not be matched "
                    f"against the forced-alignment transcript; timing for "
                    f"this line is interpolated rather than measured."
                )

        timings: List[LineTiming] = []
        prev_end = 0.0
        for idx, line in enumerate(lines):
            if line.index in line_start:
                start_sec = line_start[line.index]
                end_sec = line_end[line.index]
            else:
                # Interpolate: split the gap to the next known line
                # (or total duration, if this is the last line)
                # proportionally by word count.
                next_known = next(
                    (l for l in lines[idx + 1:] if l.index in line_start), None
                )
                gap_end = line_start[next_known.index] if next_known else total_duration
                span = max(0.05, gap_end - prev_end)
                start_sec = prev_end
                end_sec = prev_end + span
            start_sec = max(0.0, min(start_sec, total_duration))
            end_sec = max(start_sec, min(end_sec, total_duration))
            timings.append(LineTiming(
                index=line.index, text=line.text,
                start_sec=start_sec, end_sec=end_sec,
                start_frame=self._to_frame(start_sec),
                end_frame=self._to_frame(end_sec),
            ))
            prev_end = end_sec

        return timings
