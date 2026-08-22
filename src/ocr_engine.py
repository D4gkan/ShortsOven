"""
ocr_engine.py
-------------
Fully offline OCR using PaddleOCR (PP-OCRv6, via the `paddleocr` PyPI
package). Detects text the way a human reads the screenshot: grouped
into visual *lines* (rows), not sentences. Word boxes on the same
visual row are merged into a single line box with combined text, x/y/
width/height preserved for the reveal animation.

This module is an adapter: PaddleOCR replaced EasyOCR as the backend,
but the public interface (`OCREngine.detect_lines()` -> `List[TextLine]`)
and the on-disk cache format are unchanged, so nothing downstream
(text_cleanup.py, alignment.py, reveal.py, main.py) needs to know the
engine changed.

Caching: results are keyed by a hash of the image bytes, so re-running
on the same screenshot never re-runs OCR (per the "avoid re-running
OCR when image hasn't changed" performance requirement).
"""

import hashlib
import json
import os
from dataclasses import dataclass, asdict
from typing import List

import numpy as np
from PIL import Image

from .config import AppConfig
from .exceptions import OCRError
from .logger_setup import get_logger

log = get_logger(__name__)


@dataclass
class TextLine:
    index: int
    text: str
    x: int
    y: int
    width: int
    height: int


def _image_hash(image_path: str) -> str:
    h = hashlib.sha256()
    with open(image_path, "rb") as f:
        h.update(f.read())
    return h.hexdigest()[:16]


