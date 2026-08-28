#!/usr/bin/env bash
# =========================================================================
#  Build a standalone PhotoOrganizer binary for macOS / Linux.
#  Prereq: Python 3.8+ with tkinter.
#    - macOS: use the official installer from python.org (Tk included).
#    - Linux: install tk with your package manager, e.g.
#             sudo apt install python3 python3-venv python3-tk
#
#  Result: dist/PhotoOrganizer   (single-file executable, no deps)
# =========================================================================
set -euo pipefail
cd "$(dirname "$0")"

echo
echo "=== Checking Python ==="
command -v python3 >/dev/null || { echo "ERROR: python3 not found."; exit 1; }
python3 --version
python3 -c "import tkinter" || { echo "ERROR: tkinter not available. Install python3-tk."; exit 1; }

echo
echo "=== Creating build virtual environment ==="
[ -d .buildenv ] || python3 -m venv .buildenv
# shellcheck disable=SC1091
source .buildenv/bin/activate

echo
echo "=== Installing build dependencies ==="
python -m pip install --upgrade pip
python -m pip install pyinstaller Pillow reverse_geocoder

echo
echo "=== Building single-file executable ==="
pyinstaller \
  --onefile \
  --windowed \
  --noconfirm \
  --name PhotoOrganizer \
  --collect-all reverse_geocoder \
  run.py

echo
echo "========================================================================="
echo "  BUILD OK."
echo "  Your executable is: $PWD/dist/PhotoOrganizer"
if [ -d "dist/PhotoOrganizer.app" ]; then
  echo "  On macOS you also get a bundle: $PWD/dist/PhotoOrganizer.app"
fi
echo "  Copy it anywhere. No Python needed to run it."
echo "========================================================================="
