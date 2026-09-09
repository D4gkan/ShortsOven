"""Check the configured Ollama service; optionally pull a missing model."""
import argparse
import json
import os
import subprocess
import sys
from urllib.request import urlopen

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src.config import load_config


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pull", action="store_true")
    args = parser.parse_args()
    cfg = load_config()
    try:
        with urlopen(cfg.ollama_url.rstrip("/") + "/api/tags", timeout=10) as response:
            models = json.load(response)["models"]
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
