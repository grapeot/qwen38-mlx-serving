#!/usr/bin/env python3
import sys
from pathlib import Path

if sys.version_info < (3, 12):
    raise SystemExit("Python 3.12 or newer is required; use python3.12 or a Python 3.12+ virtual environment")

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from qwen38_serving.cli import main

if __name__ == "__main__":
    main()
