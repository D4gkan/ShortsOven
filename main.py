#!/usr/bin/env python3
"""ShortsOven: OCR -> cleanup -> Ollama tone -> Qwen TTS -> alignment -> video."""

import argparse
import os
import sys
import time
import traceback

from PIL import Image

from src import __version__
from src.config import load_config
from src.logger_setup import setup_logging, get_logger
from src.exceptions import RedditVideoGenError
from src.asset_manager import AssetManager
from src.ocr_engine import OCREngine
from src.text_cleanup import clean_lines
from src.tts_engine import QwenTTSEngine
from src.tone_engine import ToneEngine
from src.alignment import AlignmentEngine
from src.reveal import RevealBuilder
from src.renderer import Renderer
from src.pictures import detect_pictures, outside_pictures, insert_picture_pauses

log = get_logger("main")

TAIL_SILENCE_SEC = 0.8  # brief hold at the end after the last line finishes


def compute_display_size(orig_w: int, orig_h: int, canvas_w: int, canvas_h: int):
    """Scale conversation width consistently; height never shrinks to fit."""
    target_w = int(canvas_w * 0.88)
    target_h = int(round(target_w * orig_h / orig_w))
    if target_w % 2:
        target_w -= 1
    if target_h % 2:
        target_h -= 1
    return target_w, target_h


def parse_args():
    parser = argparse.ArgumentParser(description="AI Reddit Story Video Generator")
    parser.add_argument("--version", action="version", version=f"ShortsOven {__version__}")
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

    log.info(f"=== ShortsOven {__version__} ===")

    try:
        assets = AssetManager(cfg)
        selected = assets.select_random(forced_image=args.image)

        log.info("Loading image...")
        with Image.open(selected.image_path) as im:
            orig_w, orig_h = im.size
            # Keep OCR and rendering on identical pixels if the original moves.
            working_image = cfg.abspath(os.path.join(cfg.cache_dir, "source_image.png"))
            im.convert("RGB").save(working_image, format="PNG")

        ocr = OCREngine(cfg)
        visual_lines = ocr.detect_lines(working_image)
        pictures = detect_pictures(working_image)
        narration_lines = [line for line in visual_lines if outside_pictures(line, pictures)]
        lines = clean_lines(narration_lines)
        log.info("Detected %s separate picture reveals.", len(pictures))

        story = " ".join(line.text.strip() for line in lines if line.text.strip())
        cfg = ToneEngine(cfg).analyze(story).apply(cfg)
        tts = QwenTTSEngine(cfg)
        aligner = AlignmentEngine(cfg, tts)

        narration_path = cfg.abspath(os.path.join(cfg.cache_dir, "narration.wav"))
        timings = aligner.build_narration(lines, narration_path)

        duration_sec = timings[-1].end_sec + TAIL_SILENCE_SEC
        if pictures:
            timings, audio_duration = insert_picture_pauses(
                narration_path, lines, timings, pictures, cfg.fps, cfg.conversation_slide_sec)
            duration_sec = audio_duration + TAIL_SILENCE_SEC

        prepared_bg_path = cfg.abspath(os.path.join(cfg.cache_dir, "prepared_background.mp4"))
        assets.prepare_background(selected.background_path, duration_sec, prepared_bg_path)

        display_w, display_h = compute_display_size(orig_w, orig_h, cfg.width, cfg.height)

        reveal = RevealBuilder(cfg)
        plan = reveal.build_plan(lines, timings, (orig_w, orig_h), (display_w, display_h),
                                 visual_lines=visual_lines, pictures=pictures)
        chunk_paths = reveal.export_chunks(
            working_image, plan, cfg.abspath(os.path.join(cfg.cache_dir, "conversation")), visual_lines
        )

        renderer = Renderer(cfg)
        out_name = f"reddit_story_{int(time.time())}.mp4"
        out_path = cfg.abspath(os.path.join(cfg.output_dir, out_name))
        renderer.render(
            background_path=prepared_bg_path,
            chunk_paths=chunk_paths,
            plan=plan,
            narration_path=narration_path,
            music_path=selected.music_path,
            duration_sec=duration_sec,
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
