"""
asset_manager.py
-----------------
Handles random selection of the three required inputs (background
video, reddit screenshot, background music) and normalizes the
background video (loop if shorter than narration, trim if longer,
scale/crop to fill 1080x1920 while preserving aspect ratio).

Weighted selection (anti-repeat)
---------------------------------
Since main.py runs the pipeline once per process and exits, "don't
repeat the same background/music too often" can only work if pick
history survives across runs -- so it's persisted to a small JSON
file in the cache dir (`selection_usage.json`).

Backgrounds and music are chosen with `_weighted_choice()`: each
file's selection weight is `decay ** times_already_picked`, so every
time a file gets hit its odds of being hit again shrink further
(decay defaults to 0.5 -> each pick roughly halves its future odds
relative to untouched files). It's never a hard exclusion -- a
heavily-used file can still be chosen, just increasingly rarely --
and if every file's weight has decayed to (numerically) zero, the
counts for that category are reset so the pool doesn't get stuck.

Image selection is left as plain `random.choice`, per the request
(only backgrounds and music needed this).
"""

import json
import os
import random
import subprocess
from dataclasses import dataclass
from typing import Optional

from .config import AppConfig
from .exceptions import AssetError
from .logger_setup import get_logger

log = get_logger(__name__)

IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".webp")
VIDEO_EXTS = (".mp4", ".mov", ".mkv", ".webm")
AUDIO_EXTS = (".mp3", ".wav", ".m4a", ".ogg")

USAGE_FILE_NAME = "selection_usage.json"


@dataclass
class SelectedAssets:
    image_path: str
    background_path: str
    music_path: str


