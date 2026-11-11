"""Run one generation with durable output, crash status and memory samples."""
import argparse
import os
from pathlib import Path
import subprocess
import sys
import threading
import traceback

import psutil


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--log', required=True)
    parser.add_argument('--pid-file', required=True)
    parser.add_argument('--done-flag', required=True)
    parser.add_argument('command', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command
    if command[:1] == ['--']:
        command = command[1:]
    code = 1
    watched = {}

    def watch_exit(worker, log):
        try:
            # On Windows this opens a process handle before it disappears. The
            # venv redirector can turn a native worker crash into plain exit 1.
            status = worker.wait()
            if status is not None:
                log.write(f"[DIAGNOSTIC] Worker {worker.pid} exited: {status} "
                          f"(0x{status & 0xffffffff:08X})\n")
        except (psutil.Error, ValueError):
            pass

    try:
        with open(args.log, 'a', encoding='utf-8', buffering=1) as log:
            try:
                env = dict(os.environ, PYTHONUTF8='1', PYTHONUNBUFFERED='1', PYTHONFAULTHANDLER='1')
                child = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT, env=env)
                Path(args.pid_file).write_text(str(child.pid), encoding='ascii')
                process = psutil.Process(child.pid)
                while True:
                    try:
                        workers = [process, *process.children(recursive=True)]
                        for worker in workers[1:]:
                            if worker.pid not in watched:
                                watcher = threading.Thread(target=watch_exit, args=(worker, log), daemon=True)
                                watched[worker.pid] = watcher
                                watcher.start()
                        memories = []
                        for worker in workers:
                            try:
                                memories.append(worker.memory_info())
                            except psutil.Error:
                                pass
                        rss = sum(m.rss for m in memories)
                        private = sum(getattr(m, "private", m.vms) for m in memories)
                        system = psutil.virtual_memory()
                        swap = psutil.swap_memory()
                        log.write(f'[DIAGNOSTIC] pid={child.pid} rss_mb={rss / 2**20:.0f} '
                                  f'private_mb={private / 2**20:.0f} '
                                  f'system_available_mb={system.available / 2**20:.0f} '
                                  f'system_memory_percent={system.percent} swap_percent={swap.percent}\n')
                    except psutil.Error:
                        pass
                    try:
                        code = child.wait(timeout=10)
                        break
                    except subprocess.TimeoutExpired:
                        pass
            except Exception:
                traceback.print_exc(file=log)
            finally:
                for watcher in watched.values():
                    watcher.join(timeout=1)
                log.write(f'[DIAGNOSTIC] Process exited: {code} (0x{code & 0xffffffff:08X})\n')
    except Exception:
        # Even failure to open the log must release the waiting status monitor.
        traceback.print_exc()
        return 1
    finally:
        Path(args.done_flag).write_text(str(code), encoding='ascii')
    return 0


if __name__ == '__main__':
    sys.exit(main())
