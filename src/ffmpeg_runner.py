"""Run FFmpeg with visible progress and bounded stall/overall waits."""
import queue
import subprocess
import tempfile
import threading
import time

from .logger_setup import get_logger

log = get_logger(__name__)


def run_ffmpeg(cmd, cfg, duration_sec):
    command = [cmd[0], "-nostats", "-progress", "pipe:1", *cmd[1:]]
    events = queue.Queue()
    with tempfile.TemporaryFile() as errors:
        process = subprocess.Popen(command, stdin=subprocess.DEVNULL,
                                   stdout=subprocess.PIPE, stderr=errors,
                                   text=True, encoding="utf-8", errors="replace")
        def read_progress():
            for line in process.stdout:
                events.put(line.strip())
        reader = threading.Thread(target=read_progress, daemon=True)
        reader.start()
        started = last_advance = last_log = time.monotonic()
        media_time = 0.0
        timeout_reason = None
        try:
            while process.poll() is None:
                try:
                    line = events.get(timeout=0.2)
                except queue.Empty:
                    line = ""
                if line.startswith("out_time_us="):
                    try:
                        current = int(line.partition("=")[2]) / 1_000_000
                        if current > media_time:
                            media_time = current
                            last_advance = time.monotonic()
                    except ValueError:
                        pass
                now = time.monotonic()
                if now - last_log >= 5:
                    log.info("Encoding: %.0f%% (%.1f / %.1f seconds)",
                             min(100, media_time / max(duration_sec, 0.01) * 100),
                             media_time, duration_sec)
                    last_log = now
                if now - last_advance > cfg.render_stall_timeout_sec:
                    timeout_reason = f"FFmpeg stalled: no encoded-time progress for {cfg.render_stall_timeout_sec}s."
                    break
                if now - started > cfg.render_timeout_sec:
                    timeout_reason = f"FFmpeg exceeded the {cfg.render_timeout_sec}s render limit."
                    break
        finally:
            if process.poll() is None:
                process.kill()
            process.wait()
            reader.join(timeout=2)
            process.stdout.close()
        errors.seek(0, 2)
        errors.seek(max(0, errors.tell() - 6000))
        output = errors.read()
        if timeout_reason:
            output += ("\n" + timeout_reason).encode()
            log.error(timeout_reason)
        return subprocess.CompletedProcess(command, -1 if timeout_reason else process.returncode, output)
