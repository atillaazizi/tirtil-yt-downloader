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
  setFormat(s.format || 'mp3', false);

  // Linkler
  urlInput.addEventListener('input', refresh);

  $('btn-paste-clip').addEventListener('click', async () => {
    try {
      const text = (await navigator.clipboard.readText()).trim();
      if (!text) return appendLog('Pano boş.', 'warn');
      urlInput.value = urlInput.value.trim() ? urlInput.value.trim() + '\n' + text : text;
      refresh();
    } catch (err) {
      appendLog(`Pano okunamadı: ${err.message}`, 'warn');
    }
  });

  $('btn-import-txt').addEventListener('click', async () => {
    const res = await api.pickTxtFile();
    if (res?.success) {
      const add = res.urls.join('\n');
      urlInput.value = urlInput.value.trim() ? urlInput.value.trim() + '\n' + add : add;
      refresh();
      appendLog(`${res.filename}: ${res.count} link eklendi.`, 'success');
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

  // İndirme
  function finish(ok) {
    isDownloading = false;
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

    const res = await api.startDownload({
      urls,
      download_folder: downloadFolder,
      format: selectedFormat,
      bitrate: selectBitrate.value,
      workers: parseInt(selectWorkers.value, 10) || 3,
      split: checkSplit.checked && selectedFormat !== 'mp4',
      cookie_browser: selectCookieBrowser.value,
      delay_mode: selectDelayMode.value
    });
    if (res?.error) {
      appendLog(res.error, 'error');
      finish(false);
    }
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
        break;
      }
      case 'error':
        appendLog(d.error, 'error');
        break;
      case 'finished':
        finish(d.failed === 0);
        progressMetrics.textContent = `${d.success}/${d.total} başarılı`;
        break;
      case 'engine_stopped':
        if (isDownloading) finish(false);
        break;
    }
  });
});
