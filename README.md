# ShortsOven

[![Windows](https://img.shields.io/badge/platform-Windows-0078D4?logo=windows&logoColor=white)](https://www.microsoft.com/windows)
[![Python](https://img.shields.io/badge/python-3.9--3.13-3776AB?logo=python&logoColor=white)](https://www.python.org/downloads/)
[![Offline](https://img.shields.io/badge/runtime-fully%20offline-2EA44F)](#offline-models)
[![FFmpeg](https://img.shields.io/badge/media-FFmpeg-007808?logo=ffmpeg&logoColor=white)](https://ffmpeg.org/)

Fully offline generator for TikTok/Shorts/Reels-style "Reddit story"
videos: a screenshot reveals top-to-bottom in sync with AI narration,
over a looping background video, with background music mixed in.

No paid APIs. No OpenAI. No ElevenLabs. No gTTS/pyttsx3. Everything —
OCR, narration, and rendering — runs locally once setup finishes.

## Quick Start (Windows)

1. Install [Python 3.9 through 3.13](https://www.python.org/downloads/).
  Python 3.11-3.13 is recommended because PaddlePaddle does not currently
  provide wheels for every newer Python release.
2. Install [FFmpeg](https://ffmpeg.org/download.html) and add its `bin`
  directory to the Windows `PATH`.
3. Clone this repository and open the project folder.
4. Double-click `setup.bat`. It creates `venv`, installs `requirements.txt`,
  and downloads the local AI models. Setup is the only step that needs
  internet access.
5. Add source files to `assets/images/`, `assets/backgrounds/`, and
  `assets/music/`.
6. Double-click `start.bat`, choose a voice gender with `M` or `F`, and wait
  for each video. The console shows a live elapsed timer. Press `Esc` once
  during `Working (...)` to stop the active video safely. The source image is
  kept when a job is interrupted or fails.
7. Find completed videos in `output/` and diagnostic logs in `logs/`.

## Repository and asset policy

Large local assets, generated videos, logs, caches, and downloaded model
weights are intentionally excluded from GitHub. The `assets/` folders contain
`.gitkeep` placeholders so they are recreated when the repository is cloned.
Use media that you own or have permission to use; do not commit copyrighted
music, stock footage, personal screenshots, or model weights to this repo.

The application is a local Windows batch workflow rather than a hosted web
service. After cloning, `setup.bat` downloads the required models into the
ignored `models/` directory and `start.bat` runs the generator offline.
Both scripts call `venv\Scripts\python.exe` directly, so they do not depend
on virtual-environment activation or the system Python selected by PATH.

## How it works

| Stage | Module | What it does |
|---|---|---|
| Asset selection | `src/asset_manager.py` | Randomly picks one image, one background, one music track; loops/trims the background to match narration length |
| OCR | `src/ocr_engine.py` | PaddleOCR detects text **lines** (rows), not sentences, with `x/y/width/height` for each |
| Cleanup | `src/text_cleanup.py` | SymSpell fixes minor OCR typos (`Thls` → `This`) before narration |
| Narration | `src/tts_engine.py` | Qwen3-TTS CustomVoice generates local neural narration using the selected voice gender |
| Alignment | `src/alignment.py` | Builds the narration from real synthesized audio per line, so each line's exact start/end time is measured, not estimated; optionally refined with `faster-whisper` word timestamps |
| Reveal animation | `src/reveal.py` | Builds a black/white mask video: holds still between lines, eases smoothly (accelerate → decelerate → stop) while each line is spoken, always top→bottom only |
| Rendering | `src/renderer.py` | ffmpeg `alphamerge` + `overlay` composites the (never-cropped, never-moved) screenshot through the moving mask onto the background, mixes ducked/faded music with narration, encodes H.264/AAC 1080×1920 |

## Configuration (`config.json`)

The checked-in configuration is tuned for the current developer PC: automatic
device selection, CPU-safe PaddleOCR, 1080x1920 output, hardware-accelerated
encoding when available, and the Qwen3-TTS 1.7B CustomVoice model.

Important fields include:

| Field | Purpose |
|---|---|
| `qwen_tts_model_id` | Hugging Face model repository used by the downloader |
| `qwen_tts_model_dir` | Local Qwen model directory, relative to the project |
| `qwen_tts_device` | `auto`, `cpu`, or a CUDA device such as `cuda:0` |
| `qwen_male_voice_candidates` | Qwen speaker presets tried for male narration |
| `qwen_female_voice_candidates` | Qwen speaker presets tried for female narration |
| `paddleocr_device` | OCR device selection; use `cpu` for maximum compatibility |
| `whisper_device` | Alignment device: `auto`, `cpu`, or `cuda` |
| `whisper_compute_type` | Alignment precision such as `int8` or `float16` |
| `cache_dir`, `output_dir`, `assets_dir`, `models_dir` | Project-relative storage locations |

For example, to use a model downloaded elsewhere:

```json
{
  "qwen_tts_model_dir": "D:/AI/ShortsOven/qwen_tts",
  "qwen_tts_device": "cuda:0",
  "whisper_device": "cuda",
  "whisper_compute_type": "float16"
}
```

Paths may be absolute or project-relative. After changing
`qwen_tts_model_id`, run `venv\Scripts\python.exe scripts\download_models.py`
again. If the new checkpoint has different speaker names, replace the voice
candidate lists with names supported by that checkpoint. The application does
not silently switch to another gender or a system voice.

## Offline Models

`setup.bat` downloads the following models once:

1. **PaddleOCR PP-OCR** for text detection and recognition. PaddleOCR stores
  its downloaded weights in its normal local Paddle cache.
2. **Qwen3-TTS 1.7B CustomVoice** in `qwen_tts_model_dir` (default:
  `models/qwen_tts/`).
3. **Qwen3-TTS Tokenizer** in `models/qwen_tts_tokenizer/`.
4. **faster-whisper `base.en`** in the local Hugging Face cache for forced
  alignment. The model is required for line timing.

The model files are intentionally ignored by Git because they are large.
Developers can use different local model locations by changing the paths in
`config.json`; they do not need to change the Python source. Run the downloader
again after changing a model ID or deleting a model directory.

The requirements pin `torch==2.7.1` and `torchaudio==2.7.1` to matching
releases. This prevents Windows DLL errors caused by incompatible Torch
package versions during PaddleOCR or Qwen TTS startup.

## Caching

- OCR results are cached per image (by content hash) in `cache/`, so
  re-running on the same screenshot skips OCR entirely.
- Narration clips are cached per (voice, text), so unchanged lines are
  never re-synthesized.

## Batch Controls

`start.bat` runs one visible console session and launches the Python worker in
the background. `scripts/batch_status.ps1` keeps the timer and Escape monitor
alive for the full duration of each video, so the displayed completion time is
measured from the same monitor. `scripts/check_escape.ps1` is retained as a
small standalone key-state check for troubleshooting.

Pressing `Esc` terminates the active Python process tree, removes temporary
control files, keeps the source image, and exits with `Work interrupted`.

## Troubleshooting

- **"ffmpeg was not found on PATH"** — install ffmpeg and add its
  `bin` folder to your system PATH.
- **"Qwen3-TTS model weights not found"** — re-run `setup.bat`, or run
  `venv\Scripts\python.exe scripts\download_models.py` directly.
- **Unsupported Qwen speaker names** — inspect the speakers supported by the
  downloaded checkpoint and update the matching voice candidate list in
  `config.json`.
- **"Ignoring invalid distribution ~orch"** — an interrupted Torch install
  left temporary folders in the virtual environment. Run `setup.bat` again;
  it repairs the matching Torch and Torchaudio installation.
- **Torch DLL or `WinError 127` errors** — close running generator windows
  and run `setup.bat` again so the pinned Torch packages are reinstalled.
- **The setup log uses Python 3.14** — the scripts should report the venv
  interpreter and Python 3.11, 3.12, or 3.13. If the venv was copied from
  another folder, run `setup.bat` again to recreate it in this project.
- **"OCR found no text"** — use a clearer, higher-resolution
  screenshot.
- Full stack traces and clear explanations are always printed to the
  console — the app never fails silently.

## Project structure

```
setup.bat / start.bat        one-click install & run
requirements.txt             Python dependencies
config.json                  all tunables
main.py                      pipeline entry point
src/                         config, logging, OCR, TTS, alignment,
                              reveal animation, rendering, asset mgmt
scripts/download_models.py   one-time offline model downloader
scripts/batch_status.ps1      live timer and Escape monitor
scripts/check_escape.ps1      standalone Escape key check
assets/{images,backgrounds,music}   your input files (empty by default)
cache/                       OCR/TTS cache + intermediate render files
output/                      finished videos land here
models/                      downloaded Qwen model weights
models/qwen_tts_tokenizer/   downloaded Qwen tokenizer files
```
