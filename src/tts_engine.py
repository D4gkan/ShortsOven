"""Local Qwen3-TTS CustomVoice narration with per-story delivery instructions.

The batch VOICE_GENDER setting overrides the config's default voice gender.
Speaker presets are tried in order within that gender. Speech is generated
as one continuous take by alignment.py; cache keys include delivery settings.
"""

import hashlib
import json
import os
import wave
from typing import List

from .config import AppConfig
from .exceptions import TTSError
from .logger_setup import get_logger
from .ocr_engine import TextLine

log = get_logger(__name__)

# Qwen3-TTS-Tokenizer-12Hz's native output rate. Only used as a last
# resort if a given qwen_tts build doesn't report its own sample rate;
# soundfile always writes whatever rate we tell it to use, and the WAV
# header records that rate, so downstream code (pydub, wave) reads it
# back correctly regardless.
_DEFAULT_SAMPLE_RATE = 24000


class QwenTTSEngine:
    _MODEL_CACHE = {}  # model_dir -> loaded model, shared within this process

    def __init__(self, cfg: AppConfig):
        self.cfg = cfg
        self.model_dir = self.cfg.abspath(getattr(cfg, "qwen_tts_model_dir", "models/qwen_tts"))
        self._model = None
        self._voice = None  # name of the voice preset actually in use
        self.gender = self._resolve_gender()

    def _resolve_gender(self) -> str:
        """Priority: an explicit AppConfig.voice_gender wins (lets
        config.json or a caller override things); otherwise fall back
        to the VOICE_GENDER environment variable start.bat exports
        from the user's M/F choice; default to "male" if neither is
        present. Anything other than "female" is treated as "male"."""
        gender = getattr(self.cfg, "voice_gender", None) or os.environ.get("VOICE_GENDER")
        gender = (gender or self.cfg.voice).strip().lower()
        return "female" if gender == "female" else "male"

    # ------------------------------------------------------------------
    # Model loading
    # ------------------------------------------------------------------
    def _resolve_device(self) -> str:
        requested = getattr(self.cfg, "qwen_tts_device", "auto")
        if requested and requested != "auto":
            return requested
        try:
            import torch
            if torch.cuda.is_available():
                return "cuda:0"
        except ImportError:
            pass
        return "cpu"

    def _load_model(self):
        if self._model is not None:
            return self._model
        if self.model_dir in QwenTTSEngine._MODEL_CACHE:
            self._model = QwenTTSEngine._MODEL_CACHE[self.model_dir]
            return self._model

        try:
            from qwen_tts import Qwen3TTSModel
        except ImportError as e:
            raise TTSError(
                "qwen-tts is not installed. Run setup.bat (or "
                "`pip install qwen-tts`) to install the local Qwen3-TTS "
                "inference package."
            ) from e

        if not os.path.isdir(self.model_dir) or not os.listdir(self.model_dir):
            raise TTSError(
                f"Qwen3-TTS model weights not found in '{self.model_dir}'. "
                "Run setup.bat (or scripts/download_models.py) to download "
                f"'{getattr(self.cfg, 'qwen_tts_model_id', 'Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice')}' "
                "first."
            )

        device = self._resolve_device()
        log.info(f"Loading offline Qwen3-TTS model ({device})...")

        dtype = None
        try:
            import torch
            dtype = torch.bfloat16 if "cuda" in device else torch.float32
        except ImportError:
            pass  # qwen_tts will pick a sensible default dtype itself

        load_kwargs = {"device_map": device}
        if dtype is not None:
            load_kwargs["dtype"] = dtype

        try:
            model = Qwen3TTSModel.from_pretrained(self.model_dir, **load_kwargs)
        except Exception as e:
            if "cuda" in device:
                log.warning(f"GPU load of Qwen3-TTS failed ({e}); "
                            f"falling back to CPU inference.")
                try:
                    model = Qwen3TTSModel.from_pretrained(self.model_dir, device_map="cpu")
                except Exception as e2:
                    raise TTSError(
                        f"Failed to load Qwen3-TTS model from '{self.model_dir}' "
                        f"on GPU or CPU: {e2}"
                    ) from e2
            else:
                raise TTSError(
                    f"Failed to load Qwen3-TTS model from '{self.model_dir}': {e}. "
                    "This usually means the downloaded weights are incomplete/"
                    "corrupt, or the installed qwen-tts version doesn't match "
                    "these weights -- re-run download_models.py."
                ) from e

        self._model = model
        QwenTTSEngine._MODEL_CACHE[self.model_dir] = model
        return model

    # ------------------------------------------------------------------
    # Voice selection
    # ------------------------------------------------------------------
    # Fallback defaults if config.json doesn't set these lists. These
    # match the speaker names bundled with the Qwen3-TTS-12Hz-1.7B-
    # CustomVoice checkpoint at the time this was written. Different
    # model variants/checkpoints may ship different speakers -- if
    # synthesis fails with "Unsupported speakers: [...] Supported: [...]",
    # that error tells you exactly what your installed model supports;
    # put the ones you want in config.json's qwen_male_voice_candidates /
    # qwen_female_voice_candidates so this default list is never relied on.
    _DEFAULT_MALE_VOICES = ["ryan", "aiden", "dylan", "eric", "uncle_fu"]
    _DEFAULT_FEMALE_VOICES = ["serena", "vivian", "ono_anna", "sohee"]

    def _candidates_for_gender(self) -> List[str]:
        if self.gender == "female":
            return getattr(self.cfg, "qwen_female_voice_candidates", None) or self._DEFAULT_FEMALE_VOICES
        return getattr(self.cfg, "qwen_male_voice_candidates", None) or self._DEFAULT_MALE_VOICES

    def _select_working_voice(self, model) -> str:
        """Try each configured voice preset for the resolved gender,
        in order, until one actually produces audio from this model.
        Never silently substitutes a preset from the other gender --
        mirrors the previous Piper fallback behavior, just scoped to
        whichever gender was requested."""
        candidates = self._candidates_for_gender()
        config_key = ("qwen_female_voice_candidates" if self.gender == "female"
                      else "qwen_male_voice_candidates")
        for voice_name in candidates:
            try:
                self._raw_generate(model, "This is a voice check.", voice_name)
                log.info(f"Using offline {self.gender} voice: {voice_name}")
                return voice_name
            except Exception as e:
                log.warning(f"{self.gender.capitalize()} voice '{voice_name}' unavailable "
                            f"({e}); trying next candidate...")

        raise TTSError(
            f"No offline {self.gender} Qwen3-TTS voice preset could be used "
            f"from {candidates}. Check the voice/speaker names shipped with "
            f"your Qwen3-TTS model in config.json (\"{config_key}\"). "
            "Voices from the other gender are intentionally not used as a "
            "fallback -- fix the candidate list or pick the other gender "
            "at the start.bat prompt instead."
        )

    def get_voice(self) -> str:
        if self._voice is None:
            model = self._load_model()
            self._voice = self._select_working_voice(model)
        return self._voice

    # ------------------------------------------------------------------
    # Generation (adapter over the qwen_tts model's actual call signature)
    # ------------------------------------------------------------------
    def _raw_generate(self, model, text: str, voice_name: str):
        """Require instruction-capable CustomVoice; never discard story tone."""
        if not hasattr(model, "generate_custom_voice"):
            raise TTSError("This model does not support CustomVoice instructions. Run setup.bat with the configured Qwen3-TTS CustomVoice checkpoint.")
        wavs, sr = model.generate_custom_voice(
            text=text, language=self.cfg.qwen_tts_language,
            speaker=voice_name, instruct=self.cfg.qwen_tts_instruct,
        )
        return wavs[0], sr

    def _apply_speed(self, wav_path: str, speed: float):
        """Speeds up (or slows down) the narration WAV at `wav_path`
        in place by `speed` (e.g. 1.08 = 8% faster) WITHOUT changing
        pitch, using ffmpeg's `atempo` filter.

        Earlier attempts used librosa's phase-vocoder time_stretch()
        (warbly/"underwater" artifact on voiced speech) and then
        pydub's Python speedup() (metallic/robotic artifact,
        especially on higher-pitched voices). ffmpeg's atempo is a
        more mature, phase-coherent WSOLA-style stretcher -- the same
        class of algorithm used by video/podcast players' speed
        controls -- and handles voiced speech far more cleanly than
        either. atempo's single-filter range is 0.5-2.0, which covers
        every speed value this app would reasonably use."""
        import shutil
        import subprocess

        if shutil.which("ffmpeg") is None:
            raise TTSError(
                "ffmpeg was not found on PATH; it's required to apply "
                "voice_speed. Install it or set \"voice_speed\": 1.0 in "
                "config.json to skip this step."
            )
        if not (0.5 <= speed <= 2.0):
            raise TTSError(
                f"voice_speed={speed} is outside ffmpeg atempo's supported "
                f"single-filter range (0.5-2.0)."
            )

        tmp_path = wav_path + ".pre_speed.wav"
        os.replace(wav_path, tmp_path)
        cmd = ["ffmpeg", "-y", "-i", tmp_path, "-filter:a", f"atempo={speed:.4f}", wav_path]
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)

        if result.returncode != 0 or not os.path.exists(wav_path):
            # Restore the original so we never leave the cache slot
            # missing/corrupt, and fail loudly rather than silently
            # keep the un-sped audio.
            if os.path.exists(tmp_path):
                os.replace(tmp_path, wav_path)
            raise TTSError(
                "ffmpeg atempo speed adjustment failed:\n"
                f"{result.stdout.decode(errors='ignore')[-1500:]}"
            )
        os.remove(tmp_path)

    @staticmethod
    def _unpack_audio(result):
        import numpy as np
        sr = _DEFAULT_SAMPLE_RATE
        if isinstance(result, tuple) and len(result) == 2:
            audio, sr = result
        elif isinstance(result, dict):
            audio = result.get("audio", result.get("waveform"))
            sr = result.get("sample_rate", result.get("sr", sr))
        elif hasattr(result, "audio"):
            audio = result.audio
            sr = getattr(result, "sample_rate", getattr(result, "sr", sr))
        else:
            audio = result
        # generate_custom_voice() can return a list containing one
        # waveform (already unwrapped by _raw_generate) or, in some
        # fallback paths, a batch list -- normalize either case.
        if isinstance(audio, (list, tuple)) and len(audio) > 0 and hasattr(audio[0], "__len__"):
            audio = audio[0]
        audio = np.asarray(audio, dtype=np.float32).squeeze()
        return audio, int(sr)

    # ------------------------------------------------------------------
    # Public API (unchanged interface)
    # ------------------------------------------------------------------
    def _cache_path(self, text: str) -> str:
        speed = getattr(self.cfg, "voice_speed", 1.0) or 1.0
        key = hashlib.sha256(json.dumps({
            "version": 2, "voice": self.get_voice(), "text": text,
            "speed": speed, "instruct": self.cfg.qwen_tts_instruct,
            "language": self.cfg.qwen_tts_language,
            "model_id": self.cfg.qwen_tts_model_id, "model_dir": self.model_dir,
        }, sort_keys=True).encode("utf-8")).hexdigest()[:24]
        cache_dir = self.cfg.abspath(self.cfg.cache_dir)
        os.makedirs(cache_dir, exist_ok=True)
        return os.path.join(cache_dir, f"tts_{key}.wav")

    def synthesize(self, text: str) -> str:
        """Synthesize text to WAV, cached by content, voice, model and delivery."""
        if not text or not text.strip():
            raise TTSError(
                "Attempted to synthesize empty narration text. This should "
                "have been filtered out by text_cleanup.clean_lines() -- "
                "please report this as a bug rather than working around it."
            )

        out_path = self._cache_path(text)
        if os.path.exists(out_path):
            return out_path

        model = self._load_model()
        voice = self.get_voice()

        try:
            result = self._raw_generate(model, text, voice)
        except TTSError:
            raise
        except Exception as e:
            raise TTSError(f"Qwen3-TTS failed to synthesize narration:\n{e}") from e

        audio, sample_rate = self._unpack_audio(result)
        if audio is None or audio.size == 0:
            raise TTSError("Qwen3-TTS produced empty audio for a non-empty line.")

        try:
            import soundfile as sf
            sf.write(out_path, audio, sample_rate, subtype="PCM_16")
        except Exception as e:
            raise TTSError(f"Failed to write narration WAV '{out_path}': {e}") from e

        speed = getattr(self.cfg, "voice_speed", 1.0) or 1.0
        if abs(speed - 1.0) > 1e-3:
            self._apply_speed(out_path, speed)

        if not os.path.exists(out_path):
            raise TTSError("Qwen3-TTS synthesis finished but no WAV file was written.")
        return out_path

    def synthesize_lines(self, lines: List[TextLine]) -> List[str]:
        """Synthesize separate lines for callers that explicitly need clips."""
        log.info("Generating narration...")
        paths = []
        for line in lines:
            paths.append(self.synthesize(line.text))
        return paths


def get_wav_duration(path: str) -> float:
    with wave.open(path, "rb") as wf:
        frames = wf.getnframes()
        rate = wf.getframerate()
        return frames / float(rate)
