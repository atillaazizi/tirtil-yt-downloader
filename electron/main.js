const { app, BrowserWindow, ipcMain, dialog, shell, Menu } = require('electron');
const path = require('path');
const fs = require('fs');
const { spawn } = require('child_process');
const { checkForUpdates } = require('./updater');

const APP_NAME = 'Tırtıl YT Downloader';
app.setName('Tırtıl');

let mainWindow = null;
let currentEngineProcess = null;

// macOS: ~/Library/Application Support/Tırtıl
const APP_DATA_DIR = app.getPath('userData');
if (!fs.existsSync(APP_DATA_DIR)) {
  fs.mkdirSync(APP_DATA_DIR, { recursive: true });
}
const SETTINGS_FILE = path.join(APP_DATA_DIR, 'settings.json');

// Eski adla (ATi__ Slicer Studio) kaydedilmiş ayarları bir kereliğine taşı.
const LEGACY_SETTINGS = path.join(app.getPath('appData'), 'ATi__ Slicer Studio', 'settings.json');
if (!fs.existsSync(SETTINGS_FILE) && fs.existsSync(LEGACY_SETTINGS)) {
  try { fs.copyFileSync(LEGACY_SETTINGS, SETTINGS_FILE); } catch (_) { /* yoksay */ }
}
const LOG_DIR = path.join(app.getPath('home'), 'Library', 'Logs', 'Tırtıl');
fs.mkdirSync(LOG_DIR, { recursive: true });

const PROJECT_ROOT = path.resolve(__dirname, '..');

// Finder'dan açılan .app minimal PATH ile başlar; Homebrew yollarını ekle.
function buildEngineEnv() {
  const extra = ['/opt/homebrew/bin', '/opt/homebrew/sbin', '/usr/local/bin', '/usr/bin', '/bin', '/usr/sbin', '/sbin'];
  const current = (process.env.PATH || '').split(':').filter(Boolean);
  const merged = [...new Set([...current, ...extra])];
  const env = { ...process.env, PATH: merged.join(':'), PYTHONUNBUFFERED: '1', PYTHONIOENCODING: 'utf-8', ATI_LOG_DIR: LOG_DIR };
  const res = app.isPackaged ? process.resourcesPath : PROJECT_ROOT;
  env.ATI_ELECTRON_EXEC = process.execPath;
  env.ATI_NODE_BIN = path.join(res, 'bin', 'node');
  env.ATI_FFMPEG_DIR = app.isPackaged
    ? path.join(res, 'ffmpeg')
    : path.dirname(require('ffmpeg-static'));
  return env;
}

function loadSettings() {
  if (fs.existsSync(SETTINGS_FILE)) {
    try {
      return JSON.parse(fs.readFileSync(SETTINGS_FILE, 'utf-8'));
    } catch (_) {}
  }
  return {};
}

function saveSettings(data) {
  try {
    const current = loadSettings();
    Object.assign(current, data);
    fs.writeFileSync(SETTINGS_FILE, JSON.stringify(current, null, 2), 'utf-8');
    return true;
  } catch (err) {
    console.error('Failed to save settings:', err);
    return false;
  }
}

// Engine komutunu çöz: paketli .app içinde PyInstaller binary'si, geliştirmede .venv/python3.
function getEngineCommand(extraArgs) {
  if (app.isPackaged) {
    const bin = path.join(process.resourcesPath, 'engine', 'ati-engine');
    if (fs.existsSync(bin)) return { cmd: bin, args: extraArgs };
  }

  const script = path.join(PROJECT_ROOT, 'engine', 'ati_engine.py');
  const candidates = [
    path.join(PROJECT_ROOT, '.venv', 'bin', 'python3'),
    '/opt/homebrew/bin/python3',
    '/usr/local/bin/python3',
    '/usr/bin/python3'
  ];
  const py = candidates.find(p => fs.existsSync(p)) || 'python3';
  return { cmd: py, args: [script, ...extraArgs] };
}

function createMainWindow() {
  mainWindow = new BrowserWindow({
    title: APP_NAME,
    width: 920,
    height: 820,
    minWidth: 760,
    minHeight: 640,
    center: true,
    titleBarStyle: 'hiddenInset',
    trafficLightPosition: { x: 18, y: 17 },
    vibrancy: 'under-window',
    visualEffectState: 'active',
    backgroundColor: '#0c0c0c',
    show: false,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      nodeIntegration: false,
      contextIsolation: true,
      sandbox: false
    }
  });

  mainWindow.loadFile(path.join(PROJECT_ROOT, 'ui', 'index.html'));

  mainWindow.once('ready-to-show', () => {
    mainWindow.show();
    mainWindow.focus();
  });

  mainWindow.on('closed', () => {
    mainWindow = null;
  });
}

// Standart macOS menüsü: Cmd+C/V/X/A, Cmd+R, Cmd+Q bunsuz textarea'da çalışmaz.
function buildMenu() {
  const template = [
    {
      label: app.name,
      submenu: [
        { role: 'about', label: 'Tırtıl Hakkında' },
        { label: 'Güncellemeleri Denetle…', click: () => runUpdateCheck(true) },
        { type: 'separator' },
        { role: 'services' },
        { type: 'separator' },
        { role: 'hide' },
        { role: 'hideOthers' },
        { role: 'unhide' },
        { type: 'separator' },
        { role: 'quit' }
      ]
    },
    { role: 'editMenu' },
    {
      label: 'Görünüm',
      submenu: [
        { role: 'reload', label: 'Yeniden Yükle' },
        { role: 'toggleDevTools', label: 'Geliştirici Araçları' },
        { type: 'separator' },
        { role: 'resetZoom' },
        { role: 'zoomIn' },
        { role: 'zoomOut' },
        { type: 'separator' },
        { role: 'togglefullscreen' }
      ]
    },
    { role: 'windowMenu' }
  ];
  Menu.setApplicationMenu(Menu.buildFromTemplate(template));
}

