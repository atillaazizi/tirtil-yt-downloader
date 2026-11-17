// GitHub Releases üzerinden güncelleme denetimi + kurulum.
// Uygulama Apple imzalı olmadığı için Squirrel/electron-updater kullanılamaz;
// bunun yerine DMG indirilir, uygulama kapanınca bir kabuk betiği .app'i yerine kopyalar ve yeniden açar.
const { app, dialog, shell, net } = require('electron');
const path = require('path');
const fs = require('fs');
const os = require('os');
const { spawn } = require('child_process');

const REPO = 'atillaazizi/tirtil-yt-downloader';
const API_LATEST = `https://api.github.com/repos/${REPO}/releases/latest`;

function parseVersion(v) {
  return String(v || '').replace(/^v/i, '').split(/[.-]/).slice(0, 3).map(n => parseInt(n, 10) || 0);
}

function isNewer(remote, local) {
  const a = parseVersion(remote);
  const b = parseVersion(local);
  for (let i = 0; i < 3; i++) {
    if (a[i] !== b[i]) return a[i] > b[i];
  }
  return false;
}

async function fetchLatest() {
  const res = await net.fetch(API_LATEST, {
    headers: { Accept: 'application/vnd.github+json', 'User-Agent': 'Tirtil-Updater' }
  });
  if (!res.ok) throw new Error(`GitHub yanıtı: ${res.status}`);
  const rel = await res.json();
  const arch = process.arch; // arm64 | x64
  const dmgs = (rel.assets || []).filter(a => a.name.toLowerCase().endsWith('.dmg'));
  const asset = dmgs.find(a => a.name.includes(arch)) || dmgs[0];
  return {
    version: String(rel.tag_name || '').replace(/^v/i, ''),
    notes: (rel.body || '').trim(),
    pageUrl: rel.html_url,
    asset
  };
}

async function downloadFile(url, dest, onProgress) {
  const res = await net.fetch(url, { headers: { 'User-Agent': 'Tirtil-Updater' } });
  if (!res.ok || !res.body) throw new Error(`İndirme başarısız: ${res.status}`);
  const total = Number(res.headers.get('content-length')) || 0;
  const out = fs.createWriteStream(dest);
  let received = 0;
  const reader = res.body.getReader();
  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      received += value.length;
      if (!out.write(Buffer.from(value))) await new Promise(r => out.once('drain', r));
      if (total) onProgress(received / total);
    }
  } finally {
    await new Promise(r => out.end(r));
  }
  if (total && received !== total) throw new Error('İndirme yarım kaldı.');
}

// Çalışan .app'in yolu: .../Tırtıl.app/Contents/MacOS/Tırtıl
function currentAppBundle() {
  return path.resolve(process.execPath, '..', '..', '..');
}

function canReplaceInPlace(bundle) {
  if (!bundle.endsWith('.app')) return false;
  if (bundle.includes('/AppTranslocation/') || bundle.startsWith('/Volumes/')) return false;
  try {
    fs.accessSync(path.dirname(bundle), fs.constants.W_OK);
    fs.accessSync(bundle, fs.constants.W_OK);
    return true;
  } catch (_) {
    return false;
  }
}

const INSTALL_SCRIPT = `#!/bin/bash
PID="$1"; DMG="$2"; TARGET="$3"
while kill -0 "$PID" 2>/dev/null; do sleep 0.5; done
MNT="$(mktemp -d /tmp/tirtil-update.XXXXXX)"
if ! hdiutil attach -nobrowse -noautoopen -mountpoint "$MNT" "$DMG"; then open "$DMG"; exit 1; fi
SRC="$(find "$MNT" -maxdepth 1 -name '*.app' | head -n 1)"
if [ -n "$SRC" ]; then
  rm -rf "$TARGET.old"
  if mv "$TARGET" "$TARGET.old" && ditto "$SRC" "$TARGET"; then
    rm -rf "$TARGET.old"
  else
    rm -rf "$TARGET"; mv "$TARGET.old" "$TARGET"
  fi
  xattr -dr com.apple.quarantine "$TARGET" 2>/dev/null
fi
hdiutil detach "$MNT" -quiet || hdiutil detach "$MNT" -force -quiet
rmdir "$MNT" 2>/dev/null
rm -f "$DMG"
open "$TARGET"
`;

