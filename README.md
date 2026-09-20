<p align="center">
  <img src="logo.png" alt="ShortsOven logo" width="280">
</p>

<h1 align="center">ShortsOven</h1>

<p align="center">
  <a href="https://github.com/D4gkan/ShortsOven/tree/v1.0.0"><img src="https://img.shields.io/badge/version-1.0.0-22c55e" alt="Version 1.0.0"></a>
  <a href="https://www.python.org/downloads/"><img src="https://img.shields.io/badge/Python-3.11-3776AB?logo=python&amp;logoColor=white" alt="Python 3.11"></a>
  <img src="https://img.shields.io/badge/Platform-Windows-0078D4" alt="Windows">
  <a href="https://ollama.com/"><img src="https://img.shields.io/badge/Tone-Ollama-111111?logo=ollama&amp;logoColor=white" alt="Ollama tone analysis"></a>
  <a href="https://github.com/QwenLM/Qwen3-TTS"><img src="https://img.shields.io/badge/Voice-Qwen3--TTS-7C3AED" alt="Qwen3-TTS"></a>
  <a href="https://ffmpeg.org/"><img src="https://img.shields.io/badge/Video-FFmpeg-007808?logo=ffmpeg&amp;logoColor=white" alt="FFmpeg"></a>
  <img src="https://img.shields.io/badge/Inference-Local-2EA44F" alt="Local inference">
</p>

Turn story screenshots into vertical videos with narration that fits the situation.
ShortsOven reads the screenshot, asks your local Ollama model how it should sound,
then generates a continuous Qwen3-TTS narration. Cropped conversation sections
build into a connected upward-moving feed over background footage, with music
mixed underneath.

## Version 1.0.0

- **Adaptive, engaged narration:** Ollama chooses the story's tone while TTS
  keeps delivery lively, clear and fully voiced. An acoustic check rejects likely
  whispered takes and retries once with stronger vocal projection. If both takes
  fail, generation stops instead of accepting the rejected audio.
- **Consistent pace:** playback speed defaults to **1.10×**; Ollama cannot change it.
- **One line at a time:** connected screenshot sections slide upward only when
  new content arrives. Each move equals the new section's height, with no added gap.
- **Complete visuals:** usernames, embedded pictures and footers remain visible
  even when excluded from speech. The first section starts slightly above center,
  with feathered outer edges and subtle shadows.
- **Picture reveals:** broad embedded photos get their own chunk and a **0.5-second
  settled hold**, with narration paused. Entrance/exit slides add time around that
  hold; the next spoken line follows afterward. Text found inside a detected photo
  stays in the picture instead of becoming a separate narrated line.
- **Clearer operation:** compact launcher, live stage/progress display, bounded
  render waits and retained working files after failures.

See [CHANGELOG.md](CHANGELOG.md) for release notes.

## License

ShortsOven is provided under the [ShortsOven Non-Redistribution License](LICENSE).
You may inspect and modify the code for private local use, but you may not
redistribute, publish, share, sell, sublicense, or present the project or a
modified version as your own without prior written permission.

## What happens for each story

1. **Read:** PaddleOCR extracts text lines and their positions.
2. **Clean narration:** remove username-like tokens and correct common spelling
   errors in the spoken text. Original screenshot content stays intact visually.
3. **Choose delivery:** Ollama receives the complete cleaned story and returns a
   tone and a natural-language delivery instruction. Playback speed stays at 1.10×.
4. **Speak:** Qwen3-TTS reads that same text in one continuous take using the
   selected delivery and your chosen voice gender.
5. **Synchronize:** faster-whisper transcribes the audio with word timestamps;
   fuzzy matching maps those words back to screenshot lines. Unmatched lines
   use a logged timing fallback, so alignment is best-effort rather than exact.
   Picture pauses are inserted into the audio and all later timestamps shift together.
6. **Render:** nearby OCR lines form short cropped sections. The first appears
   slightly above screen center. Each new section joins below and pushes the whole stack
   upward with smooth easing; the stack holds still between additions. Old
   sections leave through the top without shrinking. FFmpeg combines the feed,
   narration, music and background at 1080 × 1920, 60 fps, H.264/AAC by default.

