#!/usr/bin/env bash
# Python engine'i PyInstaller ile tek klasörlük binary'ye derler (.app içine gömülür)
set -euo pipefail
cd "$(dirname "$0")/.."

[ -x .venv/bin/python3 ] || { echo "Önce ./scripts/setup.sh çalıştır" >&2; exit 1; }
.venv/bin/pip install -q pyinstaller

rm -rf build/engine build/pyi
.venv/bin/python3 -m PyInstaller --noconfirm --clean --onedir \
  --name ati-engine \
  --distpath build/engine \
  --workpath build/pyi \
  --specpath build/pyi \
  --collect-all yt_dlp \
  --collect-all yt_dlp_ejs \
  engine/ati_engine.py

echo "Engine hazır: build/engine/ati-engine/ati-engine"
