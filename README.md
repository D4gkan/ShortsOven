# AI Reddit Story Video Generator

Fully offline generator for TikTok/Shorts/Reels-style "Reddit story"
videos: a screenshot reveals top-to-bottom in sync with AI narration,
over a looping background video, with background music mixed in.

No paid APIs. No OpenAI. No ElevenLabs. No gTTS/pyttsx3. Everything —
OCR, narration, and rendering — runs locally once setup finishes.

## Quick start (Windows)

1. Install [Python 3.9 through 3.13](https://www.python.org/downloads/)
  and [ffmpeg](https://ffmpeg.org/download.html)
   (add its `bin` folder to PATH).
2. Clone this repository and open its folder.
3. Double-click **`setup.bat`**. This creates or reuses a virtual
  environment, installs everything in `requirements.txt`, and downloads
  the offline OCR/TTS/alignment models. This is the only step that needs
  internet access.
4. Drop files into:
   - `assets/images/` — Reddit screenshot(s), `.png`/`.jpg`
   - `assets/backgrounds/` — background video(s), `.mp4`
   - `assets/music/` — background music, `.mp3`
5. Double-click **`start.bat`**. A random image/background/music
   combo is picked automatically and a finished video is written to
   `output/`.

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
| Narration | `src/tts_engine.py` | Piper TTS (offline, neural, male voice only — never a female/robotic fallback) |
| Alignment | `src/alignment.py` | Builds the narration from real synthesized audio per line, so each line's exact start/end time is measured, not estimated; optionally refined with `faster-whisper` word timestamps |
| Reveal animation | `src/reveal.py` | Builds a black/white mask video: holds still between lines, eases smoothly (accelerate → decelerate → stop) while each line is spoken, always top→bottom only |
| Rendering | `src/renderer.py` | ffmpeg `alphamerge` + `overlay` composites the (never-cropped, never-moved) screenshot through the moving mask onto the background, mixes ducked/faded music with narration, encodes H.264/AAC 1080×1920 |

## Configuration (`config.json`)

```json
{
  "fps": 60,
  "resolution": "1080x1920",
  "music_volume": 0.1,
  "voice_speed": 1.0,
  "voice": "male",
  "random_background": true,
  "random_music": true,
  "random_image": true
}
```

`piper_male_voice_candidates` lists male Piper voices to try in
order — if the first fails to load, the app automatically tries the
next, and **never** falls back to a female or robotic voice.

The requirements pin `torch==2.7.1` and `torchaudio==2.7.1` to matching
releases. This prevents Windows DLL errors caused by incompatible Torch
package versions during PaddleOCR or Qwen TTS startup.

## Caching

- OCR results are cached per image (by content hash) in `cache/`, so
  re-running on the same screenshot skips OCR entirely.
- Narration clips are cached per (voice, text), so unchanged lines are
  never re-synthesized.

## Troubleshooting

- **"ffmpeg was not found on PATH"** — install ffmpeg and add its
  `bin` folder to your system PATH.
- **"No offline male Piper voice model could be found"** — re-run
  `setup.bat` with an active internet connection so the voice models can
  download.
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
assets/{images,backgrounds,music}   your input files (empty by default)
cache/                       OCR/TTS cache + intermediate render files
output/                      finished videos land here
models/                      downloaded offline model weights
```