class OCREngine:
    """Wraps PaddleOCR and groups word-level boxes into human-readable
    lines based on vertical (row) proximity. The PaddleOCR-specific
    plumbing is isolated in `_get_reader` / `_run_paddleocr` /
    `_parse_predict_result` / `_parse_legacy_result`; everything else
    (grouping, caching, the TextLine shape) is unchanged from before."""

    def __init__(self, cfg: AppConfig, languages=("en",)):
        self.cfg = cfg
        self.languages = list(languages)
        self._reader = None  # lazy-loaded, offline model, reused across calls

    # ------------------------------------------------------------------
    # Model loading
    # ------------------------------------------------------------------
    def _lang_code(self) -> str:
        """PaddleOCR expects a single language code (e.g. 'en', 'ch').
        We only ever configure one language for this pipeline."""
        return (self.languages[0] if self.languages else "en").lower()

    def _resolve_device(self) -> str:
        requested = getattr(self.cfg, "paddleocr_device", "auto")
        if requested and requested != "auto":
            return requested
        if getattr(self.cfg, "paddleocr_use_gpu", False):
            try:
                import paddle
                if paddle.device.is_compiled_with_cuda() and paddle.device.cuda.device_count() > 0:
                    return "gpu"
            except Exception:
                log.warning("GPU requested for PaddleOCR but CUDA/Paddle-GPU is "
                            "not available; falling back to CPU.")
        return "cpu"

    def _get_reader(self):
        if self._reader is not None:
            return self._reader

        try:
            from paddleocr import PaddleOCR
        except ImportError as e:
            raise OCRError(
                "PaddleOCR is not installed. Run setup.bat to install "
                "dependencies and download OCR models, or "
                "`pip install paddlepaddle paddleocr` manually."
            ) from e

        lang = self._lang_code()
        device = self._resolve_device()
        log.info(f"Loading offline OCR model (PaddleOCR, device={device})...")

        # enable_mkldnn=False: some PaddlePaddle 3.3.x CPU builds hit a
        # oneDNN/PIR bug during inference ("ConvertPirAttribute2Runtime
        # Attribute not support [pir::ArrayAttribute<pir::DoubleAttribute>]")
        # that crashes predict() entirely on affected CPUs. Disabling
        # oneDNN avoids that op path. Only relevant on CPU -- oneDNN
        # doesn't apply on GPU.
        current_kwargs = dict(
            lang=lang,
            use_doc_orientation_classify=False,
            use_doc_unwarping=False,
            use_textline_orientation=True,
            device=device,
        )
        if device == "cpu":
            current_kwargs["enable_mkldnn"] = False

        try:
            self._reader = PaddleOCR(**current_kwargs)
        except TypeError as e:
            # Either this is an older PaddleOCR release (<3.0) with a
            # different constructor signature, or this build simply
            # doesn't accept enable_mkldnn. Try current kwargs without
            # enable_mkldnn first (most likely cause on a TypeError),
            # then fall back to the legacy constructor entirely.
            if "enable_mkldnn" in str(e) and device == "cpu":
                current_kwargs.pop("enable_mkldnn", None)
                try:
                    self._reader = PaddleOCR(**current_kwargs)
                    return self._reader
                except Exception:
                    pass  # fall through to legacy constructor below

            try:
                self._reader = PaddleOCR(
                    use_angle_cls=True, lang=lang,
                    use_gpu=(device == "gpu"), show_log=False,
                )
            except Exception as e2:
                raise OCRError(
                    f"Failed to initialize PaddleOCR with either the current "
                    f"or legacy constructor signature: {e2}"
                ) from e2
        except Exception as e:
            raise OCRError(
                f"Failed to initialize PaddleOCR (device={device}): {e}. "
                "If this is a CUDA/GPU error, set \"paddleocr_use_gpu\": false "
                "in config.json to force CPU inference."
            ) from e

        return self._reader

    # ------------------------------------------------------------------
    # Caching + public API
    # ------------------------------------------------------------------
    def _cache_path(self, image_path: str) -> str:
        key = _image_hash(image_path)
        cache_dir = self.cfg.abspath(self.cfg.cache_dir)
        os.makedirs(cache_dir, exist_ok=True)
        return os.path.join(cache_dir, f"ocr_{key}.json")

    def detect_lines(self, image_path: str) -> List[TextLine]:
        cache_file = self._cache_path(image_path)
        if os.path.exists(cache_file):
            log.info("OCR cache hit -- skipping re-run.")
            with open(cache_file, "r", encoding="utf-8") as f:
                raw = json.load(f)
            return [TextLine(**item) for item in raw]

        log.info("Running OCR...")
        reader = self._get_reader()
        img = np.array(Image.open(image_path).convert("RGB"))

        words = self._run_paddleocr(reader, img, image_path)
        if not words:
            raise OCRError(
                f"OCR found no text in '{image_path}'. Make sure the "
                f"screenshot is clear and contains visible text."
            )

        lines = self._group_into_lines(words)
        if not lines:
            raise OCRError("OCR detected text fragments but could not group "
                            "them into readable lines.")

        with open(cache_file, "w", encoding="utf-8") as f:
            json.dump([asdict(l) for l in lines], f, indent=2)

        log.info(f"Detected {len(lines)} text lines")
        return lines

    # ------------------------------------------------------------------
    # PaddleOCR result parsing (adapter layer)
    # ------------------------------------------------------------------
    def _run_paddleocr(self, reader, img: np.ndarray, image_path: str) -> list:
        """Runs PaddleOCR and normalizes its output into the same
        per-word dict shape the rest of this module has always used:
        {"text", "x", "y", "w", "h", "cy", "conf"}.

        Tries the current predict()-based pipeline API first, and
        falls back to the legacy ocr() API for older PaddleOCR
        releases, so this keeps working across the version range."""
        try:
            results = reader.predict(img)
            words = self._parse_predict_result(results)
            if words:
                return words
        except AttributeError:
            pass  # this PaddleOCR build doesn't have predict(); try legacy
        except Exception as e:
            log.warning(f"PaddleOCR predict() failed ({e}); "
                        f"trying the legacy ocr() API...")

        try:
            legacy_results = reader.ocr(img)
        except TypeError:
            # Some PaddleOCR releases still expect/accept cls= on the
            # legacy ocr() call; others (current 3.x) reject it outright
            # since textline orientation is now set at construction time
            # via use_textline_orientation. Try the old signature too
            # before giving up, so this keeps working across versions.
            try:
                legacy_results = reader.ocr(img, cls=True)
            except Exception as e:
                raise OCRError(
                    f"PaddleOCR failed to run inference on '{image_path}': {e}"
                ) from e
        except Exception as e:
            raise OCRError(
                f"PaddleOCR failed to run inference on '{image_path}': {e}"
            ) from e
        return self._parse_legacy_result(legacy_results)

    @staticmethod
    def _box_to_xywh(box_points) -> tuple:
        xs = [float(p[0]) for p in box_points]
        ys = [float(p[1]) for p in box_points]
        x, y = int(min(xs)), int(min(ys))
        w, h = int(max(xs) - min(xs)), int(max(ys) - min(ys))
        return x, y, w, h

    def _parse_predict_result(self, results) -> list:
        """Parses the dict-like `.json` result of PaddleOCR 3.x's
        `predict()` pipeline API (PP-OCRv6). The result is an iterable
        with one entry per input image; we only ever pass one image."""
        words = []
        for res in results:
            data = res.json if hasattr(res, "json") else res
            # save_to_json() nests the actual fields under "res" on some
            # PaddleOCR releases; handle both shapes defensively.
            if isinstance(data, dict) and "res" in data and isinstance(data["res"], dict):
                data = data["res"]

            texts = data.get("rec_texts") or []
            scores = data.get("rec_scores") or [1.0] * len(texts)
            polys = data.get("rec_polys") or data.get("dt_polys") or []
            boxes = data.get("rec_boxes")

            for i, text in enumerate(texts):
                if not text or not str(text).strip():
                    continue
                conf = float(scores[i]) if i < len(scores) else 1.0
                if boxes is not None and i < len(boxes):
                    xs_ys = boxes[i]
                    # rec_boxes is typically [x1, y1, x2, y2]
                    x, y = int(xs_ys[0]), int(xs_ys[1])
                    w, h = int(xs_ys[2] - xs_ys[0]), int(xs_ys[3] - xs_ys[1])
                elif i < len(polys):
                    x, y, w, h = self._box_to_xywh(polys[i])
                else:
                    continue
                words.append({"text": str(text), "x": x, "y": y, "w": w, "h": h,
                              "cy": y + h / 2, "conf": conf})
        return words

    def _parse_legacy_result(self, legacy_results) -> list:
        """Parses the older `[[box, (text, conf)], ...]` shape returned
        by `PaddleOCR.ocr()` in pre-3.x releases."""
        words = []
        if not legacy_results:
            return words
        for page in legacy_results:
            if not page:
                continue
            for item in page:
                box, (text, conf) = item[0], item[1]
                if not text or not str(text).strip():
                    continue
                x, y, w, h = self._box_to_xywh(box)
                words.append({"text": str(text), "x": x, "y": y, "w": w, "h": h,
                              "cy": y + h / 2, "conf": float(conf)})
        return words

    # ------------------------------------------------------------------
    # Row grouping (unchanged from the EasyOCR-based version)
    # ------------------------------------------------------------------
    @staticmethod
    def _group_into_lines(words: list, row_tolerance_ratio: float = 0.6) -> List[TextLine]:
        """Groups word boxes into visual rows the way a human eye scans
        the image top-to-bottom, left-to-right -- NOT by sentence
        punctuation. Reading order is preserved by sorting first by row
        (cy), then left-to-right (x) within each row."""
        if not words:
            return []

        words = sorted(words, key=lambda w: w["cy"])
        rows = []
        current_row = [words[0]]
        current_cy = words[0]["cy"]
        avg_h = words[0]["h"]

        for w in words[1:]:
            tolerance = avg_h * row_tolerance_ratio
            if abs(w["cy"] - current_cy) <= tolerance:
                current_row.append(w)
                # running average keeps grouping stable across a long row
                current_cy = sum(x["cy"] for x in current_row) / len(current_row)
                avg_h = sum(x["h"] for x in current_row) / len(current_row)
            else:
                rows.append(current_row)
                current_row = [w]
                current_cy = w["cy"]
                avg_h = w["h"]
        rows.append(current_row)

        lines = []
        for i, row in enumerate(rows):
            row = sorted(row, key=lambda w: w["x"])
            text = " ".join(w["text"] for w in row).strip()
            if not text:
                continue
            x0 = min(w["x"] for w in row)
            y0 = min(w["y"] for w in row)
            x1 = max(w["x"] + w["w"] for w in row)
            y1 = max(w["y"] + w["h"] for w in row)
            lines.append(TextLine(
                index=len(lines), text=text,
                x=x0, y=y0, width=x1 - x0, height=y1 - y0,
            ))
        return lines