#!/bin/sh
set -eu
task_root=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
exec "${QWEN38_PYTHON:-python3.12}" "$task_root/scripts/qwen38.py" start "$@"
