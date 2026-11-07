#!/usr/bin/env bash
# TOKENFORGE one-click launcher (Linux / macOS)
set -e
cd "$(dirname "$0")"
if [ ! -d ".venv" ]; then
  echo "First run: creating virtual environment..."
  python3 -m venv .venv
  .venv/bin/python -m pip install --upgrade pip >/dev/null
  .venv/bin/python -m pip install -r requirements.txt
fi
command -v tesseract >/dev/null 2>&1 || echo "Note: Tesseract OCR not found (only needed for scanned PDFs/images). See README."
exec .venv/bin/python server.py
