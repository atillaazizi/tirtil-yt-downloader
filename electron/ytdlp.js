// yt-dlp'yi uygulamayı yeniden build etmeden günceller.
// YouTube sık değiştiği için paketteki yt-dlp birkaç haftada eskiyebilir. Resmi yt-dlp sürümünün
// platformdan bağımsız zipapp'i (`yt-dlp` asset'i) indirilir, aynı sürümün SHA2-256SUMS dosyasıyla
// doğrulanır ve <userData>/yt-dlp/yt-dlp-<sürüm>.zip olarak saklanır. Engine açılışta bu dosya
// paketteki sürümden yeniyse onu yükler (engine/ati_engine.py: _load_ytdlp).
// Dosya adı sürüm içerdiği için çalışan bir engine'in okuduğu zip hiçbir zaman üzerine yazılmaz.
const { net } = require('electron');
const path = require('path');
const fs = require('fs');
const crypto = require('crypto');
const { spawn } = require('child_process');

const API_LATEST = 'https://api.github.com/repos/yt-dlp/yt-dlp/releases/latest';
const HOUR = 60 * 60 * 1000;
const DAY = 24 * HOUR;

function vtuple(v) {
  return (String(v || '').match(/\d+/g) || []).map(Number);
}

function isNewer(a, b) {
  const x = vtuple(a);
  const y = vtuple(b);
  for (let i = 0; i < Math.max(x.length, y.length); i++) {
    if ((x[i] || 0) !== (y[i] || 0)) return (x[i] || 0) > (y[i] || 0);
  }
  return false;
}

async function fetchBuffer(url) {
  const res = await net.fetch(url, { headers: { 'User-Agent': 'Tirtil-Updater' } });
  if (!res.ok) throw new Error(`GitHub yanıtı: ${res.status}`);
  return Buffer.from(await res.arrayBuffer());
}

function createYtdlpUpdater({ dir, getEngineCommand, buildEngineEnv, isBusy, notify, loadSettings, saveSettings }) {
  let running = null;

  // Engine'in gerçekte yüklediği yt-dlp sürümü: { version, bundled, source }
  function getInfo() {
    return new Promise((resolve) => {
      const { cmd, args } = getEngineCommand(['--ytdlp-info']);
      let out = '';
      let proc;
      try {
        proc = spawn(cmd, args, { env: buildEngineEnv(), stdio: ['ignore', 'pipe', 'ignore'] });
      } catch (err) {
        return resolve({ error: err.message });
      }
      const timer = setTimeout(() => proc.kill('SIGTERM'), 60000);
      proc.stdout.on('data', (c) => { out += c.toString('utf-8'); });
      proc.on('error', (err) => { clearTimeout(timer); resolve({ error: err.message }); });
      proc.on('close', () => {
        clearTimeout(timer);
        for (const line of out.split('\n')) {
          try {
            const p = JSON.parse(line);
            if (p.event === 'ytdlp_info') return resolve(p);
          } catch (_) {}
        }
        resolve({ error: 'yt-dlp sürümü okunamadı' });
      });
    });
  }

  function cleanup(keepVersion) {
    if (isBusy()) return;
    try {
      for (const f of fs.readdirSync(dir)) {
        if (/^yt-dlp-.*\.zip(\.tmp)?$/.test(f) && f !== `yt-dlp-${keepVersion}.zip`) fs.unlinkSync(path.join(dir, f));
      }
    } catch (_) {}
  }

  async function doCheck(manual) {
    notify({ state: 'checking' });
    const info = await getInfo();
    if (info.error) throw new Error(info.error);

    const res = await net.fetch(API_LATEST, {
      headers: { Accept: 'application/vnd.github+json', 'User-Agent': 'Tirtil-Updater' }
    });
    if (!res.ok) throw new Error(`GitHub yanıtı: ${res.status}`);
    const rel = await res.json();
    const latest = String(rel.tag_name || '');
    if (!/^\d{4}\.\d{1,2}\.\d{1,2}(\.\d+)?$/.test(latest)) throw new Error('Beklenmeyen sürüm etiketi');
    saveSettings({ ytdlp_last_check: Date.now() });

    if (!isNewer(latest, info.version)) {
      notify({ state: 'latest', version: info.version, source: info.source, manual });
      return;
    }
    const assets = rel.assets || [];
    const zipAsset = assets.find(a => a.name === 'yt-dlp');
    const sumAsset = assets.find(a => a.name === 'SHA2-256SUMS');
    if (!zipAsset || !sumAsset) throw new Error('Sürüm dosyaları bulunamadı');

    notify({ state: 'downloading', version: latest });
    const sums = (await fetchBuffer(sumAsset.browser_download_url)).toString('utf-8');
    const line = sums.split('\n').find(l => /\s\*?yt-dlp$/.test(l.trim()));
    const expected = line && line.trim().split(/\s+/)[0].toLowerCase();
    if (!expected || !/^[0-9a-f]{64}$/.test(expected)) throw new Error('SHA-256 listesi okunamadı');

    const data = await fetchBuffer(zipAsset.browser_download_url);
    const actual = crypto.createHash('sha256').update(data).digest('hex');
    if (actual !== expected) throw new Error('SHA-256 doğrulaması başarısız, dosya kullanılmadı');

    fs.mkdirSync(dir, { recursive: true });
    const target = path.join(dir, `yt-dlp-${latest}.zip`);
    fs.writeFileSync(`${target}.tmp`, data);
    fs.renameSync(`${target}.tmp`, target);
    const currentFile = path.join(dir, 'current.txt');
    const previous = fs.existsSync(currentFile) ? fs.readFileSync(currentFile, 'utf-8').trim() : '';
    fs.writeFileSync(currentFile, latest);

    // Gerçekten yüklenebildiğini doğrula; olmazsa önceki duruma dön
    const after = await getInfo();
    if (after.error || after.version !== latest || after.source !== 'güncel') {
      if (previous) fs.writeFileSync(currentFile, previous);
      else fs.unlinkSync(currentFile);
      try { fs.unlinkSync(target); } catch (_) {}
      throw new Error('Yeni yt-dlp açılamadı, eski sürümle devam ediliyor');
    }
    cleanup(latest);
    notify({ state: 'updated', version: latest, source: 'güncel', manual });
  }

  // manual: kullanıcı butona bastı. urgent: bir indirme başarısız oldu; YouTube değişmiş olabilir,
  // günlük sınırı beklemeden (en fazla saatte bir) denetle.
  function check(manual = false, urgent = false) {
    if (running) return running;
    if (!manual) {
      const s = loadSettings();
      if (s.ytdlp_auto_update === false) return Promise.resolve();
      const wait = urgent ? HOUR : DAY;
      if (Date.now() - (s.ytdlp_last_check || 0) < wait) return Promise.resolve();
    }
    running = doCheck(manual)
      .catch((err) => notify({ state: 'error', error: err.message, manual }))
      .finally(() => { running = null; });
    return running;
  }

  return { check, getInfo };
}

module.exports = { createYtdlpUpdater };
