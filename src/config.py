"""
config.py
---------
Loads and validates config.json, and exposes convenient derived
properties (e.g. resolution as an (w, h) tuple) to the rest of the
application.
"""

import json
import os
from dataclasses import dataclass, field
from typing import List


DEFAULT_CONFIG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config.json"
)


@dataclass
class AppConfig:
    fps: int = 60
    resolution: str = "1080x1920"
    music_volume: float = 0.10
    # Gain applied to the narration track alone, before mixing with
    # music (separate from narration_mix_gain, which affects the
    # already-mixed narration+music output together). 1.0 = no change,
    # 1.3 = 30% louder narration only, music untouched.
    narration_volume: float = 1.0
    music_fade_in_sec: float = 1.5
    music_fade_out_sec: float = 2.0
    voice_speed: float = 1.18
    voice: str = "male"

    # --- OCR (PaddleOCR) ---
    ocr_lang: str = "en"
    paddleocr_use_gpu: bool = False
    paddleocr_device: str = "auto"  # "auto" | "cpu" | "gpu"

    # --- TTS (Qwen3-TTS 1.7B) ---
    qwen_tts_model_id: str = "Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice"
    qwen_tts_model_dir: str = "models/qwen_tts"
    qwen_tts_device: str = "auto"  # "auto" | "cpu" | "cuda:0"
    qwen_tts_language: str = "English"
    # Natural-language delivery instruction sent to Qwen3-TTS on every
    # call (its `instruct` param -- the model's actual mechanism for
    # controlling pace/pitch/emotion, e.g. Qwen's own docs use
    # instruct="说得非常愤怒" for an angry read). Left unset before,
    # the model defaulted to a fast, emphatic, "read-aloud" delivery.
    qwen_tts_instruct: str = (
        "Speak with high energy and genuine excitement, like you can't "
        "wait to tell someone this story -- quick, lively pacing, "
        "animated inflection, real enthusiasm and rising energy on the "
        "interesting parts, but still natural and conversational, never "
        "robotic or shouty."
    )
    # Real Qwen3-TTS-12Hz-1.7B-CustomVoice preset speakers, filtered to the
    # male-sounding presets (Vivian/Serena/Ono_Anna/Sohee are female).
    # Verify against model.get_supported_speakers() for your checkpoint.
    qwen_male_voice_candidates: List[str] = field(
        default_factory=lambda: ["Ryan", "Aiden", "Eric", "Dylan", "Uncle_Fu"]
    )
    # Same idea for the female voice: Vivian ("bright, slightly edgy") is
    # more energetic; Serena ("warm, gentle") is calmer. Ordered
    # energetic-first here, matching qwen_male_voice_candidates. This
    # field didn't exist in config.py before -- tts_engine.py only had a
    # hardcoded internal fallback (Serena-first, i.e. calm-first) that
    # was used whenever config.json didn't set this explicitly.
    qwen_female_voice_candidates: List[str] = field(
        default_factory=lambda: ["Sohee", "Ono_Anna", "Serena", "Vivian"]
    )

    # --- Forced alignment (faster-whisper) ---
    # Previously hardcoded to CPU; "auto" now uses CUDA if available,
    # same detection pattern as qwen_tts_device above.
    whisper_device: str = "auto"       # "auto" | "cpu" | "cuda"
    whisper_compute_type: str = "auto"  # "auto" | "int8" | "float16" | "float32" | ...

    background_blur: int = 0
    random_background: bool = True
    random_music: bool = True
    random_image: bool = True
    # Anti-repeat weighting for random background/music selection: each
    # time a file is picked, its odds of being picked again multiply by
    # this factor (0.5 = each use roughly halves its future odds versus
    # untouched files; 1.0 disables this and falls back to plain uniform
    # random.choice; 0.0 makes a file effectively unpickable until every
    # other file in its folder has also been used at least once).
    background_reuse_decay: float = 0.5
    music_reuse_decay: float = 0.5
    line_padding_px: int = 14
    reveal_ease: str = "ease_out_quart"
    min_line_reveal_sec: float = 0.10
    max_line_reveal_sec: float = 0.30
    video_codec: str = "libx264"
    video_bitrate: str = "12M"
    audio_codec: str = "aac"
    audio_bitrate: str = "192k"
    # Post-mix makeup gain applied to the narration+music mix in
    # renderer.py. This used to be hard-coded to 2.0 (a big boost on
    # top of alignment.py's own loudness-normalize pass), which is why
    # narration came out sounding loud/shouty rather than calm. 1.0 =
    # no extra boost.
    narration_mix_gain: float = 1.0
    use_hardware_acceleration: bool = True
    cache_dir: str = "cache"
    output_dir: str = "output"
    assets_dir: str = "assets"
    models_dir: str = "models"
    log_level: str = "INFO"

    # Derived / runtime
    project_root: str = field(default_factory=lambda: os.path.dirname(
        os.path.dirname(os.path.abspath(__file__))))

    @property
    def width(self) -> int:
        return int(self.resolution.lower().split("x")[0])

    @property
    def height(self) -> int:
        return int(self.resolution.lower().split("x")[1])

    def abspath(self, relative: str) -> str:
        """Resolve a config-relative path (e.g. self.cache_dir) to an
        absolute path rooted at the project directory."""
        return os.path.join(self.project_root, relative)

    def ensure_dirs(self):
        for d in (self.cache_dir, self.output_dir, self.models_dir,
                  self.qwen_tts_model_dir,
                  os.path.join(self.assets_dir, "images"),
                  os.path.join(self.assets_dir, "backgrounds"),
                  os.path.join(self.assets_dir, "music")):
            os.makedirs(self.abspath(d), exist_ok=True)


def load_config(path: str = DEFAULT_CONFIG_PATH) -> AppConfig:
    """Load config.json, falling back to defaults for any missing keys."""
    data = {}
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    else:
        # No config.json present -> proceed with pure defaults rather
        # than crashing. This keeps first-run UX friendly.
        pass

    valid_fields = {f for f in AppConfig.__dataclass_fields__.keys()}
    filtered = {k: v for k, v in data.items() if k in valid_fields}
    cfg = AppConfig(**filtered)
    cfg.ensure_dirs()
    return cfg
