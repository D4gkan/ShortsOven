<p align="center">
  <img src="logo.png" alt="ShortsOven logo" width="280">
</p>

<h1 align="center">ShortsOven</h1>

<p align="center">
  <a href="https://www.python.org/downloads/"><img src="https://img.shields.io/badge/Python-3.11-3776AB?logo=python&amp;logoColor=white" alt="Python 3.11"></a>
  <img src="https://img.shields.io/badge/Platform-Windows-0078D4" alt="Windows">
  <a href="https://ollama.com/"><img src="https://img.shields.io/badge/Tone-Ollama-111111?logo=ollama&amp;logoColor=white" alt="Ollama tone analysis"></a>
  <a href="https://github.com/QwenLM/Qwen3-TTS"><img src="https://img.shields.io/badge/Voice-Qwen3--TTS-7C3AED" alt="Qwen3-TTS"></a>
  <a href="https://ffmpeg.org/"><img src="https://img.shields.io/badge/Video-FFmpeg-007808?logo=ffmpeg&amp;logoColor=white" alt="FFmpeg"></a>
  <img src="https://img.shields.io/badge/Inference-Local-2EA44F" alt="Local inference">
</p>

Turn story screenshots into vertical videos with narration that fits the situation.
ShortsOven reads the screenshot, asks your local Ollama model how it should sound,
then generates a continuous Qwen3-TTS narration. The screenshot reveals from top to
bottom over background footage, with music mixed underneath.

## What happens for each story

1. **Read:** PaddleOCR extracts text lines and their positions.
2. **Clean:** remove username-like tokens and correct common spelling errors.
3. **Choose delivery:** Ollama receives the complete cleaned story and returns a
   tone, a natural-language delivery instruction, and a speed multiplier.
4. **Speak:** Qwen3-TTS reads that same text in one continuous take using the
   selected delivery and your chosen voice gender.
5. **Synchronize:** faster-whisper transcribes the audio with word timestamps;
   fuzzy matching maps those words back to screenshot lines. Unmatched lines
   use a logged timing fallback, so alignment is best-effort rather than exact.
6. **Render:** FFmpeg combines narration, music, background clips and the reveal
   animation. Default output is 1080 × 1920, 60 fps, H.264/AAC.

Sad stories can receive a restrained, compassionate delivery; jokes can be dry
and playful; suspense can build gradually. Ollama provides one configuration for
each story, including instructions for emotional changes within the narration.
It does not rewrite the text or select the speaker. Delivery quality depends on
both the tone model and Qwen's interpretation of the instruction.

## Setup on Windows

1. Install **Python 3.11** with the Windows Python launcher. This is the supported
   target for the compatibility constraints in `requirements.txt`.
