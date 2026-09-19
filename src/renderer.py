"""Composite feathered conversation crops as a narration-triggered vertical feed."""

import os
import shutil

from .config import AppConfig
from .ffmpeg_runner import run_ffmpeg
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

    def render(self, background_path: str, chunk_paths: list, plan,
               narration_path: str, music_path: str, duration_sec: float,
               out_path: str) -> str:
        _require_ffmpeg()
        inputs = [("background", background_path), ("narration", narration_path),
                  ("music", music_path)] + [("conversation chunk", p) for p in chunk_paths]
        if not chunk_paths or len(chunk_paths) != len(plan.chunks):
            raise RenderError("Missing conversation chunks for the animation plan.")
        for label, path in inputs:
            if not os.path.isfile(path):
                raise RenderError(f"Missing {label} input: {path}")
        log.info("Rendering conversation feed...")
        fade_in = self.cfg.music_fade_in_sec
        fade_out = self.cfg.music_fade_out_sec
        fade_out_start = max(0.0, duration_sec - fade_out)
        bg_filters = "format=yuv420p"
        if self.cfg.background_blur > 0:
            bg_filters = f"boxblur={self.cfg.background_blur}:1,{bg_filters}"
        filters = [f"[0:v]{bg_filters}[base0]"]
        offset = plan.offset_expression()
        cmd = ["ffmpeg", "-nostdin", "-y", "-filter_complex_threads", "1", "-i", background_path,
               "-i", narration_path, "-stream_loop", "-1", "-t", str(duration_sec), "-i", music_path]
        for i, (path, chunk) in enumerate(zip(chunk_paths, plan.chunks)):
            cmd += ["-loop", "1", "-framerate", str(self.cfg.fps), "-t", str(duration_sec), "-i", path]
            pixel_filter = "format=rgba"
            if i:
                # Opacity is only an introduction accent; all visible crops move
                # together using the same stack offset throughout the slide.
                pixel_filter += (f",fade=t=in:st={chunk.transition_start:.6f}:"
                                 f"d={chunk.transition_duration:.6f}:alpha=1")
            filters.append(f"[{i + 3}:v]{pixel_filter}[chunk{i}]")
            start = chunk.transition_start if i else 0
            filters.append(
                f"[base{i}][chunk{i}]overlay=x=(W-w)/2:"
                f"y='{chunk.stack_top:.6f}+({offset})':"
                f"enable='gte(t,{start:.6f})':eval=frame:"
                f"eof_action=repeat:format=auto[base{i + 1}]"
            )
        filters += [
            f"[base{len(chunk_paths)}]format=yuv420p[vout]",
            f"[2:a]volume={self.cfg.music_volume},afade=t=in:st=0:d={fade_in},"
            f"afade=t=out:st={fade_out_start:.3f}:d={fade_out}[music]",
            f"[1:a]volume={self.cfg.narration_volume},apad=whole_dur={duration_sec},atrim=duration={duration_sec}[narr]",
            f"[narr][music]amix=inputs=2:duration=first:dropout_transition=3,"
            f"volume={self.cfg.narration_mix_gain}[aout]",
        ]
        # A file avoids Windows command-length limits on longer conversations.
        script_path = self.cfg.abspath(os.path.join(self.cfg.cache_dir, "conversation_filters.txt"))
        with open(script_path, "w", encoding="utf-8") as f:
            f.write(";\n".join(filters))
        cmd += ["-filter_complex_script", script_path,
                "-map", "[vout]", "-map", "[aout]", "-t", f"{duration_sec:.3f}",
                "-r", str(self.cfg.fps), *self._video_codec_args(),
                "-c:a", self.cfg.audio_codec, "-b:a", self.cfg.audio_bitrate,
                "-pix_fmt", "yuv420p", "-movflags", "+faststart", out_path]

        result = run_ffmpeg(cmd, self.cfg, duration_sec)
        if result.returncode != 0:
            # Retry once with a software encoder if hardware encoding failed.
            if self.cfg.use_hardware_acceleration:
                log.warning("Hardware-accelerated encode failed, retrying with "
                            "software encoder (libx264)...")
                cmd_sw = list(cmd)
                idx = cmd_sw.index("-c:v")
                cmd_sw[idx + 1] = "libx264"
                cmd_sw[cmd_sw.index("-preset") + 1] = "medium"
                result = run_ffmpeg(cmd_sw, self.cfg, duration_sec)

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
