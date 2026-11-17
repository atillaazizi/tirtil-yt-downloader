#!/bin/bash
# Tırtıl YT Downloader — terminalden kurulum (macOS, Apple Silicon)
#
#   curl -fsSL https://raw.githubusercontent.com/atillaazizi/tirtil-yt-downloader/main/install.sh | bash
#
# Belirli bir sürüm:  ... | bash -s -- 1.2.0
# Son sürümü GitHub'dan indirir, SHA-256 ve kod imzasını doğrular, /Applications'a kurar.
set -euo pipefail

REPO="atillaazizi/tirtil-yt-downloader"
APP_NAME="Tırtıl.app"
VERSION="${1:-}"

say()  { printf '\033[1;32m==>\033[0m %s\n' "$*"; }
die()  { printf '\033[1;31mHata:\033[0m %s\n' "$*" >&2; exit 1; }

[ "$(uname -s)" = "Darwin" ] || die "Tırtıl yalnızca macOS'ta çalışır."
ARCH="$(uname -m)"
[ "$ARCH" = "arm64" ] || die "Şu an yalnızca Apple Silicon (arm64) destekleniyor; bu Mac: $ARCH"
OS_MAJOR="$(sw_vers -productVersion | cut -d. -f1)"
[ "$OS_MAJOR" -ge 12 ] || die "macOS 12 veya üzeri gerekli."

if [ -z "$VERSION" ]; then
  say "Son sürüm denetleniyor…"
  VERSION="$(curl -fsSL "https://api.github.com/repos/$REPO/releases/latest" \
    | grep -m1 '"tag_name"' | sed -E 's/.*"v?([0-9]+\.[0-9]+\.[0-9]+)".*/\1/')"
fi
[[ "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || die "Sürüm okunamadı: '$VERSION'"

DMG_NAME="Tirtil-$VERSION-$ARCH.dmg"
BASE="https://github.com/$REPO/releases/download/v$VERSION"
TMP="$(mktemp -d)"
MNT="$TMP/mnt"
cleanup() {
  hdiutil detach "$MNT" -quiet 2>/dev/null || true
  rm -rf "$TMP"
}
trap cleanup EXIT

say "Tırtıl v$VERSION indiriliyor…"
curl -fL --progress-bar -o "$TMP/$DMG_NAME" "$BASE/$DMG_NAME"
curl -fsSL -o "$TMP/$DMG_NAME.sig" "$BASE/$DMG_NAME.sig"

say "Bütünlük doğrulanıyor…"
EXPECTED="$(plutil -extract sha256 raw -o - "$TMP/$DMG_NAME.sig")"
MANIFEST_VERSION="$(plutil -extract version raw -o - "$TMP/$DMG_NAME.sig")"
ACTUAL="$(shasum -a 256 "$TMP/$DMG_NAME" | awk '{print $1}')"
[ "$MANIFEST_VERSION" = "$VERSION" ] || die "Manifest sürümü uyuşmuyor ($MANIFEST_VERSION ≠ $VERSION)."
[ "$EXPECTED" = "$ACTUAL" ] || die "SHA-256 uyuşmuyor; dosya bozuk ya da değiştirilmiş. Kurulum iptal."

mkdir -p "$MNT"
hdiutil attach -nobrowse -noautoopen -quiet -mountpoint "$MNT" "$TMP/$DMG_NAME"
SRC="$MNT/$APP_NAME"
[ -d "$SRC" ] || die "DMG içinde $APP_NAME bulunamadı."
codesign --verify --deep --strict "$SRC" || die "Uygulamanın kod imzası geçersiz. Kurulum iptal."

DEST_DIR="/Applications"
if [ ! -w "$DEST_DIR" ]; then
  DEST_DIR="$HOME/Applications"
  mkdir -p "$DEST_DIR"
fi
DEST="$DEST_DIR/$APP_NAME"

if pgrep -f "$APP_NAME/Contents/MacOS/" >/dev/null 2>&1; then
  say "Açık olan Tırtıl kapatılıyor…"
  osascript -e 'quit app "Tırtıl"' >/dev/null 2>&1 || true
  sleep 2
fi

say "$DEST kuruluyor…"
rm -rf "$DEST.old"
[ -d "$DEST" ] && mv "$DEST" "$DEST.old"
if ditto "$SRC" "$DEST"; then
  rm -rf "$DEST.old"
else
  rm -rf "$DEST"; [ -d "$DEST.old" ] && mv "$DEST.old" "$DEST"
  die "Kopyalama başarısız."
fi
xattr -dr com.apple.quarantine "$DEST" 2>/dev/null || true

say "Tırtıl v$VERSION kuruldu: $DEST"
open "$DEST"
