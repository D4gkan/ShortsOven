import io
import unittest
from unittest.mock import Mock, patch

from src.config import AppConfig
from src.ffmpeg_runner import run_ffmpeg


class EncodingWatchdogTests(unittest.TestCase):
    def test_stalled_process_is_killed_and_reported(self):
        process = Mock(stdout=io.StringIO(""), returncode=-9)
        process.poll.return_value = None
        cfg = AppConfig(render_stall_timeout_sec=0.01)
        with patch("src.ffmpeg_runner.subprocess.Popen", return_value=process):
            result = run_ffmpeg(["ffmpeg", "-y"], cfg, 1)
        process.kill.assert_called_once()
        process.wait.assert_called_once()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(b"stalled", result.stdout)

    def test_total_deadline_is_enforced(self):
        process = Mock(stdout=io.StringIO(""), returncode=-9)
        process.poll.return_value = None
        cfg = AppConfig(render_stall_timeout_sec=100, render_timeout_sec=0.01)
        with patch("src.ffmpeg_runner.subprocess.Popen", return_value=process):
            result = run_ffmpeg(["ffmpeg", "-y"], cfg, 1)
        process.kill.assert_called_once()
        self.assertIn(b"render limit", result.stdout)

    def test_completed_process_is_not_killed(self):
        process = Mock(stdout=io.StringIO("out_time_us=1000000\nprogress=end\n"), returncode=0)
        process.poll.return_value = 0
        with patch("src.ffmpeg_runner.subprocess.Popen", return_value=process):
            result = run_ffmpeg(["ffmpeg", "-y"], AppConfig(), 1)
        process.kill.assert_not_called()
        self.assertEqual(result.returncode, 0)


if __name__ == "__main__":
    unittest.main()
