document.addEventListener('DOMContentLoaded', async () => {
  const api = window.atiAPI;
  const $ = (id) => document.getElementById(id);

  const urlInput = $('url-input');
  const urlCounter = $('url-counter');
  const folderPathDisplay = $('folder-path-display');
  const formatGroup = $('format-pill-group');
  const selectBitrate = $('select-bitrate');
  const bitrateSection = $('bitrate-control-section');
  const selectWorkers = $('select-workers');
  const checkSplit = $('check-split');
  const selectCookieBrowser = $('select-cookie-browser');
  const selectDelayMode = $('select-delay-mode');
  const btnStart = $('btn-start-download');
  const btnCancel = $('btn-cancel-download');
  const progressStatus = $('progress-status');
  const progressMetrics = $('progress-metrics');
  const progressFill = $('progress-bar-fill');
  const logScreen = $('terminal-screen');
  const selectResolution = $('select-resolution');
  const resolutionSection = $('resolution-control-section');
  const checkEmbedMeta = $('check-embed-meta');
  const checkSkipDownloaded = $('check-skip-downloaded');
  const checkPlaylistFolders = $('check-playlist-folders');
  const checkLoudnorm = $('check-loudnorm');
  const checkSponsorblock = $('check-sponsorblock');
  const queueList = $('queue-list');
  const retryRow = $('retry-row');

  const updatePill = $('update-pill');
  updatePill.addEventListener('click', () => api.checkUpdates());
  api.onUpdateStatus((s) => {
    if (s.state === 'available') {
      updatePill.textContent = `Güncelleme var: v${s.version}`;
      updatePill.hidden = false;
    } else if (s.state === 'downloading') {
      updatePill.textContent = `İndiriliyor v${s.version} %${Math.round((s.progress || 0) * 100)}`;
      updatePill.hidden = false;
    } else if (s.state === 'ready') {
      updatePill.textContent = `v${s.version} kuruluma hazır`;
      updatePill.hidden = false;
    } else if (s.state === 'idle') {
      updatePill.hidden = true;
    }
  });

  let downloadFolder = '';
  let selectedFormat = 'mp3';
  let isDownloading = false;

  const setSelect = (el, value) => {
    if (value && el.querySelector(`option[value="${value}"]`)) el.value = value;
  };

  function appendLog(msg, level = 'info', timestamp = '') {
    const line = document.createElement('div');
    line.className = level;
    line.textContent = `[${timestamp || new Date().toLocaleTimeString('tr-TR')}] ${msg}`;
    logScreen.appendChild(line);
    logScreen.scrollTop = logScreen.scrollHeight;
  }

  function getUrls() {
    return urlInput.value
      .split('\n')
      .map(l => l.trim())
      .filter(l => l && !l.startsWith('#') && (l.includes('http') || l.includes('youtu')));
  }

  function refresh() {
    const n = getUrls().length;
    urlCounter.textContent = n;
    const fmt = selectedFormat.toUpperCase();
    const lossy = selectedFormat === 'mp3' || selectedFormat === 'm4a';
    const detail = selectedFormat === 'mp4' ? 'Video' : lossy ? `${fmt} ${selectBitrate.value} kbps` : fmt;
    btnStart.textContent = n ? `${n} link indir · ${detail}` : `İndir · ${detail}`;
  }

  function setFormat(fmt, persist = true) {
    selectedFormat = fmt;
    formatGroup.querySelectorAll('button').forEach(b => b.classList.toggle('active', b.dataset.format === fmt));
    const lossy = fmt === 'mp3' || fmt === 'm4a';
    selectBitrate.disabled = !lossy;
    bitrateSection.classList.toggle('disabled', !lossy);
    checkSplit.disabled = fmt === 'mp4';
    // Çözünürlük yalnızca video için; ses eşitleme ve SponsorBlock kesimi yalnızca ses için
    selectResolution.disabled = fmt !== 'mp4';
    resolutionSection.classList.toggle('disabled', fmt !== 'mp4');
    checkLoudnorm.disabled = fmt === 'mp4';
    checkSponsorblock.disabled = fmt === 'mp4';
    if (persist) api.saveSettings({ format: fmt });
    refresh();
  }

  // Başlangıç ayarları
  const state = await api.getInitialState();
  const s = state.settings;
  downloadFolder = s.download_folder || state.defaultDownloadFolder;
  folderPathDisplay.textContent = downloadFolder;
  $('app-version').textContent = `v${state.version}`;
  setSelect(selectCookieBrowser, s.browser_cookie);
  setSelect(selectDelayMode, s.delay_mode);
  setSelect(selectBitrate, s.bitrate);
  setSelect(selectWorkers, s.workers);
  checkSplit.checked = !!s.split;
  setSelect(selectResolution, s.resolution);
  checkEmbedMeta.checked = s.embed_meta !== false;
  checkSkipDownloaded.checked = !!s.skip_downloaded;
  checkPlaylistFolders.checked = s.playlist_folders !== false;
  checkLoudnorm.checked = !!s.loudnorm;
  checkSponsorblock.checked = !!s.sponsorblock;
  $('check-ytdlp-auto').checked = s.ytdlp_auto_update !== false;
  setFormat(s.format || 'mp3', false);

  // Genişletilen çalma listesi videoları → liste adı (alt klasör için)
  const playlistFolderOf = new Map();

  // Linkler
  urlInput.addEventListener('input', refresh);

  const checkAutoClip = $('check-auto-clip');
  const checkExpand = $('check-expand-playlist');
  checkAutoClip.checked = !!s.auto_clipboard;
  checkExpand.checked = !!s.expand_playlists;

  // Metnin içindeki tüm linkleri bulur (satır, boşluk, virgül fark etmez)
  const URL_RE = /https?:\/\/[^\s"'<>,]+/g;
  const BARE_YT_RE = /(?:^|[\s,])((?:www\.|m\.|music\.)?(?:youtube\.com|youtu\.be)\/[^\s"'<>,]+)/g;
  function extractUrls(text, youtubeOnly = false) {
    const found = (text.match(URL_RE) || []).map(u => u.replace(/[).\]]+$/, ''));
    for (const m of text.matchAll(BARE_YT_RE)) found.push('https://' + m[1]);
    const urls = [...new Set(found)];
    return youtubeOnly ? urls.filter(u => /^https?:\/\/([\w-]+\.)?(youtube\.com|youtu\.be)\//i.test(u)) : urls;
  }
  const isPlaylist = (u) => /youtu/.test(u) && /[?&]list=(?!RD)[\w-]+/.test(u);

  let expanding = false;
  async function expandInList(playlists) {
    expanding = true;
    appendLog(`${playlists.length} çalma listesi açılıyor…`, 'info');
    const res = await api.expandPlaylists(playlists);
    expanding = false;
    if (res?.error) return appendLog(`Çalma listesi açılamadı: ${res.error}`, 'warn');
    const lines = urlInput.value.split('\n');
    const existing = new Set(lines.map(l => l.trim()));
    for (const r of res.results || []) {
      if (r.error) {
        appendLog(`Çalma listesi açılamadı (${r.error}). Link olduğu gibi bırakıldı.`, 'warn');
        continue;
      }
      const idx = lines.findIndex(l => l.trim() === r.url);
      const fresh = r.entries.filter(e => !existing.has(e));
      fresh.forEach(e => existing.add(e));
      if (r.title) r.entries.forEach(e => playlistFolderOf.set(e, r.title));
      if (idx >= 0) lines.splice(idx, 1, ...fresh);
      else lines.push(...fresh);
      if (r.title) appendLog(`Çalma listesi genişletildi: ${r.title} (${r.entries.length} video)`, 'success');
    }
    urlInput.value = lines.filter(l => l.trim()).join('\n');
    refresh();
  }

  // Yeni linkleri listeye ekler, var olanları atlar. Eklenen sayısını döner.
  function addUrls(urls, source) {
    const existing = new Set(urlInput.value.split('\n').map(l => l.trim()));
    const fresh = urls.filter(u => !existing.has(u));
    if (fresh.length) {
      const cur = urlInput.value.trim();
      urlInput.value = (cur ? cur + '\n' : '') + fresh.join('\n');
      refresh();
      appendLog(`${source}: ${fresh.length} link eklendi.`, 'success');
      const playlists = fresh.filter(isPlaylist);
      if (checkExpand.checked && playlists.length) expandInList(playlists);
    }
    return fresh.length;
  }

  $('btn-paste-clip').addEventListener('click', async () => {
    try {
      const text = (await api.readClipboard()).trim();
      if (!text) return appendLog('Pano boş.', 'warn');
      const urls = extractUrls(text);
      if (!urls.length) return appendLog('Panoda link bulunamadı.', 'warn');
      if (!addUrls(urls, 'Pano')) appendLog('Panodaki linkler zaten listede.', 'info');
    } catch (err) {
      appendLog(`Pano okunamadı: ${err.message}`, 'warn');
    }
  });

  // Panodan otomatik ekle: pano değiştiğinde YouTube linklerini yakalar
  let lastClip = null;
  let clipTimer = null;
  async function pollClipboard() {
    if (!checkAutoClip.checked || expanding) return;
    try {
      const text = await api.readClipboard();
      if (text === lastClip) return;
      lastClip = text;
      const urls = extractUrls(text || '', true);
      if (urls.length) addUrls(urls, 'Panodan otomatik');
    } catch (_) {}
  }
  function setAutoClip(on) {
    clearInterval(clipTimer);
    clipTimer = null;
    if (on) {
      clipTimer = setInterval(pollClipboard, 1500);
      pollClipboard();
    }
  }
  checkAutoClip.addEventListener('change', () => {
    api.saveSettings({ auto_clipboard: checkAutoClip.checked });
    setAutoClip(checkAutoClip.checked);
  });
  window.addEventListener('focus', pollClipboard);
  setAutoClip(checkAutoClip.checked);

  checkExpand.addEventListener('change', () => {
    api.saveSettings({ expand_playlists: checkExpand.checked });
    if (checkExpand.checked) {
      const playlists = getUrls().filter(isPlaylist);
      if (playlists.length) expandInList(playlists);
    }
  });

  // Çoklu URL ekle
  const multiDialog = $('multi-url-dialog');
  const multiInput = $('multi-url-input');
  const multiCount = $('multi-url-count');
  const updateMultiCount = () => { multiCount.textContent = `${extractUrls(multiInput.value).length} link bulundu`; };
  multiInput.addEventListener('input', updateMultiCount);
  $('btn-multi-url').addEventListener('click', () => {
    multiInput.value = '';
    multiDialog.returnValue = '';
    updateMultiCount();
    multiDialog.showModal();
    multiInput.focus();
  });
  multiDialog.addEventListener('close', () => {
    if (multiDialog.returnValue !== 'add') return;
    const urls = extractUrls(multiInput.value);
    if (!urls.length) return appendLog('Eklenecek link bulunamadı.', 'warn');
    if (!addUrls(urls, 'Çoklu ekleme')) appendLog('Linklerin hepsi zaten listede.', 'info');
  });

  $('btn-import-txt').addEventListener('click', async () => {
    const res = await api.pickTxtFile();
    if (res?.success) {
      const added = addUrls(res.urls, res.filename);
      if (!added) appendLog(`${res.filename}: yeni link yok.`, 'info');
    } else if (res?.error) {
      appendLog(`Dosya okunamadı: ${res.error}`, 'error');
    }
  });

  $('btn-clear-urls').addEventListener('click', () => {
    urlInput.value = '';
    refresh();
  });

  // Klasör
  $('btn-pick-folder').addEventListener('click', async () => {
    const chosen = await api.pickFolder(downloadFolder);
    if (chosen) {
      downloadFolder = chosen;
      folderPathDisplay.textContent = chosen;
    }
  });
  $('btn-open-folder').addEventListener('click', () => api.openFolder(downloadFolder));
  $('btn-open-log').addEventListener('click', () => api.openLogs());

  // Ayarlar
  formatGroup.addEventListener('click', (e) => {
    const b = e.target.closest('button');
    if (b) setFormat(b.dataset.format);
  });
  selectBitrate.addEventListener('change', () => { api.saveSettings({ bitrate: selectBitrate.value }); refresh(); });
  selectWorkers.addEventListener('change', () => api.saveSettings({ workers: selectWorkers.value }));
  checkSplit.addEventListener('change', () => api.saveSettings({ split: checkSplit.checked }));
  selectCookieBrowser.addEventListener('change', () => api.saveSettings({ browser_cookie: selectCookieBrowser.value }));
  selectDelayMode.addEventListener('change', () => api.saveSettings({ delay_mode: selectDelayMode.value }));
  selectResolution.addEventListener('change', () => api.saveSettings({ resolution: selectResolution.value }));
  const bindCheck = (el, key) => el.addEventListener('change', () => api.saveSettings({ [key]: el.checked }));
  bindCheck(checkEmbedMeta, 'embed_meta');
  bindCheck(checkSkipDownloaded, 'skip_downloaded');
  bindCheck(checkPlaylistFolders, 'playlist_folders');
  bindCheck(checkLoudnorm, 'loudnorm');
  bindCheck(checkSponsorblock, 'sponsorblock');
  bindCheck($('check-ytdlp-auto'), 'ytdlp_auto_update');

  $('btn-clear-archive').addEventListener('click', async () => {
    if (!confirm('İndirme geçmişi silinsin mi? Daha önce indirilen videolar tekrar indirilebilir.')) return;
    const res = await api.clearArchive();
    if (res?.error) appendLog(`Geçmiş silinemedi: ${res.error}`, 'error');
    else appendLog('İndirme geçmişi temizlendi.', 'success');
  });

  // yt-dlp sürümü ve güncelleme
  const ytdlpLabel = $('ytdlp-version');
  const btnYtdlp = $('btn-ytdlp-update');
  const showYtdlp = (v, source) => { ytdlpLabel.textContent = `yt-dlp: ${v}${source === 'güncel' ? ' (güncellendi)' : ''}`; };
  api.ytdlpInfo().then((i) => { if (i && !i.error) showYtdlp(i.version, i.source); else ytdlpLabel.textContent = 'yt-dlp: ?'; });
  btnYtdlp.addEventListener('click', () => api.ytdlpUpdate());
  api.onYtdlpStatus((st) => {
    btnYtdlp.disabled = st.state === 'checking' || st.state === 'downloading';
    if (st.state === 'checking') ytdlpLabel.textContent = 'yt-dlp: denetleniyor…';
    else if (st.state === 'downloading') ytdlpLabel.textContent = `yt-dlp: ${st.version} indiriliyor…`;
    else if (st.state === 'latest') {
      showYtdlp(st.version, st.source);
      if (st.manual) appendLog(`yt-dlp güncel (${st.version}).`, 'success');
    } else if (st.state === 'updated') {
      showYtdlp(st.version, st.source);
      appendLog(`yt-dlp ${st.version} sürümüne güncellendi.`, 'success');
    } else if (st.state === 'error') {
      api.ytdlpInfo().then((i) => { if (i && !i.error) showYtdlp(i.version, i.source); });
      if (st.manual) appendLog(`yt-dlp güncellenemedi: ${st.error}`, 'warn');
    }
  });

  // Kuyruk listesi: her link için durum
  const queueRows = new Map();
  let failedUrls = [];
  const ICONS = { waiting: '·', active: '↓', done: '✓', skipped: '↷', failed: '✗' };
  function setRow(index, state, meta) {
    const row = queueRows.get(index);
    if (!row) return;
    row.el.className = `q-item ${state}`;
    row.icon.textContent = ICONS[state] || '·';
    if (meta !== undefined) row.meta.textContent = meta;
  }
  function renderQueue(items) {
    queueRows.clear();
    queueList.replaceChildren();
    for (const it of items) {
      const el = document.createElement('div');
      const icon = document.createElement('span');
      icon.className = 'q-icon';
      const title = document.createElement('span');
      title.className = 'q-title';
      title.textContent = it.url;
      if (it.folder) {
        const f = document.createElement('span');
        f.className = 'q-folder';
        f.textContent = `${it.folder} / `;
        title.prepend(f);
      }
      const meta = document.createElement('span');
      meta.className = 'q-meta';
      el.append(icon, title, meta);
      queueList.appendChild(el);
      queueRows.set(it.index, { el, icon, title, meta, url: it.url });
      setRow(it.index, 'waiting', '');
    }
    queueList.hidden = !items.length;
  }
  function setRowTitle(index, text) {
    const row = queueRows.get(index);
    if (!row) return;
    const folder = row.title.querySelector('.q-folder');
    row.title.textContent = text;
    if (folder) row.title.prepend(folder);
    row.title.title = row.url;
  }

  // İndirme
  function finish(ok) {
    isDownloading = false;
    for (const [i, row] of queueRows) {
      if (/waiting|active/.test(row.el.className)) setRow(i, 'waiting', ok ? '' : 'durduruldu');
    }
    retryRow.hidden = !failedUrls.length;
    btnStart.disabled = false;
    btnCancel.disabled = true;
    if (ok) progressFill.style.width = '100%';
    progressStatus.textContent = ok ? 'Tamamlandı' : 'Durduruldu';
  }

  btnStart.addEventListener('click', async () => {
    const urls = getUrls();
    if (!urls.length) {
      appendLog('En az bir YouTube linki gir.', 'warn');
      return urlInput.focus();
    }
    isDownloading = true;
    btnStart.disabled = true;
    btnCancel.disabled = false;
    progressFill.style.width = '0%';
    progressStatus.textContent = 'Başlatılıyor…';
    progressMetrics.textContent = `0/${urls.length}`;
    failedUrls = [];
    retryRow.hidden = true;
    renderQueue([]);

    const res = await api.startDownload({
      urls: urls.map(url => ({ url, folder: playlistFolderOf.get(url) || '' })),
      download_folder: downloadFolder,
      format: selectedFormat,
      bitrate: selectBitrate.value,
      workers: parseInt(selectWorkers.value, 10) || 3,
      split: checkSplit.checked && selectedFormat !== 'mp4',
      cookie_browser: selectCookieBrowser.value,
      delay_mode: selectDelayMode.value,
      expand_playlists: checkExpand.checked,
      playlist_folders: checkPlaylistFolders.checked,
      embed_meta: checkEmbedMeta.checked,
      resolution: selectResolution.value,
      skip_downloaded: checkSkipDownloaded.checked,
      loudnorm: checkLoudnorm.checked && selectedFormat !== 'mp4',
      sponsorblock: checkSponsorblock.checked && selectedFormat !== 'mp4'
    });
    if (res?.error) {
      appendLog(res.error, 'error');
      finish(false);
    }
  });

  $('btn-retry-failed').addEventListener('click', () => {
    if (isDownloading || !failedUrls.length) return;
    urlInput.value = failedUrls.join('\n');
    refresh();
    btnStart.click();
  });

  btnCancel.addEventListener('click', async () => {
    btnCancel.disabled = true;
    await api.cancelDownload();
  });

  api.onEngineEvent((d) => {
    switch (d.event) {
      case 'log':
        appendLog(d.message, d.level || 'info', d.timestamp);
        break;
      case 'progress': {
        const pct = Math.round(Math.min(1, Math.max(0, d.overall || 0)) * 100);
        progressFill.style.width = `${pct}%`;
        progressStatus.textContent = `İndiriliyor ${d.index}/${d.total}`;
        progressMetrics.textContent = [`${pct}%`, d.speed, d.eta && `kalan ${d.eta}`].filter(Boolean).join(' · ');
        const row = queueRows.get(d.index);
        if (row && row.el.classList.contains('active')) setRow(d.index, 'active', `%${Math.round(d.percent || 0)}`);
        break;
      }
      case 'queue':
        renderQueue(d.items || []);
        break;
      case 'item_start':
        setRowTitle(d.index, d.title);
        setRow(d.index, 'active', '');
        break;
      case 'item_done':
        setRowTitle(d.index, d.title);
        setRow(d.index, 'done', d.size_mb ? `${d.size_mb.toFixed(1)} MB` : '');
        break;
      case 'item_skipped':
        setRow(d.index, 'skipped', 'zaten var');
        break;
      case 'item_failed':
        if (d.url) failedUrls.push(d.url);
        setRow(d.index, 'failed', 'başarısız');
        if (queueRows.get(d.index)) queueRows.get(d.index).el.title = d.error || '';
        break;
      case 'error':
        appendLog(d.error, 'error');
        break;
      case 'finished':
        finish(d.failed === 0);
        progressMetrics.textContent = [`${d.success - (d.skipped || 0)}/${d.total} indirildi`,
          d.skipped && `${d.skipped} atlandı`, d.failed && `${d.failed} başarısız`].filter(Boolean).join(' · ');
        break;
      case 'engine_stopped':
        if (isDownloading) finish(false);
        break;
    }
  });
  // Sürükle-bırak: link, metin ya da .txt dosyası
  const dropOverlay = $('drop-overlay');
  let dragDepth = 0;
  window.addEventListener('dragenter', (e) => {
    e.preventDefault();
    dragDepth++;
    dropOverlay.hidden = false;
  });
  window.addEventListener('dragleave', () => {
    dragDepth = Math.max(0, dragDepth - 1);
    if (!dragDepth) dropOverlay.hidden = true;
  });
  window.addEventListener('dragover', (e) => e.preventDefault());
  window.addEventListener('drop', async (e) => {
    e.preventDefault();
    dragDepth = 0;
    dropOverlay.hidden = true;
    const dt = e.dataTransfer;
    let text = '';
    for (const file of dt.files || []) {
      if (file.size > 5 * 1024 * 1024) {
        appendLog(`${file.name} çok büyük, atlandı.`, 'warn');
        continue;
      }
      if (/\.(txt|csv|md|url|webloc)$/i.test(file.name) || file.type.startsWith('text/')) {
        text += '\n' + await file.text();
      }
    }
    text += '\n' + (dt.getData('text/uri-list') || '') + '\n' + (dt.getData('text/plain') || '');
    const lines = text.split(/\r?\n/).filter(l => !l.trim().startsWith('#')).join('\n');
    const urls = extractUrls(lines);
    if (!urls.length) return appendLog('Bırakılan içerikte link bulunamadı.', 'warn');
    if (!addUrls(urls, 'Sürükle-bırak')) appendLog('Bırakılan linkler zaten listede.', 'info');
  });
});
