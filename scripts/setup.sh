#!/usr/bin/env bash
# Tırtıl — macOS kurulum
set -euo pipefail
cd "$(dirname "$0")/.."

if ! command -v brew >/dev/null 2>&1; then
  echo "Homebrew gerekli: https://brew.sh" >&2
  exit 1
fi

echo "==> Homebrew bağımlılığı (python)"
for pkg in python@3.12; do
  brew list --formula "$pkg" >/dev/null 2>&1 || brew install "$pkg"
done

PY="$(brew --prefix python@3.12)/bin/python3.12"
echo "==> Python sanal ortamı (.venv)"
[ -d .venv ] || "$PY" -m venv .venv
.venv/bin/pip install --upgrade pip >/dev/null
.venv/bin/pip install -U -r requirements.txt

echo "==> Electron bağımlılıkları"
npm install

echo
echo "Kurulum tamam. Çalıştır:  npm start"
echo "Uygulama (.app/.dmg) üret: npm run build"
