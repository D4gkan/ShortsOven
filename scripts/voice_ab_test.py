#!/usr/bin/env python3
"""
voice_ab_test.py
-----------------
Synthesizes ONE sample line with EVERY candidate voice for the
configured gender (qwen_male_voice_candidates / qwen_female_voice_
candidates in config.json), using the exact same instruct + speed
settings the real pipeline uses -- so what you hear here is a true
preview of how each voice will actually sound in a finished video.

Unlike the normal pipeline (which stops at the FIRST candidate that
loads successfully), this script deliberately tries ALL of them and
keeps going even if some fail, so you get a full lineup to compare.

Usage:
    python scripts/voice_ab_test.py
    python scripts/voice_ab_test.py --gender female
    python scripts/voice_ab_test.py --text "Custom sample line here."

Output:
    cache/voice_samples/<gender>_<voice_name>.wav  -- one file per
    voice that successfully synthesized. Failed voices are skipped
    with a warning (same as the real pipeline would fall back), not
    a hard crash, so one bad preset doesn't stop the rest from being
    generated.

Once you've listened and picked a favorite, move that voice name to
the FRONT of the matching list in config.json (qwen_male_voice_
candidates or qwen_female_voice_candidates) -- the pipeline always
uses the first candidate in that list that loads successfully.
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.config import load_config
from src.exceptions import TTSError
from src.logger_setup import get_logger, setup_logging
from src.tts_engine import QwenTTSEngine

log = get_logger("voice_ab_test")

DEFAULT_SAMPLE_TEXT = (
    "You are not going to believe what happened to me at work today -- "
    "it honestly still doesn't feel real."
)


def parse_args():
    p = argparse.ArgumentParser(description="A/B test Qwen3-TTS voice candidates.")
    p.add_argument("--gender", choices=["male", "female"], default=None,
                    help="Which candidate list to test. Defaults to the "
                         "gender configured in config.json/VOICE_GENDER.")
    p.add_argument("--text", default=DEFAULT_SAMPLE_TEXT,
                    help="Sample line to synthesize with every voice.")
    return p.parse_args()


def main():
    args = parse_args()
    cfg = load_config()
    setup_logging(cfg.log_level)

    engine = QwenTTSEngine(cfg)
    if args.gender:
        engine.gender = args.gender  # override auto-resolved gender

    candidates = engine._candidates_for_gender()
    log.info(f"Testing {len(candidates)} '{engine.gender}' voice candidate(s): "
             f"{', '.join(candidates)}")

    model = engine._load_model()

    out_dir = cfg.abspath(os.path.join(cfg.cache_dir, "voice_samples"))
    os.makedirs(out_dir, exist_ok=True)

    speed = getattr(cfg, "voice_speed", 1.0) or 1.0
    results = []

    for voice_name in candidates:
        out_path = os.path.join(out_dir, f"{engine.gender}_{voice_name}.wav")
        log.info(f"Synthesizing sample for voice '{voice_name}'...")
        try:
            result = engine._raw_generate(model, args.text, voice_name)
            audio, sample_rate = engine._unpack_audio(result)
            if audio is None or audio.size == 0:
                raise TTSError("Produced empty audio.")

            import soundfile as sf
            sf.write(out_path, audio, sample_rate, subtype="PCM_16")

            if abs(speed - 1.0) > 1e-3:
                engine._apply_speed(out_path, speed)

            log.info(f"  -> saved: {out_path}")
            results.append((voice_name, out_path, True))
        except Exception as e:
            log.warning(f"  -> voice '{voice_name}' failed: {e}")
            results.append((voice_name, None, False))

    ok = [r for r in results if r[2]]
    failed = [r for r in results if not r[2]]

    log.info("")
    log.info("=== Summary ===")
    for voice_name, out_path, success in results:
        status = "OK" if success else "FAILED"
        log.info(f"  [{status}] {voice_name}" + (f" -> {out_path}" if success else ""))

    if not ok:
        log.error("No candidate voices synthesized successfully.")
        return 1

    log.info("")
    log.info(f"Listen to the files in: {out_dir}")
    log.info("Once you've picked a favorite, move its name to the FRONT of "
             f"'qwen_{engine.gender}_voice_candidates' in config.json.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