ipcMain.handle('get-initial-state', () => {
  const settings = loadSettings();
  const defaultDownloadFolder = path.join(app.getPath('downloads'), 'Tırtıl_Downloads');
  if (!settings.download_folder) {
    settings.download_folder = defaultDownloadFolder;
  }
  return {
    settings,
    defaultDownloadFolder,
    version: app.getVersion()
  };
});

ipcMain.handle('save-settings', (_e, settings) => {
  return saveSettings(settings);
});

ipcMain.handle('pick-folder', async (_e, defaultPath) => {
  const result = await dialog.showOpenDialog(mainWindow, {
    title: 'İndirme Klasörünü Seç',
    defaultPath: defaultPath || app.getPath('downloads'),
    properties: ['openDirectory', 'createDirectory']
  });
  if (!result.canceled && result.filePaths.length > 0) {
    const selected = result.filePaths[0];
    saveSettings({ download_folder: selected });
    return selected;
  }
  return null;
});

ipcMain.handle('pick-txt-file', async () => {
  const result = await dialog.showOpenDialog(mainWindow, {
    title: 'YouTube Link Listesi Seç',
    filters: [{ name: 'Metin dosyaları', extensions: ['txt'] }, { name: 'Tüm dosyalar', extensions: ['*'] }],
    properties: ['openFile']
  });
  if (!result.canceled && result.filePaths.length > 0) {
    try {
      const content = fs.readFileSync(result.filePaths[0], 'utf-8');
      const urls = content
        .split(/\r?\n/)
        .map(l => l.trim())
        .filter(l => l && !l.startsWith('#') && (l.includes('http') || l.includes('youtu')));
      return { success: true, urls, count: urls.length, filename: path.basename(result.filePaths[0]) };
    } catch (err) {
      return { success: false, error: err.message };
    }
  }
  return { canceled: true };
});

ipcMain.handle('open-folder', (_e, targetPath) => {
  if (!targetPath) return false;
  fs.mkdirSync(targetPath, { recursive: true });
  shell.openPath(targetPath);
  return true;
});

ipcMain.handle('open-logs', () => {
  shell.openPath(LOG_DIR);
  return true;
});

ipcMain.handle('start-download', async (_e, config) => {
  if (currentEngineProcess) {
    return { error: 'İndirme zaten çalışıyor.' };
  }

  const tempConfigFile = path.join(APP_DATA_DIR, `job_${Date.now()}.json`);
  try {
    fs.writeFileSync(tempConfigFile, JSON.stringify(config), 'utf-8');
  } catch (err) {
    return { error: `Kuyruk hazırlanamadı: ${err.message}` };
  }

  const { cmd, args } = getEngineCommand([tempConfigFile]);
  const proc = spawn(cmd, args, {
    cwd: APP_DATA_DIR,
    env: buildEngineEnv(),
    stdio: ['ignore', 'pipe', 'pipe']
  });
  currentEngineProcess = proc;

  const send = (payload) => {
    if (mainWindow && !mainWindow.isDestroyed()) {
      mainWindow.webContents.send('engine-event', payload);
    }
  };

  let lineBuffer = '';

  proc.stdout.on('data', (chunk) => {
    lineBuffer += chunk.toString('utf-8');
    const lines = lineBuffer.split('\n');
    lineBuffer = lines.pop();

    for (const line of lines) {
      const trimmed = line.trim();
      if (!trimmed) continue;
      try {
        send(JSON.parse(trimmed));
      } catch (_) {
        send({ event: 'log', level: 'info', message: trimmed, timestamp: new Date().toLocaleTimeString('tr-TR') });
      }
    }
  });

  proc.stderr.on('data', (chunk) => {
    const errText = chunk.toString('utf-8').trim();
    if (errText) {
      send({ event: 'log', level: 'warn', message: errText, timestamp: new Date().toLocaleTimeString('tr-TR') });
    }
  });

  proc.on('error', (err) => {
    send({ event: 'log', level: 'error', message: `Engine başlatılamadı (${cmd}): ${err.message}`, timestamp: new Date().toLocaleTimeString('tr-TR') });
  });

  proc.on('close', (code) => {
    if (currentEngineProcess === proc) currentEngineProcess = null;
    try {
      if (fs.existsSync(tempConfigFile)) fs.unlinkSync(tempConfigFile);
    } catch (_) {}
    send({ event: 'engine_stopped', exitCode: code });
  });

  return { success: true };
});

ipcMain.handle('cancel-download', () => {
  if (currentEngineProcess) {
    try {
      currentEngineProcess.kill('SIGTERM');
      currentEngineProcess = null;
      return { success: true };
    } catch (e) {
      return { success: false, error: e.message };
    }
  }
  return { success: false };
});

function runUpdateCheck(manual) {
  return checkForUpdates({
    getWindow: () => mainWindow,
    notify: (status) => {
      if (mainWindow && !mainWindow.isDestroyed()) mainWindow.webContents.send('update-status', status);
    },
    loadSettings,
    saveSettings,
    manual
  });
}

ipcMain.handle('check-updates', () => runUpdateCheck(true));

app.whenReady().then(() => {
  buildMenu();
  createMainWindow();
  // Paketli sürümde açılıştan kısa süre sonra sessizce denetle.
  if (app.isPackaged) setTimeout(() => runUpdateCheck(false), 4000);

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createMainWindow();
  });
});

app.on('before-quit', () => {
  if (currentEngineProcess) {
    try { currentEngineProcess.kill('SIGTERM'); } catch (_) {}
  }
});
