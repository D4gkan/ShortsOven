"""
reveal.py
---------
Builds the top->bottom "clipping mask" reveal animation, driven
entirely by narration timing (never by a constant speed, never
sideways, never a fade/wipe).

For every OCR line i:
  - The chunk reveals in the short gap RIGHT AFTER the previous
    line's last word finishes and RIGHT BEFORE this line's first
    word is spoken -- a quick "snap", capped between
    `min_line_reveal_sec` and `max_line_reveal_sec` (config.json),
    using an eased curve so it still feels smooth rather than an
    instant cut.
  - While line i is actually being spoken, the mask holds perfectly
    still at that line's target so the viewer can read it while
    listening ("no movement" while narrated, per spec).

The mask is rendered as a black/white video the same size as the
*displayed* screenshot: white = revealed (show image), black =
hidden (show background through). This mask is later combined with
the image and background in renderer.py via ffmpeg's `alphamerge` +
`overlay`, so the screenshot image itself is never cropped or
re-encoded at reduced quality -- only the mask moves.
"""

import os
from dataclasses import dataclass
from typing import List

import cv2
import numpy as np

from .alignment import LineTiming
from .config import AppConfig
from .logger_setup import get_logger
from .ocr_engine import TextLine

log = get_logger(__name__)


def _ease_in_out_cubic(t: float) -> float:
    """Smooth accelerate -> decelerate -> stop-precisely curve.
    t in [0, 1] -> eased value in [0, 1]."""
    t = max(0.0, min(1.0, t))
    if t < 0.5:
        return 4 * t * t * t
    p = -2 * t + 2
    return 1 - (p ** 3) / 2


def _ease_out_quart(t: float) -> float:
    """Snappier curve: fires fast immediately, decelerates hard into
    the stop. Feels more like a quick "snap" than the smoother
    in-out curve above -- better suited to the very short reveal
    window used now."""
    t = max(0.0, min(1.0, t))
    return 1 - (1 - t) ** 4


EASING_FUNCS = {
    "ease_out_cubic": _ease_out_quart,
    "ease_in_out_cubic": _ease_in_out_cubic,
    "ease_out_quart": _ease_out_quart,
}


@dataclass
class RevealPlan:
    total_frames: int
    display_width: int
    display_height: int
    heights: np.ndarray  # per-frame revealed height in displayed-image pixels


class RevealBuilder:
    def __init__(self, cfg: AppConfig):
        self.cfg = cfg
        self.ease = EASING_FUNCS.get(cfg.reveal_ease, _ease_in_out_cubic)

    def build_plan(self, lines: List[TextLine], timings: List[LineTiming],
                    orig_image_size, display_size) -> RevealPlan:
        log.info("Building reveal animation...")
        orig_w, orig_h = orig_image_size
        disp_w, disp_h = display_size
        scale = disp_h / float(orig_h)

        pad = self.cfg.line_padding_px
        # Reveal target for each line = bottom edge of that line's
        # bounding box (plus a little padding so text isn't clipped),
        # converted into displayed-image pixel space.
        targets = []
        for line in lines:
            bottom = min(orig_h, line.y + line.height + pad)
            targets.append(bottom * scale)

        total_frames = int(round(timings[-1].end_frame)) + 1
        heights = np.zeros(total_frames, dtype=np.float32)

        min_frames = max(1, int(self.cfg.min_line_reveal_sec * self.cfg.fps))
        max_frames = max(min_frames, int(self.cfg.max_line_reveal_sec * self.cfg.fps))

        prev_target = 0.0
        prev_end_frame = 0
        for line, timing, target in zip(lines, timings, targets):
            # The chunk reveals in the gap RIGHT AFTER the previous
            # line's last word and RIGHT BEFORE this line's first word
            # -- not while this line is being spoken. This keeps the
            # motion a quick "snap" instead of a slow multi-second
            # crawl, and lets the viewer read the line while it's
            # narrated instead of watching it still animate.
            reveal_start = prev_end_frame
            available = max(1, timing.start_frame - reveal_start)
            reveal_span = min(max_frames, max(min_frames, available))
            reveal_end = min(reveal_start + reveal_span, total_frames)

            for f in range(reveal_start, reveal_end):
                t = (f - reveal_start) / reveal_span
                eased = self.ease(t)
                heights[f] = prev_target + (target - prev_target) * eased

            # Hold perfectly still for the rest of the gap (if any) and
            # for the entire time this line is being spoken.
            hold_end = max(reveal_end, timing.end_frame)
            if reveal_end < total_frames:
                heights[reveal_end:min(hold_end, total_frames)] = target

            prev_target = target
            prev_end_frame = max(timing.end_frame, reveal_end)

        # tail: keep final line's revealed height for any remaining frames
        if prev_end_frame < total_frames:
            heights[prev_end_frame:total_frames] = prev_target

        heights = np.clip(heights, 0, disp_h)
        return RevealPlan(total_frames=total_frames, display_width=disp_w,
                           display_height=disp_h, heights=heights)

    def render_mask_video(self, plan: RevealPlan, out_path: str) -> str:
        """Writes a black/white mask video: white rectangle from y=0
        to y=revealed_height(frame), black elsewhere. Dimensions MUST
        exactly match the image's display size to avoid alphamerge
        frame-size mismatches in ffmpeg."""
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        writer = cv2.VideoWriter(out_path, fourcc, self.cfg.fps,
                                  (plan.display_width, plan.display_height), isColor=False)
        try:
            for f in range(plan.total_frames):
                h = int(plan.heights[f])
                frame = np.zeros((plan.display_height, plan.display_width), dtype=np.uint8)
                if h > 0:
                    frame[0:h, :] = 255
                writer.write(frame)
        finally:
            writer.release()
        return out_path