Serious stories receive compassionate but engaged delivery; jokes can be dry
and playful; suspense can build gradually. Ollama provides one configuration for
each story, including instructions for emotional changes within the narration.
It does not rewrite the text or select the speaker. Delivery quality depends on
both the tone model and Qwen's interpretation of the instruction.

The voiced-speech check measures periodicity over sustained audio windows, not
volume alone. It is a heuristic: it can miss brief or partly voiced whispers and
can occasionally reject unusual normal speech. Old narration caches are invalidated
for this change. Picture detection uses broad visual regions on light/dark post
backgrounds; tiny images or unusual layouts may remain attached to nearby text.

## Installation on Windows

1. Install **Python 3.11** with the Windows Python launcher. This is the supported
   target for the compatibility constraints in `requirements.txt`.
2. Install [FFmpeg](https://ffmpeg.org/download.html). Put the folder containing
   both `ffmpeg.exe` and `ffprobe.exe` on `PATH`.
3. Install and open [Ollama](https://ollama.com/download/windows).
4. Double-click `setup.bat`. It checks Ollama, pulls the configured tone model if
   missing, installs Python dependencies into `venv`, checks their compatibility,
   and downloads OCR, TTS and alignment models. Downloads require internet and
   several gigabytes of free disk space. Setup stops if a required step fails.
5. Add media to the input folders below, then double-click `start.bat`.

An existing environment must use Python 3.11. If it uses another version or its
interpreter is broken, rename `venv` and rerun setup to create a fresh environment.
The scripts use `venv\Scripts\python.exe` directly; activation is unnecessary.
A capable NVIDIA GPU can speed up inference, but CPU execution is supported and
can be slow. GPU use requires compatible drivers and CUDA-enabled dependencies.

## Configuration

ShortsOven reads runtime settings from `config.json`. The checked-in file is a
working default configuration, so you can run the project without changing it.
Configuration paths may be absolute or relative to the project folder.

### Media inputs

| Folder | Supported files |
|---|---|
| `assets/images/` | PNG, JPG, JPEG, WebP story screenshots |
| `assets/backgrounds/` | MP4, MOV, MKV, WebM background clips |
| `assets/music/` | MP3, WAV, M4A, OGG music tracks |

All three categories need at least one file. For longer narration, background
clips are joined until they cover the story; a single available clip loops.
Use clear screenshots: cleanup can mistake mixed letter/digit tokens for handles,
and spelling correction can alter unusual words.

### Ollama tone settings

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
and keeps playback speed fixed by `voice_speed` (default 1.10×). Ollama chooses
tone, not speed. Ollama is asked to unload its model after responding,
freeing memory for TTS. Requests time out after the configured interval.
Stories above 16,000 cleaned characters are rejected rather than silently cut off.
If Ollama is unavailable or returns invalid settings, the job stops before TTS.
Delivery stays lively and engaged while matching the story; serious subjects do
not receive an inappropriate celebratory voice. Gloomy, lethargic delivery is
discouraged in both tone selection and TTS. Ollama is instructed never to request
whispering. TTS removes conflicting whisper/hushed/ASMR instructions and appends
a mandatory clear, fully voiced delivery instruction; speech caching includes this rule.

Ollama is a separate application, not a Python requirement. With the default
loopback address and downloaded local models, story processing stays on your PC.
Changing the URL to another machine sends the cleaned story there.

### Conversation animation

Story text is narrated, beginning with the opening section positioned slightly
above screen center (46% of frame height). Each addition includes one narrated OCR line by default. Visual
sections form contiguous strips covering the entire original screenshot: usernames,
headers, embedded pictures, whitespace and footers are retained. Unspoken content
between narrated lines appears with the following line; trailing content appears
with the final line. Filtering a username from speech never removes its pixels.
The optional larger chunk size also splits at sentence endings and paragraph gaps.
Each section preserves the screenshot's proportions
at a consistent width, with no scaling down as the conversation grows.

Movement happens only when a section is added. All visible sections share the
same smoothly eased vertical offset, with sections touching and no added gap.
Each addition moves the stack by exactly the new section height plus configured
spacing. The bottom of the feed stays anchored near the initial section; older sections
travel off the top. When there is a speech gap, the slide uses it. With continuous
speech, the slide occupies just the short introduction of the next section, then
stops. This is not an automatic scrolling animation.

A soft shadow separates the connected stack from the background without adding gaps.
Only the outer alpha boundary is feathered; touching section boundaries stay opaque.
Screenshot pixels are not blurred,
and detected text areas remain fully opaque. A working image copy supplies both
OCR and crops, so moving the original during generation cannot break the render.

| Setting | Default | Purpose |
|---|---|---|
| `conversation_chunk_lines` | `1` | OCR lines per addition: one line at a time by default (1–8) |
| `conversation_slide_sec` | `0.32` | Eased addition duration in seconds (0.1–1) |
| `conversation_anchor_y` | `0.46` | First section's center, as a fraction of screen height |
| `conversation_gap_px` | `0` | Added spacing between sections; 0 joins them without gaps |
| `conversation_feather_px` | `10` | Outer opacity feather width, in output pixels; 0 disables |
| `conversation_shadow_opacity` | `0.22` | Subtle black shadow opacity; 0 disables |
| `conversation_shadow_radius_px` | `10` | Shadow blur radius in output pixels |
| `line_padding_px` | `14` | Preferred cut spacing after a narrated line; all intervening pixels remain in the next section |

The old line-mask easing and reveal-duration settings are no longer used.

Rendering uses finite input durations and a single filter-processing thread to
avoid stalled multi-input filter graphs. Encoding progress is logged every five
seconds. `render_stall_timeout_sec` defaults to 120 seconds without output-time
progress; `render_timeout_sec` caps each encoding attempt at 900 seconds. A failed
hardware attempt retries once in software. Failed-job cache files are retained.

## Other configuration

| Setting | Purpose |
|---|---|
| `voice_speed` | Playback multiplier, default `1.10`; independent of Ollama |
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

Tone is selected anew for each story; static `qwen_tts_instruct` is overridden
by the Ollama result. `voice_speed` stays at the configured 1.10× and is never
overridden by Ollama. Configuration paths may be absolute or project-relative. The batch launcher uses `assets/images/`,
`logs/` and `cache/` directly; keep those directory defaults for batch operation.

## Running

**Batch:** double-click `start.bat`, choose M or F once, and let it process
`assets/images/`. It writes logs to `logs/`, gives each finished video a randomized
hashtag filename, and **deletes its source screenshot after successful output
verification and renaming**. Keep copies of screenshots you want to retain.
The batch stops on failure and keeps the failed screenshot. Escape during the
timer stops the worker and its child processes. The batch clears intermediate
cache files after successful jobs and retains them
after failures for diagnosis and recovery. Encoding progress appears beside the timer.

**Single video, retaining the source:**

```powershell
.\venv\Scripts\python.exe main.py --image "C:\Stories\story.png"
```

Omit `--image` to select a random screenshot from `assets/images/`. Results go to
`output/`. Run one job at a time because intermediate file names are shared.

## Models and storage

- `models/qwen_tts/` contains Qwen3-TTS 1.7B CustomVoice and its bundled
  `speech_tokenizer/`. A separate tokenizer download is unnecessary.
- PaddleOCR weights live in Paddle's normal user cache.
- faster-whisper `base.en` weights live in the Hugging Face cache.
- Ollama manages its own model storage outside this project.
- `cache/` holds OCR results, speech and intermediate video files. OCR is keyed
  by image contents. Speech caching includes text, speaker, tone instruction,
  speed, language and model identity. Single runs retain the cache; successful batch jobs
  clear it, including background/music selection history. Failed jobs retain it.
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
TTS delivery rules, cache separation, complete screenshot preservation, precise
scroll distances, shadows and encoding timeouts. The 22 tests run without model downloads.

Check the application version with:

```powershell
.\venv\Scripts\python.exe main.py --version
```

Preview the launcher layout without generating a video with `start.bat --preview`.

```text
main.py                     single-story pipeline
config.json                 application settings
requirements.txt            Python dependencies and compatibility constraints
setup.bat / start.bat       install / batch run
src/                        OCR, tone, TTS, alignment, reveal and rendering
scripts/check_ollama.py      Ollama readiness and optional model pull
scripts/download_models.py  required OCR/TTS/alignment downloads
scripts/batch_status.ps1     elapsed timer and Escape monitoring
tests/                      narration, animation and watchdog regression tests
CHANGELOG.md                version history
logo.png / PROMPT.txt       branding / optional screenshot creation brief
assets/                     source images, footage and music
```
