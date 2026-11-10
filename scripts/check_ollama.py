"""Check the configured Ollama service; optionally pull a missing model."""
import argparse
import json
import os
import subprocess
import sys
import shutil
import time
from urllib.parse import urlparse
from urllib.request import urlopen

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src.config import load_config


def read_models(url):
    with urlopen(url.rstrip("/") + "/api/tags", timeout=2) as response:
        return json.load(response)["models"]


def ensure_service(url, start=False):
    try:
        return read_models(url)
    except OSError:
        if not start or urlparse(url).hostname not in {"localhost", "127.0.0.1", "::1"}:
            raise
    executable = shutil.which("ollama")
    if not executable:
        candidate = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "Ollama", "ollama.exe")
        if os.path.isfile(candidate):
            executable = candidate
    if not executable:
        raise RuntimeError("Ollama is not installed or could not be found.")
    print("Starting Ollama...", flush=True)
    subprocess.Popen(
        [executable, "serve"],
        env=dict(os.environ, OLLAMA_HOST=url),
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        try:
            return read_models(url)
        except OSError:
            time.sleep(0.5)
    raise RuntimeError("Ollama did not become ready within 30 seconds.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pull", action="store_true")
    parser.add_argument("--start", action="store_true", help="Start a stopped local Ollama service")
    args = parser.parse_args()
    cfg = load_config()
    try:
        models = ensure_service(cfg.ollama_url, start=args.start)
        names = {item["name"] for item in models}
        name = cfg.ollama_model
        if name not in names and (name + ":latest") not in names:
            if not args.pull:
                raise RuntimeError(f"Model {name} is missing. Run this script with --pull.")
            env = dict(os.environ, OLLAMA_HOST=cfg.ollama_url)
            subprocess.run(["ollama", "pull", name], env=env, check=True)
        print(f"Ollama ready: {name} at {cfg.ollama_url}")
        return 0
    except Exception as exc:
        print(f"Ollama check failed: {exc}")
        print("Install/open Ollama or run 'ollama serve'. Check ollama_url and ollama_model in config.json.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
