"""
renderer.py
-----------
Final compositing pass. Prefers raw ffmpeg filters over MoviePy for
speed. Pipeline:

  1. Screenshot is scaled (never cropped/re-encoded lossily) to its
     fixed on-screen display size and looped as a static video for
     the narration's duration.
  2. The reveal mask video (from reveal.py) is merged into that
     image's alpha channel with `alphamerge` -- this is the "moving
     clipping mask", the image pixels themselves never change.
  3. The now-transparent-where-hidden image is `overlay`'d onto the
     prepared background video at a FIXED centered position (the
     image itself never moves, scales, or shakes -- only the mask
     reveals more of it over time).
  4. Narration + music are mixed: music is volume-reduced to
     `music_volume` (default 10%) with fade in/out, narration stays
     at full, clear volume.
  5. Output is encoded to H.264/AAC at the configured resolution/fps.
"""

import os
import shutil
import subprocess

from .config import AppConfig
from .exceptions import FFmpegNotFoundError, RenderError
from .logger_setup import get_logger

log = get_logger(__name__)


def _require_ffmpeg():
    if shutil.which("ffmpeg") is None:
        raise FFmpegNotFoundError(
            "ffmpeg was not found on your PATH. Install it from "
            "https://ffmpeg.org/download.html (Windows: download a build, "
            "add its /bin folder to PATH) and re-run start.bat."
        )


class Renderer:
    def __init__(self, cfg: AppConfig):
        self.cfg = cfg

    def render(self, background_path: str, image_path: str, mask_path: str,
               narration_path: str, music_path: str, duration_sec: float,
               display_w: int, display_h: int, out_path: str) -> str:
        _require_ffmpeg()
        log.info("Rendering video...")

        w, h = self.cfg.width, self.cfg.height
        fade_in = self.cfg.music_fade_in_sec
        fade_out = self.cfg.music_fade_out_sec
        fade_out_start = max(0.0, duration_sec - fade_out)

        bg_filters = "format=yuv420p"
        if self.cfg.background_blur and self.cfg.background_blur > 0:
            bg_filters = f"boxblur={self.cfg.background_blur}:1,{bg_filters}"

        filter_complex = (
            f"[0:v]{bg_filters}[bg];"
            f"[1:v]scale={display_w}:{display_h}[imgscaled];"
            f"[imgscaled][2:v]alphamerge[imgalpha];"
            f"[bg][imgalpha]overlay=x=(W-w)/2:y=(H-h)/2:shortest=1,"
            f"format=yuv420p[vout];"
            f"[4:a]volume={self.cfg.music_volume},"
            f"afade=t=in:st=0:d={fade_in},"
            f"afade=t=out:st={fade_out_start:.3f}:d={fade_out}[music];"
            f"[3:a]volume={getattr(self.cfg, 'narration_volume', 1.0)}[narr];"
            f"[narr][music]amix=inputs=2:duration=first:dropout_transition=3,"
            f"volume={getattr(self.cfg, 'narration_mix_gain', 1.0)}[aout]"
        )

        video_codec_args = self._video_codec_args()

        cmd = [
            "ffmpeg", "-y",
            "-i", background_path,
            "-loop", "1", "-t", f"{duration_sec:.3f}", "-i", image_path,
            "-i", mask_path,
            "-i", narration_path,
            "-stream_loop", "-1", "-i", music_path,
            "-filter_complex", filter_complex,
            "-map", "[vout]", "-map", "[aout]",
            "-t", f"{duration_sec:.3f}",
            "-r", str(self.cfg.fps),
            *video_codec_args,
            "-c:a", self.cfg.audio_codec, "-b:a", self.cfg.audio_bitrate,
            "-pix_fmt", "yuv420p",
            "-movflags", "+faststart",
            out_path,
        ]

        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        if result.returncode != 0:
            # Retry once with a software encoder if hardware encoding failed.
            if self.cfg.use_hardware_acceleration:
                log.warning("Hardware-accelerated encode failed, retrying with "
                            "software encoder (libx264)...")
                cmd_sw = list(cmd)
                idx = cmd_sw.index("-c:v")
                cmd_sw[idx + 1] = "libx264"
                result = subprocess.run(cmd_sw, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)

            if result.returncode != 0:
                raise RenderError(
                    "ffmpeg rendering failed:\n"
                    f"{result.stdout.decode(errors='ignore')[-3000:]}"
                )

        log.info(f"Done. Output saved to: {out_path}")
        return out_path

    def _video_codec_args(self):
        if self.cfg.use_hardware_acceleration:
            # Try NVENC first; renderer.render() will transparently fall
            # back to libx264 if this fails for the current machine.
            return ["-c:v", "h264_nvenc", "-preset", "p5", "-b:v", self.cfg.video_bitrate]
        return ["-c:v", self.cfg.video_codec, "-b:v", self.cfg.video_bitrate, "-preset", "medium"]
