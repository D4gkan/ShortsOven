# Changelog

## 1.0.0 — 2026-09-19

First explicitly versioned ShortsOven release.

### Narration

- Local Ollama chooses a tone and delivery instruction from the cleaned story.
- Playback speed defaults to 1.10× and remains under application control.
- Story-appropriate energy is encouraged without gloomy or lethargic delivery.
- Whisper, hushed and ASMR requests are filtered before TTS; clear, fully voiced
  delivery instructions are always appended.
- Speech cache keys include the effective delivery instruction and speed.

### Conversation visuals

- Reveal one narrated line per addition in a connected upward-moving stack.
- Move by the incoming section's height; hold still between additions.
- Retain every screenshot region, including usernames, pictures and footers.
- Start slightly above screen center with zero added spacing, feathered outer
  edges and a subtle shadow. Preserve source proportions and readable text.

### Running and reliability

- Compact batch interface with stage updates, elapsed time and encoding progress.
- Finite FFmpeg inputs, controlled filter threading, stall/overall timeouts and
  software-encoding fallback.
- Preserve working files on failure and stop child processes on Escape.
- Add `main.py --version`, a README version badge and this changelog.

### Validation

- 22 automated tests cover tone handling, delivery constraints, screenshot
  preservation, animation geometry, shadow placement and render timeouts.
- Real FFmpeg rendering and shadow appearance were checked locally. These tests
  do not establish that every generated voice will follow every instruction.
