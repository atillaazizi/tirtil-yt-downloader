# ⚡ ATi__ : YouTube Audio & Video Batch Slicer Studio

macOS için toplu YouTube ses/video indirici ve parça bölücü. Electron arayüzü + Python (yt-dlp, FFmpeg) motoru.

> [rtrw_/dotu-yt](https://github.com/rtrwcloud/dotu-yt) (MIT) projesinin macOS portu.

## Özellikler

- **Toplu kuyruk**: onlarca linki yapıştır veya `.txt` dosyasından içe aktar.
- **Formatlar**: MP3 (128–320 kbps), WAV, FLAC, M4A, MP4 video.
- **Auto-Split**: YouTube bölümlerine (chapter) göre, bölüm yoksa FFmpeg sessizlik algılama ile derleme/albüm videolarını ayrı parçalara böler (`01 - Başlık.mp3`, title/album/track etiketli).
- **Paralel indirme**: 1–6 eşzamanlı.
- **Tarayıcı cookie'leri**: Chrome, Brave, Edge, Vivaldi, Opera, Firefox profillerinde YouTube oturumunu otomatik bulur; Safari elle seçilebilir. Cookie okunamazsa cookie'siz moda otomatik geçer.
- **Rastgele bekleme** ve 429/403 için kademeli yeniden deneme.

## macOS'a özel değişiklikler

| Orijinal (Windows) | Bu port (macOS) |
|---|---|
| Çerçevesiz pencere + özel butonlar | Native trafik ışıkları (`hiddenInset`), tam ekran desteği, standart menü (Cmd+C/V/Q/R) |
| `C:\ProgramData\RTRW_DoTu` | `~/Library/Application Support/ATi__ Slicer Studio` |
| Proje klasörüne log | `~/Library/Logs/ATi__ Slicer Studio/ati_latest.log` |
| `%LOCALAPPDATA%` tarayıcı yolları | `~/Library/Application Support/...` + Firefox + Safari |
| `ffmpeg.exe`, `node.exe` | Homebrew (`/opt/homebrew/bin`), Finder'dan açılışta PATH düzeltmesi |
| `.bat` scriptleri, PyInstaller GUI | `scripts/setup.sh`, `start.command`, electron-builder ile `.app` + `.dmg` (engine PyInstaller ile gömülü) |
| Bölmede kayıplı/kayıpsız fark yok | WAV/FLAC/M4A için doğru encoder, kayıpsızda bitrate yok |

## Kurulum (geliştirme)

Gereken: [Homebrew](https://brew.sh)

```bash
./scripts/setup.sh      # ffmpeg, node, python@3.12, .venv, npm install
./start.command         # veya: npm start
```

## Uygulama paketi (.app / .dmg)

```bash
npm run build           # dist/ATi__ Slicer Studio-1.0.0-arm64.dmg
```

Paket Python motorunu içerir; yine de **FFmpeg** sistemde olmalı (`brew install ffmpeg`), **node** önerilir (YouTube JS imza çözümü için).
Uygulama ad-hoc imzalıdır; ilk açılışta Gatekeeper uyarırsa: sağ tık → **Aç** (veya `xattr -dr com.apple.quarantine "/Applications/ATi__ Slicer Studio.app"`).

## Notlar

- Chromium tarayıcı cookie'leri okunurken macOS **Anahtar Zinciri** izni sorar ("Chrome Safe Storage") — "İzin Ver" seç.
- Safari cookie'leri için uygulamaya **Tam Disk Erişimi** gerekir.
- İkon: `scripts/make_icon.py`.

## Lisans

MIT — bkz. [LICENSE](LICENSE). Orijinal telif: rtrw_.