2. Install [FFmpeg](https://ffmpeg.org/download.html). Put the folder containing
   both `ffmpeg.exe` and `ffprobe.exe` on `PATH`.
3. Install and open [Ollama](https://ollama.com/download/windows).
4. Double-click `setup.bat`. It checks Ollama, pulls the configured tone model if
   missing, installs Python dependencies into `venv`, checks their compatibility,
   and downloads OCR, TTS and alignment models. Downloads require internet and
   several gigabytes of free disk space. Setup stops if a required step fails.
5. Add your media to the folders below, then run `start.bat`.

An existing environment must use Python 3.11. If it uses another version or its
interpreter is broken, rename `venv` and rerun setup to create a fresh environment.
The scripts use `venv\Scripts\python.exe` directly; activation is unnecessary.
A capable NVIDIA GPU can speed up inference, but CPU execution is supported and
can be slow. GPU use requires compatible drivers and CUDA-enabled dependencies.

## Inputs and running

| Folder | Supported files |
|---|---|
| `assets/images/` | PNG, JPG, JPEG, WebP story screenshots |
| `assets/backgrounds/` | MP4, MOV, MKV, WebM background clips |
| `assets/music/` | MP3, WAV, M4A, OGG music tracks |

All three categories need at least one file. For longer narration, background
clips are joined until they cover the story; a single available clip loops.
Use clear screenshots: cleanup can mistake mixed letter/digit tokens for handles,
and spelling correction can alter unusual words.

**Batch:** double-click `start.bat`, choose M or F once, and let it process
`assets/images/`. It writes logs to `logs/`, gives each finished video a randomized
hashtag filename, and **deletes its source screenshot after successful output
verification and renaming**. Keep copies of screenshots you want to retain.
The batch stops on failure and keeps the failed screenshot. Escape during the
timer stops the Python worker. The batch clears intermediate cache files after
each completed attempt.

**Single video, retaining the source:**

```powershell
.\venv\Scripts\python.exe main.py --image "C:\Stories\story.png"
```

Omit `--image` to select a random screenshot from `assets/images/`. Results go to
`output/`. Run one job at a time because intermediate file names are shared.

## Ollama tone settings

Edit `config.json`:

```json
{
  "ollama_url": "http://127.0.0.1:11434",
  "ollama_model": "qwen2.5:7b-instruct-q4_K_M",
  "ollama_timeout_sec": 180
}
```

The default matches the general instruction model installed on the development
PC. To use another local instruction model, set its exact name from `ollama list`.
Check or prepare it with:

```powershell
.\venv\Scripts\python.exe scripts\check_ollama.py --pull
```

The integration uses Ollama's [structured JSON outputs](https://docs.ollama.com/capabilities/structured-outputs)
and [chat API](https://docs.ollama.com/api/chat). It validates all returned fields
and limits speed to 0.85–1.15×. Ollama is asked to unload its model after responding,
freeing memory for TTS. Requests time out after the configured interval.
Stories above 16,000 cleaned characters are rejected rather than silently cut off.
If Ollama is unavailable or returns invalid settings, the job stops before TTS.
There is no automatic energetic fallback.

Ollama is a separate application, not a Python requirement. With the default
loopback address and downloaded local models, story processing stays on your PC.
Changing the URL to another machine sends the cleaned story there.

## Other configuration

| Setting | Purpose |
|---|---|
| `voice` | Default `male` or `female` for single runs; batch choice overrides it |
| `qwen_male_voice_candidates`, `qwen_female_voice_candidates` | Speaker presets tried in order within the chosen gender |
| `qwen_tts_model_id`, `qwen_tts_model_dir` | CustomVoice checkpoint and local weights directory |
| `qwen_tts_device` | `auto`, `cpu`, or a CUDA device such as `cuda:0` |
| `paddleocr_device` | `auto`, `cpu`, or `gpu`; default auto uses CPU unless GPU is enabled |
| `ocr_lang`, `qwen_tts_language` | OCR and speech languages; alignment currently uses English `base.en` |
| `whisper_device`, `whisper_compute_type` | Alignment device and numeric precision |
| `music_volume`, `narration_volume`, `narration_mix_gain` | Music, voice and final mix levels |
| `resolution`, `fps`, `video_bitrate` | Output dimensions, frame rate and bitrate |
| `use_hardware_acceleration` | Try NVIDIA NVENC encoding, with a software fallback |

Tone and speed are selected anew for each story; static `qwen_tts_instruct` and
`voice_speed` values are overridden by the Ollama result. Configuration paths
may be absolute or project-relative. The batch launcher uses `assets/images/`,
`logs/` and `cache/` directly; keep those directory defaults for batch operation.

## Models and storage

- `models/qwen_tts/` contains Qwen3-TTS 1.7B CustomVoice and its bundled
  `speech_tokenizer/`. A separate tokenizer download is unnecessary.
- PaddleOCR weights live in Paddle's normal user cache.
- faster-whisper `base.en` weights live in the Hugging Face cache.
- Ollama manages its own model storage outside this project.
- `cache/` holds OCR results, speech and intermediate video files. OCR is keyed
  by image contents. Speech caching includes text, speaker, tone instruction,
  speed, language and model identity. Single runs retain the cache; batch runs
  clear it, including background/music selection history.
- `output/` holds finished videos; `logs/` holds batch diagnostics.

Keep media, model weights, environments and generated artifacts out of Git;
`.gitignore` handles these paths. `PROMPT.txt` is the optional screenshot-generation
brief, not a runtime instruction file.

## Troubleshooting

- **Ollama connection error:** open Ollama or run `ollama serve`; check the URL.
- **Missing tone model:** run the check command above with `--pull`.
- **Tone timeout:** increase `ollama_timeout_sec` or choose a smaller installed
  instruction model. Cold model loading can take longer than later requests.
- **Invalid tone response:** retry or select another instruction-following model.
- **Missing Qwen/OCR/Whisper weights:** rerun setup or
  `venv\Scripts\python.exe scripts\download_models.py`.
- **GPU errors:** try `qwen_tts_device: "cpu"`, `whisper_device: "cpu"` and
  `use_hardware_acceleration: false`. For OCR use `paddleocr_device: "cpu"`.
- **Package errors:** read the actual install/import error. Setup retains matching
  Torch/Torchaudio versions and the existing Windows compatibility constraints;
  it does not change Windows security settings.

## Development

```powershell
.\venv\Scripts\python.exe -m unittest discover -s tests -v
```

Focused tests cover the tone API boundary, rejection paths, pipeline ordering,
TTS instruction forwarding and cache separation. They dont download models.

```text
main.py                     single-story pipeline
config.json                 application settings
requirements.txt            Python dependencies and compatibility constraints
setup.bat / start.bat       install / batch run
src/                        OCR, tone, TTS, alignment, reveal and rendering
scripts/check_ollama.py      Ollama readiness and optional model pull
scripts/download_models.py required OCR/TTS/alignment downloads
scripts/batch_status.ps1     elapsed timer and Escape monitoring
tests/                      current tone integration regression tests
logo.png / PROMPT.txt       branding / optional screenshot creation brief
assets/                     source images, footage and music
```
