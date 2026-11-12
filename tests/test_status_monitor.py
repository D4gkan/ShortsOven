"""Verify progress display failures do not terminate generation workers."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import threading
import unittest

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(os.name == 'nt', 'Windows status monitor')
class StatusMonitorTests(unittest.TestCase):
    def test_display_failure_waits_for_worker_instead_of_killing_it(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            source = (ROOT / 'scripts/batch_status.ps1').read_text()
            # Simulate the observed broken-console exception at the output seam.
            source = source.replace('Write-Output "    $stage / $clock"',
                                    '[IO.File]::WriteAllText($ElapsedFile + ".display-failed", "1"); throw "No process is on the other end of the pipe."')
            script = folder / 'monitor.ps1'
            script.write_text(source)
            worker = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])
            pid_file = folder / 'pid'
            pid_file.write_text(str(worker.pid))
            done = folder / 'done'
            def complete_after_display_failure():
                deadline = time.monotonic() + 10
                while time.monotonic() < deadline:
                    if (folder / 'elapsed.display-failed').exists():
                        break
                    time.sleep(.01)
                time.sleep(.2)
                done.write_text('0')
            timer = threading.Thread(target=complete_after_display_failure)
            timer.start()
            try:
                result = subprocess.run(
                    ['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass',
                     '-File', str(script), '-PidFile', str(pid_file), '-DoneFlag', str(done),
                     '-ElapsedFile', str(folder / 'elapsed'), '-LogFile', str(folder / 'run.log')],
                    stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=15)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIsNone(worker.poll(), 'Display failure must not kill generation')
                self.assertTrue(done.exists())
                self.assertTrue((folder / 'elapsed').exists())
                self.assertIn('No process is on the other end of the pipe', (folder / 'run.log').read_text())
            finally:
                timer.join()
                # Kill this test's launcher and its worker, never a user generation.
                if worker.poll() is None:
                    subprocess.run(['taskkill', '/PID', str(worker.pid), '/T', '/F'], capture_output=True)
                worker.wait(timeout=5)


if __name__ == '__main__':
    unittest.main()
