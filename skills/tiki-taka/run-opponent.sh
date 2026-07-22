#!/usr/bin/env bash
# tiki-taka의 안정적인 Python 실행기로 인자를 그대로 전달한다.
set -eu

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd -P)"
exec python3 "$SCRIPT_DIR/scripts/opponent_runner.py" "$@"
