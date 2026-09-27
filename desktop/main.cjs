const { app, BrowserWindow, Menu, dialog, protocol, session, shell } = require('electron');
const { autoUpdater } = require('electron-updater');
const fs = require('node:fs/promises');
const { createHash } = require('node:crypto');
const path = require('node:path');

const APP_SCHEME = 'wanxiang';
const APP_HOST = 'workspace';
const APP_ROOT = app.getAppPath();
const APP_URL = `${APP_SCHEME}://${APP_HOST}/life-workspace.html#dashboard`;
const APP_ID = 'com.wanxiang.life-workspace';
const USER_DATA_PATH = path.join(app.getPath('appData'), 'Wanxiang Life Workspace');
const LOCAL_CONTENT_PATH = path.join(USER_DATA_PATH, 'content');

app.setName('万象来信');
app.setPath('userData', USER_DATA_PATH);
if (process.platform === 'win32') app.setAppUserModelId(APP_ID);

protocol.registerSchemesAsPrivileged([
  {
    scheme: APP_SCHEME,
    privileges: {
      standard: true,
      secure: true,
      supportFetchAPI: true,
      stream: true
    }
  }
]);

const hasSingleInstance = app.requestSingleInstanceLock();
if (!hasSingleInstance) app.quit();

let mainWindow = null;
let updateBusy = false;
let manualUpdateCheck = false;
let updateDownloading = false;
const RELEASES_URL = 'https://github.com/linjiuyao2025/FLUKE/releases';

function showUpdateMessage(options) {
  return mainWindow ? dialog.showMessageBox(mainWindow, options) : dialog.showMessageBox(options);
}

function checkForUpdates(manual = false) {
  if (!app.isPackaged) {
    if (manual) void showUpdateMessage({ type: 'info', message: '开发模式不检查更新。' });
    return;
  }
  if (updateBusy) return;
  updateBusy = true;
  manualUpdateCheck = manual;
  autoUpdater.checkForUpdates().catch((error) => {
    const showResult = manualUpdateCheck;
    updateBusy = false;
    manualUpdateCheck = false;
    console.error('检查 GitHub 更新失败：', error);
    if (showResult) void showUpdateMessage({ type: 'warning', message: '暂时无法检查更新。', detail: '请检查网络，或在 GitHub Releases 页面查看最新版本。' });
  });
}

function configureUpdates() {
  autoUpdater.autoDownload = true;
  autoUpdater.autoInstallOnAppQuit = true;
  autoUpdater.on('update-available', () => {
    updateDownloading = true;
    manualUpdateCheck = false;
  });
  autoUpdater.on('update-not-available', () => {
    const showResult = manualUpdateCheck;
    updateBusy = false;
    manualUpdateCheck = false;
    if (showResult) void showUpdateMessage({ type: 'info', message: '当前已是最新版本。' });
  });
  autoUpdater.on('update-downloaded', (info) => {
    updateBusy = false;
    updateDownloading = false;
    void showUpdateMessage({
      type: 'info',
      buttons: ['现在重启并更新', '稍后'],
      defaultId: 0,
      cancelId: 1,
      message: `万象来信 ${info.version} 已下载完成。`,
      detail: '选择“稍后”时，退出软件后也会自动安装。'
    }).then(({ response: choice }) => {
      if (choice === 0) autoUpdater.quitAndInstall(false, true);
    });
  });
  autoUpdater.on('error', (error) => {
    const showResult = manualUpdateCheck || updateDownloading;
    updateBusy = false;
    manualUpdateCheck = false;
    updateDownloading = false;
    console.error('GitHub 更新失败：', error);
    if (showResult) void showUpdateMessage({ type: 'warning', message: '暂时无法完成更新。', detail: '请检查网络，或在 GitHub Releases 页面下载最新版本。' });
  });

  const menu = Menu.buildFromTemplate([
    { label: '软件', submenu: [{ role: 'quit', label: '退出万象来信' }] },
    { label: '帮助', submenu: [
      { label: '检查更新', click: () => checkForUpdates(true) },
      { label: '打开 GitHub 发布页', click: () => openExternalHttps(RELEASES_URL) }
    ] }
  ]);
  Menu.setApplicationMenu(menu);
  setTimeout(() => checkForUpdates(), 10000);
  setInterval(() => checkForUpdates(), 6 * 60 * 60 * 1000).unref();
}

const contentTypes = new Map([
  ['.html', 'text/html; charset=utf-8'],
  ['.css', 'text/css; charset=utf-8'],
  ['.js', 'text/javascript; charset=utf-8'],
  ['.json', 'application/json; charset=utf-8'],
  ['.svg', 'image/svg+xml'],
  ['.png', 'image/png'],
  ['.jpg', 'image/jpeg'],
  ['.jpeg', 'image/jpeg'],
  ['.webp', 'image/webp'],
  ['.gif', 'image/gif'],
  ['.ico', 'image/x-icon'],
  ['.ttf', 'font/ttf'],
  ['.otf', 'font/otf'],
  ['.woff', 'font/woff'],
  ['.woff2', 'font/woff2']
]);

const contentSecurityPolicy = [
  "default-src 'self' data: blob:",
  "script-src 'self' 'unsafe-inline'",
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' data: blob: https:",
  "font-src 'self' data:",
  "connect-src 'self' https://geocoding-api.open-meteo.com https://api.open-meteo.com",
  'frame-src https://open.spotify.com',
  "media-src 'self' data: blob: https:",
  "object-src 'none'",
  "base-uri 'self'",
  "form-action 'self'"
].join('; ');

