#!/usr/bin/env python3
"""
main.py
-------
Entry point. Runs the full pipeline end-to-end with zero user
interaction, per the spec:

  1. Randomly select image / background / music from assets/
  2. OCR the screenshot into human-readable lines (with coordinates)
  3. Clean up OCR mistakes
  4. Generate offline male narration & determine exact per-line timing
     from the generated speech (never estimated)
  5. Prepare the background video (loop/trim, scale to fill 1080x1920)
  6. Build the speech-driven reveal mask animation
  7. Render the final H.264/AAC vertical video with ffmpeg
"""

import argparse
import os
import sys
import time
import traceback

from PIL import Image

from src.config import load_config
from src.logger_setup import setup_logging, get_logger
from src.exceptions import RedditVideoGenError
from src.asset_manager import AssetManager
from src.ocr_engine import OCREngine
from src.text_cleanup import clean_lines
from src.tts_engine import QwenTTSEngine
from src.alignment import AlignmentEngine
from src.reveal import RevealBuilder
from src.renderer import Renderer

log = get_logger("main")

TAIL_SILENCE_SEC = 0.8  # brief hold at the end after the last line finishes


def compute_display_size(orig_w: int, orig_h: int, canvas_w: int, canvas_h: int):
    """Screenshot is scaled (never cropped) to fit within ~88% of the
    canvas width while preserving its aspect ratio, then centered.

    Both dimensions are forced to be even numbers. Video codecs (the
    mp4v writer used for the mask, and libx264/yuv420p for the final
    render) require even width/height and will silently round an odd
    value down internally -- if we didn't force evenness here, the
    mask video and the ffmpeg `scale` filter (which has no such
    constraint) could end up 1px apart and fail alphamerge.
    """
    target_w = int(canvas_w * 0.88)
    target_h = int(round(target_w * orig_h / orig_w))
    if target_w % 2:
        target_w -= 1
    if target_h % 2:
        target_h -= 1
    return target_w, target_h


def parse_args():
    parser = argparse.ArgumentParser(description="AI Reddit Story Video Generator")
    parser.add_argument(
        "--image", default=None,
        help="Use this specific image instead of picking one randomly "
             "from assets/images. Used by the batch loop in start.bat; "
             "omit this for the normal single-random-image run.",
    )
    return parser.parse_args()


def run():
    args = parse_args()
    cfg = load_config()
    setup_logging(cfg.log_level)

    log.info("=== AI Reddit Story Video Generator ===")

    try:
        assets = AssetManager(cfg)
        selected = assets.select_random(forced_image=args.image)

        log.info("Loading image...")
        with Image.open(selected.image_path) as im:
            orig_w, orig_h = im.size

        ocr = OCREngine(cfg)
        lines = ocr.detect_lines(selected.image_path)
        lines = clean_lines(lines)

        tts = QwenTTSEngine(cfg)
        aligner = AlignmentEngine(cfg, tts)

        narration_path = cfg.abspath(os.path.join(cfg.cache_dir, "narration.wav"))
        timings = aligner.build_narration(lines, narration_path)

        duration_sec = timings[-1].end_sec + TAIL_SILENCE_SEC

        prepared_bg_path = cfg.abspath(os.path.join(cfg.cache_dir, "prepared_background.mp4"))
        assets.prepare_background(selected.background_path, duration_sec, prepared_bg_path)

        display_w, display_h = compute_display_size(orig_w, orig_h, cfg.width, cfg.height)

        reveal = RevealBuilder(cfg)
        plan = reveal.build_plan(lines, timings, (orig_w, orig_h), (display_w, display_h))
        mask_path = cfg.abspath(os.path.join(cfg.cache_dir, "reveal_mask.mp4"))
        reveal.render_mask_video(plan, mask_path)

        renderer = Renderer(cfg)
        out_name = f"reddit_story_{int(time.time())}.mp4"
        out_path = cfg.abspath(os.path.join(cfg.output_dir, out_name))
        renderer.render(
            background_path=prepared_bg_path,
            image_path=selected.image_path,
            mask_path=mask_path,
            narration_path=narration_path,
            music_path=selected.music_path,
            duration_sec=duration_sec,
            display_w=display_w,
            display_h=display_h,
            out_path=out_path,
        )

        log.info(f"Video ready: {out_path}")
        return 0

    except RedditVideoGenError as e:
        log.error(str(e))
        return 1
    except Exception:
        log.error("An unexpected error occurred:\n" + traceback.format_exc())
        return 1


if __name__ == "__main__":
    sys.exit(run())