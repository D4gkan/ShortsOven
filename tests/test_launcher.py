"""Exercise the real batch failure path without running the generation models."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(os.name == 'nt', 'Windows batch launcher')
class LauncherFailureTests(unittest.TestCase):
    def test_failed_generation_reaches_pause_and_outer_recovery(self):
        with tempfile.TemporaryDirectory(prefix='shortsoven-failure-') as directory:
            folder = Path(directory)
            (folder / 'venv').mkdir()
            (folder / 'assets/images').mkdir(parents=True)
            (folder / 'assets/images/test.png').touch()
            lines = (ROOT / 'start.bat').read_text().splitlines()
            for index, line in enumerate(lines):
                if line.startswith('set "VENV_PYTHON='):
                    lines[index] = f'set "VENV_PYTHON={ROOT / "venv/Scripts/python.exe"}"'
                elif 'scripts\\check_ollama.py' in line:
                    lines[index] = 'ver >nul'
                elif line.startswith('choice /c MF'):
                    lines[index] = 'choice /c MF /n /d M /t 0'
                elif line.startswith('start "" /b'):
                    lines[index] = 'echo [ERROR] Deliberate failure > "!LOGFILE!"\necho 7 > "!DONEFLAG!"'
                elif line.startswith('powershell -NoProfile -ExecutionPolicy Bypass -File'):
                    lines[index] = 'ver >nul'
                elif line.strip() == 'pause':
                    lines[index] = 'echo PAUSE_REACHED'
                elif line.strip() == 'cmd.exe /d /k':
                    # Substitute the interactive prompt so this check can finish unattended.
                    lines[index] = 'echo RECOVERY_PROMPT'
            batch = folder / 'start.bat'
            batch.write_text('\n'.join(lines) + '\n')
            env = dict(os.environ)
            env.pop('SHORTSOVEN_SESSION', None)
            result = subprocess.run(['cmd.exe', '/d', '/c', str(batch)],
                                    stdin=subprocess.DEVNULL, capture_output=True, env=env, timeout=30)
            output = result.stdout.decode('utf-8', errors='replace')
            self.assertEqual(result.returncode, 1, output + repr(result.stderr))
            self.assertIn('Deliberate failure', output)
            self.assertIn('PAUSE_REACHED', output)
            self.assertIn('ShortsOven exited with code 1', output)
            self.assertIn('RECOVERY_PROMPT', output)
            self.assertTrue((folder / 'assets/images/test.png').exists())


if __name__ == '__main__':
    unittest.main()