function response(body, status, headers = {}) {
  return new Response(body, { status, headers });
}

async function readLocalPage() {
  try {
    const manifest = JSON.parse(await fs.readFile(path.join(LOCAL_CONTENT_PATH, 'manifest.json'), 'utf8'));
    if (manifest.format !== 1 || manifest.shellVersion !== app.getVersion() || !/^[a-f0-9]{64}$/.test(manifest.sha256)) {
      return null;
    }
    const pagePath = path.join(LOCAL_CONTENT_PATH, 'life-workspace.html');
    const fileInfo = await fs.stat(pagePath);
    if (!fileInfo.isFile() || fileInfo.size > 5 * 1024 * 1024) return null;
    const page = await fs.readFile(pagePath);
    return createHash('sha256').update(page).digest('hex') === manifest.sha256 ? page : null;
  } catch {
    return null;
  }
}

async function serveAppResource(request) {
  if (request.method !== 'GET' && request.method !== 'HEAD') {
    return response('Method not allowed', 405, { Allow: 'GET, HEAD' });
  }

  let targetPath;
  try {
    const requestUrl = new URL(request.url);
    if (requestUrl.host !== APP_HOST) return response('Not found', 404);

    const decodedPath = decodeURIComponent(requestUrl.pathname);
    const resourcePath = decodedPath === '/' ? '/life-workspace.html' : decodedPath;
    targetPath = path.resolve(APP_ROOT, `.${resourcePath}`);
  } catch {
    return response('Bad request', 400);
  }

  const relativePath = path.relative(APP_ROOT, targetPath);
  if (!relativePath || relativePath === '..' || relativePath.startsWith(`..${path.sep}`) || path.isAbsolute(relativePath)) {
    return response('Bad request', 400);
  }

  if (relativePath === 'life-workspace.html') {
    const localPage = await readLocalPage();
    if (localPage) {
      return response(request.method === 'HEAD' ? null : localPage, 200, {
        'Content-Type': 'text/html; charset=utf-8',
        'Cache-Control': 'no-store',
        'Content-Security-Policy': contentSecurityPolicy,
        'X-Content-Type-Options': 'nosniff'
      });
    }
  }

  try {
    const fileInfo = await fs.stat(targetPath);
    if (!fileInfo.isFile()) return response('Not found', 404);

    const headers = {
      'Content-Type': contentTypes.get(path.extname(targetPath).toLowerCase()) || 'application/octet-stream',
      'Cache-Control': 'no-store'
    };
    if (path.basename(targetPath).toLowerCase() === 'life-workspace.html') {
      headers['Content-Security-Policy'] = contentSecurityPolicy;
      headers['X-Content-Type-Options'] = 'nosniff';
    }

    const body = request.method === 'HEAD' ? null : await fs.readFile(targetPath);
    return response(body, 200, headers);
  } catch (error) {
    if (error && error.code === 'ENOENT') return response('Not found', 404);
    return response('Unable to load app resource', 500);
  }
}

function openExternalHttps(url) {
  try {
    const parsed = new URL(url);
    if (parsed.protocol === 'https:') void shell.openExternal(parsed.href);
  } catch {
    // Invalid or unsupported destinations are ignored.
  }
}

function createMainWindow() {
  const window = new BrowserWindow({
    width: 1480,
    height: 960,
    minWidth: 760,
    minHeight: 620,
    show: false,
    autoHideMenuBar: true,
    backgroundColor: '#f5f0e8',
    icon: path.join(APP_ROOT, 'assets', 'wanxiang.ico'),
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      webSecurity: true
    }
  });

  window.webContents.setWindowOpenHandler(({ url }) => {
    openExternalHttps(url);
    return { action: 'deny' };
  });

  window.webContents.on('will-navigate', (event, url) => {
    try {
      const destination = new URL(url);
      if (destination.protocol === `${APP_SCHEME}:` && destination.host === APP_HOST) return;
      event.preventDefault();
      openExternalHttps(url);
    } catch {
      event.preventDefault();
    }
  });

  window.once('ready-to-show', () => window.show());
  window.on('closed', () => {
    if (mainWindow === window) mainWindow = null;
  });

  window.loadURL(APP_URL);
  mainWindow = window;
  return window;
}

if (hasSingleInstance) {
  app.on('second-instance', () => {
    if (!mainWindow) return;
    if (mainWindow.isMinimized()) mainWindow.restore();
    mainWindow.focus();
  });

  app.whenReady().then(() => {
    protocol.handle(APP_SCHEME, serveAppResource);
    session.defaultSession.setPermissionRequestHandler((_webContents, _permission, callback) => callback(false));

    app.on('web-contents-created', (_event, contents) => {
      contents.on('will-attach-webview', (event) => event.preventDefault());
    });

    createMainWindow();
    configureUpdates();
    app.on('activate', () => {
      if (BrowserWindow.getAllWindows().length === 0) createMainWindow();
    });
  }).catch((error) => {
    console.error('万象来信启动失败：', error);
    app.quit();
  });

  app.on('window-all-closed', () => {
    if (process.platform !== 'darwin') app.quit();
  });
}