class AssetManager:
    def __init__(self, cfg: AppConfig):
        self.cfg = cfg
        self._usage = self._load_usage()

    # ------------------------------------------------------------------
    # Persisted pick-history (for weighted anti-repeat selection)
    # ------------------------------------------------------------------
    def _usage_path(self) -> str:
        return self.cfg.abspath(os.path.join(self.cfg.cache_dir, USAGE_FILE_NAME))

    def _load_usage(self) -> dict:
        path = self._usage_path()
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    return {
                        "backgrounds": dict(data.get("backgrounds", {})),
                        "music": dict(data.get("music", {})),
                    }
            except Exception as e:
                log.warning(f"Could not read '{path}' ({e}); starting a fresh "
                            f"selection history.")
        return {"backgrounds": {}, "music": {}}

    def _save_usage(self):
        path = self._usage_path()
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(self._usage, f, indent=2)
        except Exception as e:
            # Non-fatal: worst case the anti-repeat weighting resets
            # next run, selection itself must never crash the pipeline.
            log.warning(f"Could not save selection history to '{path}': {e}")

    def _weighted_choice(self, files: list, category: str, decay: float) -> str:
        """Picks one file from `files`, weighting down files that have
        already been picked before -- the more often a file has been
        hit, the lower its odds of being hit again (weight =
        decay ** times_picked). Falls back to a plain uniform choice
        if `decay` is disabled (>= 1.0)."""
        counts = self._usage.setdefault(category, {})

        if decay >= 1.0:
            chosen = random.choice(files)
        else:
            decay = max(0.0, decay)
            weights = [decay ** counts.get(os.path.basename(f), 0) for f in files]
            if sum(weights) <= 0:
                # Every file has decayed to (numerically) zero weight --
                # everything's had its turn, so start a fresh cycle
                # instead of getting stuck / raising in random.choices.
                log.info(f"All '{category}' files have been used recently; "
                          f"resetting anti-repeat history for this category.")
                for f in files:
                    counts[os.path.basename(f)] = 0
                weights = [1.0 for _ in files]
            chosen = random.choices(files, weights=weights, k=1)[0]

        key = os.path.basename(chosen)
        counts[key] = counts.get(key, 0) + 1
        self._save_usage()
        return chosen

    def _pick_next_background(self, all_backgrounds: list, exclude_path: str = None) -> str:
        """Picks the next background clip to switch to when the
        current one runs out, using the same weighted anti-repeat
        selection as the initial pick. Excludes the immediately
        preceding clip (if any other option exists) so two clips in
        the sequence are never the same file back-to-back."""
        candidates = all_backgrounds
        if exclude_path and len(all_backgrounds) > 1:
            filtered = [f for f in all_backgrounds if f != exclude_path]
            if filtered:
                candidates = filtered

        if not self.cfg.random_background:
            return candidates[0]
        return self._weighted_choice(candidates, "backgrounds", self.cfg.background_reuse_decay)

    def _list_files(self, subdir: str, exts) -> list:
        folder = self.cfg.abspath(os.path.join(self.cfg.assets_dir, subdir))
        if not os.path.isdir(folder):
            raise AssetError(f"Missing assets folder: {folder}")
        files = [
            os.path.join(folder, f) for f in os.listdir(folder)
            if f.lower().endswith(exts) and not f.startswith(".")
        ]
        if not files:
            raise AssetError(
                f"No usable files found in '{folder}'. "
                f"Add at least one file with extension in {exts}."
            )
        return files

    def select_random(self, forced_image: Optional[str] = None) -> SelectedAssets:
        """Randomly pick one image, one background video, one music
        track, with no user interaction, per the spec.

        `forced_image`, if given, is used verbatim instead of picking
        an image here -- this is how the batch workflow in start.bat
        (which rescans assets/images itself and hands this pipeline
        one specific file per run) selects the image. Background and
        music selection are completely unaffected and still follow
        the normal random/weighted logic below.
        """
        if forced_image:
            image = forced_image
        else:
            image = random.choice(self._list_files("images", IMAGE_EXTS)) \
                if self.cfg.random_image else self._list_files("images", IMAGE_EXTS)[0]
        background = self._weighted_choice(
            self._list_files("backgrounds", VIDEO_EXTS), "backgrounds",
            self.cfg.background_reuse_decay,
        ) if self.cfg.random_background else self._list_files("backgrounds", VIDEO_EXTS)[0]
        music = self._weighted_choice(
            self._list_files("music", AUDIO_EXTS), "music",
            self.cfg.music_reuse_decay,
        ) if self.cfg.random_music else self._list_files("music", AUDIO_EXTS)[0]

        log.info(f"Selected image: {os.path.basename(image)}")
        log.info(f"Selected background: {os.path.basename(background)}")
        log.info(f"Selected music: {os.path.basename(music)}")
        return SelectedAssets(image_path=image, background_path=background, music_path=music)

    def probe_duration(self, media_path: str) -> float:
        """Return duration in seconds via ffprobe."""
        cmd = [
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", media_path,
        ]
        try:
            out = subprocess.check_output(cmd, stderr=subprocess.STDOUT)
            return float(out.decode().strip())
        except Exception as e:
            raise AssetError(f"Could not read duration of '{media_path}': {e}")

    def prepare_background(self, background_path: str, target_duration: float,
                            out_path: str) -> str:
        """
        Builds the final background track for `target_duration`.

        Instead of looping `background_path` on repeat when it's
        shorter than the narration, this keeps appending a NEW
        background clip (same weighted anti-repeat selection used for
        the initial pick, and never immediately repeating the clip
        that just played) each time the running total falls short --
        so a 6s clip under a 30s narration becomes clip A -> clip B ->
        clip C -> ... rather than clip A looped five times.

        Every clip is individually scaled+cropped to fill the target
        resolution (preserving aspect ratio, no letterboxing) before
        being concatenated. The only case that still loops a single
        clip is when the backgrounds folder genuinely contains just
        one file -- there's nothing else to switch to.
        """
        w, h = self.cfg.width, self.cfg.height

        all_backgrounds = self._list_files("backgrounds", VIDEO_EXTS)

        clip_paths = [background_path]
        total_duration = self.probe_duration(background_path)
        while total_duration < target_duration and len(all_backgrounds) > 1:
            next_bg = self._pick_next_background(all_backgrounds, exclude_path=clip_paths[-1])
            clip_paths.append(next_bg)
            total_duration += self.probe_duration(next_bg)
            log.info(f"Background clip ran out before narration ends; "
                     f"switching to: {os.path.basename(next_bg)}")

        # scale to fill then center-crop -> preserves aspect ratio,
        # fills the frame with no letterboxing. Applied identically to
        # every clip so the concat has matching dimensions/timebase.
        vf_common = (
            f"scale={w}:{h}:force_original_aspect_ratio=increase,"
            f"crop={w}:{h},fps={self.cfg.fps},setsar=1,format=yuv420p"
        )

        cmd = ["ffmpeg", "-y"]

        if len(clip_paths) == 1 and total_duration < target_duration:
            # Only one background file exists in the whole folder --
            # nothing to switch to, so loop it as before.
            cmd += ["-stream_loop", "-1", "-i", background_path]
            filter_complex = f"[0:v]{vf_common}[vout]"
        elif len(clip_paths) == 1:
            cmd += ["-i", background_path]
            filter_complex = f"[0:v]{vf_common}[vout]"
        else:
            for p in clip_paths:
                cmd += ["-i", p]
            filter_parts = []
            labels = []
            for i in range(len(clip_paths)):
                label = f"v{i}"
                filter_parts.append(f"[{i}:v]{vf_common}[{label}]")
                labels.append(f"[{label}]")
            filter_parts.append(
                f"{''.join(labels)}concat=n={len(clip_paths)}:v=1:a=0[vout]"
            )
            filter_complex = ";".join(filter_parts)

        video_codec_args = self._video_codec_args()
        cmd += ["-filter_complex", filter_complex, "-map", "[vout]",
                "-t", f"{target_duration:.3f}", "-an", "-r", str(self.cfg.fps),
                *video_codec_args,
                out_path]

        log.info(f"Preparing background video "
                 f"({len(clip_paths)} clip(s), scale/crop to fill)...")
        for p in clip_paths:
            log.info(f"  - {os.path.basename(p)}")
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        if result.returncode != 0:
            # Same retry-with-software-encoder fallback as renderer.py:
            # a hardware encoder can fail on some machines/drivers even
            # when use_hardware_acceleration is enabled.
            if self.cfg.use_hardware_acceleration:
                log.warning("Hardware-accelerated background encode failed, "
                            "retrying with software encoder (libx264)...")
                cmd_sw = list(cmd)
                idx = cmd_sw.index("-c:v")
                cmd_sw[idx + 1] = "libx264"
                result = subprocess.run(cmd_sw, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)

            if result.returncode != 0:
                raise AssetError(
                    f"ffmpeg failed to prepare background video "
                    f"({len(clip_paths)} clip(s): "
                    f"{', '.join(os.path.basename(p) for p in clip_paths)}):\n"
                    f"{result.stdout.decode(errors='ignore')[-3000:]}"
                )
        return out_path

    def _video_codec_args(self):
        """Same hardware-acceleration choice as Renderer._video_codec_args
        in renderer.py -- this step was previously always using the
        software `video_codec` (libx264) regardless of the
        use_hardware_acceleration setting, unlike the final render
        pass, which left GPU encoding unused for this step."""
        if self.cfg.use_hardware_acceleration:
            return ["-c:v", "h264_nvenc", "-preset", "p5", "-b:v", self.cfg.video_bitrate]
        return ["-c:v", self.cfg.video_codec, "-b:v", self.cfg.video_bitrate, "-preset", "medium"]
