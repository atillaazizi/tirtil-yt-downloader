// =========================================================
// ATi__ Slicer Studio (macOS) - Client Controller
// =========================================================

document.addEventListener('DOMContentLoaded', async () => {
  const api = window.atiAPI;

  const windowFrame = document.getElementById('app-window-frame');
  const liveClock = document.getElementById('live-clock');
  const appVersion = document.getElementById('app-version');

  const btnOpenLog = document.getElementById('btn-open-log');
  const urlInput = document.getElementById('url-input');
  const urlCounter = document.getElementById('url-counter');
  const btnPasteClip = document.getElementById('btn-paste-clip');
  const btnImportTxt = document.getElementById('btn-import-txt');
  const btnClearUrls = document.getElementById('btn-clear-urls');

  const folderPathDisplay = document.getElementById('folder-path-display');
  const btnPickFolder = document.getElementById('btn-pick-folder');
  const btnOpenFolder = document.getElementById('btn-open-folder');

  const formatPillGroup = document.getElementById('format-pill-group');
  const selectBitrate = document.getElementById('select-bitrate');
  const bitrateSection = document.getElementById('bitrate-control-section');
  const selectWorkers = document.getElementById('select-workers');
  const checkSplit = document.getElementById('check-split');

  const selectCookieBrowser = document.getElementById('select-cookie-browser');
  const selectDelayMode = document.getElementById('select-delay-mode');
  const btnClearCache = document.getElementById('btn-clear-cache');

  const btnStartDownload = document.getElementById('btn-start-download');
  const btnCancelDownload = document.getElementById('btn-cancel-download');

  const progressStatus = document.getElementById('progress-status');
  const progressMetrics = document.getElementById('progress-metrics');
  const progressBarFill = document.getElementById('progress-bar-fill');

  const terminalScreen = document.getElementById('terminal-screen');
  const btnClearTerminal = document.getElementById('btn-clear-terminal');
  const footerUser = document.getElementById('footer-user');

  let currentDownloadFolder = '';
  let selectedFormat = 'mp3';
  let isDownloading = false;

  // 1. Saat
  function updateClock() {
    liveClock.textContent = new Date().toLocaleTimeString('tr-TR');
  }
  setInterval(updateClock, 1000);
  updateClock();

  // 2. Tam ekranda trafik ışıkları gizlenir; başlık boşluğunu kaldır
  api?.onWindowStateChange((state) => {
    windowFrame.classList.toggle('fullscreen', !!state.isFullScreen);
  });

  // 3. Başlangıç durumu
  if (api) {
    const state = await api.getInitialState();
    currentDownloadFolder = state.settings.download_folder || state.defaultDownloadFolder;
    folderPathDisplay.textContent = currentDownloadFolder;
    footerUser.textContent = state.currentUser || 'Guest';
    if (state.version) appVersion.textContent = `v${state.version}`;

    selectCookieBrowser.value = state.settings.browser_cookie || 'auto';
    if (state.settings.delay_mode && selectDelayMode.querySelector(`option[value="${state.settings.delay_mode}"]`)) {
      selectDelayMode.value = state.settings.delay_mode;
    }
    if (state.settings.bitrate) selectBitrate.value = state.settings.bitrate;
    if (state.settings.workers) selectWorkers.value = state.settings.workers;
    checkSplit.checked = !!state.settings.split;
    if (state.settings.format) setFormat(state.settings.format, false);
  }

  // 4. URL girişi
  function getUrls() {
    return urlInput.value
      .split('\n')
      .map(l => l.trim())
      .filter(l => l && !l.startsWith('#') && (l.includes('http') || l.includes('youtu')));
  }

  function updateUrlCounter() {
    urlCounter.textContent = `${getUrls().length} Link Hazır`;
    updateCtaText();
  }

  urlInput.addEventListener('input', updateUrlCounter);

  btnPasteClip.addEventListener('click', async () => {
    try {
      const clipText = await navigator.clipboard.readText();
      if (!clipText.trim()) {
        appendLog('Pano boş.', 'warn');
        return;
      }
      const existing = urlInput.value.trim();
      urlInput.value = existing ? existing + '\n' + clipText.trim() : clipText.trim();
      updateUrlCounter();
      appendLog('Linkler panodan yapıştırıldı.', 'success');
    } catch (err) {
      appendLog(`Pano okunamadı: ${err.message}`, 'warn');
    }
  });

  btnImportTxt.addEventListener('click', async () => {
    const res = await api?.pickTxtFile();
    if (res && res.success) {
      const existing = urlInput.value.trim();
      const newUrls = res.urls.join('\n');
      urlInput.value = existing ? existing + '\n' + newUrls : newUrls;
      updateUrlCounter();
      appendLog(`${res.filename} dosyasından ${res.count} link yüklendi.`, 'success');
    } else if (res && res.error) {
      appendLog(`Dosya içe aktarılamadı: ${res.error}`, 'error');
    }
  });

  btnClearUrls.addEventListener('click', () => {
    urlInput.value = '';
    updateUrlCounter();
    appendLog('Link kuyruğu temizlendi.', 'info');
  });

  // 5. Klasör
  btnPickFolder.addEventListener('click', async () => {
    const chosen = await api?.pickFolder(currentDownloadFolder);
    if (chosen) {
      currentDownloadFolder = chosen;
      folderPathDisplay.textContent = chosen;
      appendLog(`İndirme konumu: ${chosen}`, 'info');
    }
  });

  btnOpenFolder.addEventListener('click', () => {
    api?.openFolder(currentDownloadFolder);
  });

  btnOpenLog.addEventListener('click', () => {
    api?.openLogs();
  });

  // 6. Format seçimi
  function setFormat(fmt, persist = true) {
    selectedFormat = fmt;
    document.querySelectorAll('.format-pill-btn').forEach(btn => {
      btn.classList.toggle('active', btn.dataset.format === fmt);
    });

    // Bitrate yalnız kayıplı formatlarda anlamlı
    const lossy = fmt === 'mp3' || fmt === 'm4a';
    bitrateSection.style.opacity = lossy ? '1' : '0.4';
    selectBitrate.disabled = !lossy;
    checkSplit.disabled = fmt === 'mp4';

    if (persist) api?.saveSettings({ format: fmt });
    updateCtaText();
  }

  formatPillGroup.addEventListener('click', (e) => {
    const target = e.target.closest('.format-pill-btn');
    if (target) setFormat(target.dataset.format);
  });

  selectBitrate.addEventListener('change', () => {
    api?.saveSettings({ bitrate: selectBitrate.value });
    updateCtaText();
  });

  selectWorkers.addEventListener('change', () => {
    api?.saveSettings({ workers: selectWorkers.value });
  });

  checkSplit.addEventListener('change', () => {
    api?.saveSettings({ split: checkSplit.checked });
  });

  selectCookieBrowser.addEventListener('change', () => {
    api?.saveSettings({ browser_cookie: selectCookieBrowser.value });
    appendLog(`Tarayıcı cookie ayarı: ${selectCookieBrowser.value}`, 'info');
  });

  selectDelayMode.addEventListener('change', () => {
    api?.saveSettings({ delay_mode: selectDelayMode.value });
    appendLog(`Rastgele bekleme: ${selectDelayMode.options[selectDelayMode.selectedIndex].text}`, 'info');
  });

  btnClearCache.addEventListener('click', async () => {
    appendLog('yt-dlp önbelleği temizleniyor...', 'info');
    const ok = await api?.clearCache();
    appendLog(ok ? 'yt-dlp token önbelleği temizlendi.' : 'Önbellek temizlenemedi.', ok ? 'success' : 'warn');
  });

  btnClearTerminal.addEventListener('click', () => {
    terminalScreen.innerHTML = '';
  });

  function updateCtaText() {
    const count = getUrls().length;
    const fmt = selectedFormat.toUpperCase();
    const n = count > 0 ? count + ' ' : '';
    let label;
    if (fmt === 'MP4') label = `⚡ ${n}VİDEO İNDİR (MP4)`;
    else if (fmt === 'MP3' || fmt === 'M4A') label = `⚡ ${n}SES İNDİR (${fmt} ${selectBitrate.value}kbps)`;
    else label = `⚡ ${n}SES İNDİR (${fmt} Lossless)`;
    btnStartDownload.querySelector('span').textContent = label;
  }

  // 7. Log
  function appendLog(msg, level = 'info', timestamp = '') {
    const line = document.createElement('div');
    line.className = `terminal-line level-${level}`;
    const time = timestamp || new Date().toLocaleTimeString('tr-TR');
    line.textContent = `[${time}] ${msg}`;
    terminalScreen.appendChild(line);
    terminalScreen.scrollTop = terminalScreen.scrollHeight;
  }

  // 8. İndirmeyi başlat
  btnStartDownload.addEventListener('click', async () => {
    const urls = getUrls();
    if (urls.length === 0) {
      appendLog('En az bir geçerli YouTube linki gir!', 'warn');
      urlInput.focus();
      return;
    }

    isDownloading = true;
    btnStartDownload.disabled = true;
    btnCancelDownload.disabled = false;
    progressBarFill.style.width = '0%';
    progressStatus.textContent = 'İndirme başlatılıyor...';
    progressMetrics.textContent = `0% • 0/${urls.length} tamamlandı`;

    const config = {
      urls,
      download_folder: currentDownloadFolder,
      format: selectedFormat,
      bitrate: selectBitrate.value,
      workers: parseInt(selectWorkers.value, 10) || 3,
      split: checkSplit.checked && selectedFormat !== 'mp4',
      cookie_browser: selectCookieBrowser.value,
      delay_mode: selectDelayMode.value
    };

    appendLog(`${urls.length} linklik kuyruk başlatılıyor...`, 'info');
    const res = await api?.startDownload(config);
    if (res && res.error) {
      appendLog(`Hata: ${res.error}`, 'error');
      finishDownloadState(false);
    }
  });

  // 9. İptal
  btnCancelDownload.addEventListener('click', async () => {
    appendLog('İptal komutu gönderiliyor...', 'warn');
    btnCancelDownload.disabled = true;
    await api?.cancelDownload();
  });

  function finishDownloadState(isSuccess = true) {
    isDownloading = false;
    btnStartDownload.disabled = false;
    btnCancelDownload.disabled = true;
    if (isSuccess) {
      progressBarFill.style.width = '100%';
      progressStatus.textContent = 'Tamamlandı_!';
    } else {
      progressStatus.textContent = 'Durduruldu / Hata.';
    }
  }

  // 10. Engine olay akışı
  api?.onEngineEvent((data) => {
    if (data.event === 'log') {
      appendLog(data.message, data.level || 'info', data.timestamp);
    } else if (data.event === 'progress') {
      const overall = Math.min(1.0, Math.max(0.0, data.overall || 0.0));
      const overallPct = Math.round(overall * 100);
      progressBarFill.style.width = `${overallPct}%`;

      let detail = `${overallPct}%`;
      if (data.speed) detail += ` • Hız: ${data.speed}`;
      if (data.eta) detail += ` • Kalan: ${data.eta}`;
      progressMetrics.textContent = detail;
      progressStatus.textContent = `İndiriliyor: ${data.index}/${data.total}...`;
    } else if (data.event === 'item_done') {
      appendLog(`BAŞARILI: ${data.title}${data.size_mb ? ' (' + data.size_mb.toFixed(1) + ' MB)' : ''}`, 'success');
    } else if (data.event === 'item_failed') {
      appendLog(`BAŞARISIZ: ${data.url} -- ${data.error}`, 'error');
    } else if (data.event === 'error') {
      appendLog(`Engine hatası: ${data.error}`, 'error');
    } else if (data.event === 'finished') {
      finishDownloadState(data.failed === 0);
      progressMetrics.textContent = `100% • ${data.success}/${data.total} başarılı`;
      appendLog(`Tüm indirmeler bitti! Klasör: ${data.folder}`, 'success');
    } else if (data.event === 'engine_stopped') {
      if (isDownloading) finishDownloadState(false);
    }
  });

  updateCtaText();
});
