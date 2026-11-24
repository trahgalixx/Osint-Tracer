#!/usr/bin/env bash
# Jalankan OSINT Issue Tracer (Linux/macOS)
cd "$(dirname "$0")"
[ -d .venv ] || python3 -m venv .venv
. .venv/bin/activate
pip install -q -r requirements.txt
python app.py "$@"
