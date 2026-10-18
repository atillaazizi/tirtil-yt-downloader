#!/usr/bin/env bash
# Çift tıkla çalıştır (geliştirme modu)
cd "$(dirname "$0")"
if [ ! -d node_modules ] || [ ! -d .venv ]; then
  ./scripts/setup.sh
fi
exec npx electron .
