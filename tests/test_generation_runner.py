"""Integration checks for preserving evidence from failed generation workers."""
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


RUNNER = Path(__file__).resolve().parents[1] / 'scripts' / 'run_generation.py'


class GenerationRunnerTests(unittest.TestCase):
    def run_worker(self, command):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            result = subprocess.run(
                [sys.executable, str(RUNNER), '--log', str(folder / 'run.log'),
                 '--pid-file', str(folder / 'pid'), '--done-flag', str(folder / 'done'),
                 '--', *command], capture_output=True, text=True, timeout=20)
            self.assertEqual(result.returncode, 0, result.stderr)
            return (folder / 'run.log').read_text(encoding='utf-8'), (folder / 'done').read_text()

    def test_failure_keeps_both_output_streams_and_exit_code(self):
        log, status = self.run_worker([
            sys.executable, '-c',
            "import sys; print('worker output'); print('worker error', file=sys.stderr); sys.exit(7)"])
        self.assertIn('worker output', log)
        self.assertIn('worker error', log)
        self.assertIn('Process exited: 7 (0x00000007)', log)
        self.assertEqual(status, '7')

    def test_launch_failure_still_signals_completion(self):
        log, status = self.run_worker(['shortsoven-nonexistent-executable'])
        self.assertIn('FileNotFoundError', log)
        self.assertEqual(status, '1')


if __name__ == '__main__':
    unittest.main()
