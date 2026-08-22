#!/usr/bin/env python3
"""
download_models.py
-------------------
Run once (called automatically by setup.bat) to fetch every model
needed for fully-offline operation afterwards:

  - PaddleOCR (PP-OCRv6) detection/recognition/orientation weights
  - Qwen3-TTS 1.7B model weights (male voice narration)
  - faster-whisper base.en weights (REQUIRED for the forced-alignment
    line timing in alignment.py, not optional)

After this script finishes, main.py never needs a network connection.
"""

import json
import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)


def _load_config() -> dict:
    cfg_path = os.path.join(PROJECT_ROOT, "config.json")
    if not os.path.exists(cfg_path):
        return {}
    with open(cfg_path, "r", encoding="utf-8") as f:
        return json.load(f)


def download_paddleocr_models():
    """Instantiating PaddleOCR triggers its own one-time download of
    detection/recognition/orientation-classification weights into its
    default local cache -- mirrors the old EasyOCR download step."""
    print("== Downloading PaddleOCR models ==")
    cfg = _load_config()
    lang = cfg.get("ocr_lang", "en")
    try:
        from paddleocr import PaddleOCR
        try:
            PaddleOCR(
                lang=lang,
                use_doc_orientation_classify=False,
                use_doc_unwarping=False,
                use_textline_orientation=True,
                device="cpu",
            )
        except TypeError:
            # older PaddleOCR releases use a different constructor
            PaddleOCR(use_angle_cls=True, lang=lang, use_gpu=False, show_log=False)
        print("  OK")
    except Exception as e:
        print(f"  FAILED: {e}")
        print("  PaddleOCR models could not be downloaded. Check your "
              "internet connection and re-run this script.")


def download_qwen_tts_model():
    """Downloads the Qwen3-TTS 1.7B weights from Hugging Face into the
    directory configured by qwen_tts_model_dir in config.json."""
    print("== Downloading Qwen3-TTS 1.7B model ==")
    cfg = _load_config()
    model_id = cfg.get("qwen_tts_model_id", "Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice")
    tokenizer_id = "Qwen/Qwen3-TTS-Tokenizer-12Hz"
    model_dir = os.path.join(PROJECT_ROOT, cfg.get("qwen_tts_model_dir", "models/qwen_tts"))
    tokenizer_dir = os.path.join(PROJECT_ROOT, "models", "qwen_tts_tokenizer")
    os.makedirs(model_dir, exist_ok=True)
    os.makedirs(tokenizer_dir, exist_ok=True)

    try:
        from huggingface_hub import snapshot_download
    except ImportError as e:
        print(f"  FAILED: huggingface_hub is not installed ({e}). "
              "Run `pip install huggingface_hub` and re-run this script.")
        return False

    got_one = False
    for repo_id, out_dir in ((tokenizer_id, tokenizer_dir), (model_id, model_dir)):
        try:
            print(f"  downloading {repo_id} ...")
            snapshot_download(repo_id=repo_id, local_dir=out_dir)
            print(f"  OK: {repo_id} -> {out_dir}")
            got_one = True
        except Exception as e:
            print(f"  FAILED: {repo_id}: {e}")

    if not got_one:
        print("  WARNING: Qwen3-TTS weights could not be downloaded. Check your "
              "internet connection and re-run this script. main.py will refuse "
              "to fall back to a female or robotic voice.")
    return got_one


def _resolve_whisper_device(cfg: dict) -> str:
    """Mirrors AlignmentEngine._resolve_whisper_device in
    src/alignment.py, so this download step exercises the model on
    the same device the real pipeline will use -- a GPU/driver
    problem shows up here during setup instead of on your first
    real batch run."""
    requested = cfg.get("whisper_device", "auto")
    if requested and requested != "auto":
        return requested
    try:
        import torch
        if torch.cuda.is_available():
            return "cuda"
    except ImportError:
        pass
    return "cpu"


def _resolve_whisper_compute_type(device: str, cfg: dict) -> str:
    requested = cfg.get("whisper_compute_type", "auto")
    if requested and requested != "auto":
        return requested
    return "float16" if device == "cuda" else "int8"


def download_whisper_model():
    print("== Downloading faster-whisper base.en model (required) ==")
    cfg = _load_config()
    device = _resolve_whisper_device(cfg)
    compute_type = _resolve_whisper_compute_type(device, cfg)
    try:
        from faster_whisper import WhisperModel
    except ImportError as e:
        print(f"  FAILED: faster-whisper is not installed ({e}). "
              "Run `pip install faster-whisper` and re-run this script.")
        return

    try:
        print(f"  loading on device={device}, compute_type={compute_type} ...")
        WhisperModel("base.en", device=device, compute_type=compute_type)
        print("  OK")
    except Exception as e:
        if device != "cpu":
            print(f"  GPU load failed ({e}); retrying on CPU...")
            try:
                WhisperModel("base.en", device="cpu", compute_type="int8")
                print("  OK (CPU)")
                return
            except Exception as e2:
                print(f"  FAILED: {e2}")
                return
        print(f"  FAILED: {e}")


if __name__ == "__main__":
    download_paddleocr_models()
    download_qwen_tts_model()
    download_whisper_model()
    print("\nModel download step complete.")