function installAndRelaunch(dmgPath) {
  const bundle = currentAppBundle();
  if (!canReplaceInPlace(bundle)) return false;
  const script = path.join(os.tmpdir(), `tirtil-update-${Date.now()}.sh`);
  fs.writeFileSync(script, INSTALL_SCRIPT, { mode: 0o755 });
  const child = spawn('/bin/bash', [script, String(process.pid), dmgPath, bundle], {
    detached: true,
    stdio: 'ignore'
  });
  child.unref();
  app.quit();
  return true;
}

let busy = false;

/**
 * @param {object} opts
 * @param {() => Electron.BrowserWindow|null} opts.getWindow
 * @param {(s: object) => void} opts.notify  renderer'a durum gönderir
 * @param {() => object} opts.loadSettings
 * @param {(d: object) => void} opts.saveSettings
 * @param {boolean} opts.manual  menüden mi çağrıldı (sonuç yoksa da bilgi ver)
 */
async function checkForUpdates({ getWindow, notify, loadSettings, saveSettings, manual = false }) {
  if (busy) return;
  busy = true;
  const win = getWindow();
  try {
    const latest = await fetchLatest();
    const current = app.getVersion();
    const skipped = loadSettings().skipped_update_version;

    if (!isNewer(latest.version, current) || (!manual && skipped === latest.version)) {
      if (manual) {
        await dialog.showMessageBox(win, {
          type: 'info',
          message: 'Tırtıl güncel',
          detail: `Yüklü sürüm: v${current}`
        });
      }
      return;
    }

    notify({ state: 'available', version: latest.version });
    const notes = latest.notes ? `\n\nYenilikler:\n${latest.notes.slice(0, 1200)}` : '';
    const { response } = await dialog.showMessageBox(win, {
      type: 'info',
      buttons: ['Şimdi Güncelle', 'Sonra', 'Bu Sürümü Atla'],
      defaultId: 0,
      cancelId: 1,
      message: `Yeni sürüm var: Tırtıl v${latest.version}`,
      detail: `Yüklü sürüm: v${current}${notes}`
    });

    if (response === 2) {
      saveSettings({ skipped_update_version: latest.version });
      notify({ state: 'idle' });
      return;
    }
    if (response !== 0) return;

    if (!latest.asset) {
      shell.openExternal(latest.pageUrl);
      return;
    }

    const dest = path.join(app.getPath('temp'), latest.asset.name);
    notify({ state: 'downloading', version: latest.version, progress: 0 });
    await downloadFile(latest.asset.browser_download_url, dest, (p) => {
      notify({ state: 'downloading', version: latest.version, progress: p });
      const w = getWindow();
      if (w && !w.isDestroyed()) w.setProgressBar(p);
    });
    const w = getWindow();
    if (w && !w.isDestroyed()) w.setProgressBar(-1);
    notify({ state: 'ready', version: latest.version });

    const { response: r2 } = await dialog.showMessageBox(getWindow(), {
      type: 'info',
      buttons: ['Yeniden Başlat ve Kur', 'İptal'],
      defaultId: 0,
      cancelId: 1,
      message: `Tırtıl v${latest.version} indirildi`,
      detail: 'Uygulama kapanıp yeni sürümle yeniden açılacak. Devam eden indirmeler durdurulur.'
    });
    if (r2 !== 0) return;

    if (!installAndRelaunch(dest)) {
      // Yerinde değiştirilemiyorsa (ör. /Applications'a yazma izni yok) DMG'yi aç, kullanıcı sürüklesin.
      await shell.openPath(dest);
      await dialog.showMessageBox(getWindow(), {
        type: 'info',
        message: 'Kurulumu tamamla',
        detail: 'Açılan pencerede Tırtıl\'ı Applications klasörüne sürükle, ardından uygulamayı yeniden aç.'
      });
    }
  } catch (err) {
    notify({ state: 'error', message: err.message });
    if (manual) {
      dialog.showMessageBox(win, { type: 'warning', message: 'Güncelleme denetlenemedi', detail: err.message });
    }
  } finally {
    busy = false;
  }
}

module.exports = { checkForUpdates, isNewer };
