const { app, BrowserWindow, Menu, Notification, Tray, dialog, ipcMain, protocol, safeStorage, session, shell } = require('electron');
const { autoUpdater } = require('electron-updater');
const fs = require('node:fs/promises');
const { createHash } = require('node:crypto');
const path = require('node:path');
const { ReminderService } = require('./reminder-service.cjs');
const { CalendarSubscriptionService } = require('./calendar-subscription-service.cjs');
const { CalDavService } = require('./caldav-service.cjs');
const { WebDavBackupService } = require('./webdav-backup-service.cjs');
const WanxiangCalendar = require('./calendar-exchange.js');

const APP_SCHEME = 'wanxiang';
const APP_HOST = 'workspace';
const APP_ROOT = app.getAppPath();
const APP_URL = `${APP_SCHEME}://${APP_HOST}/life-workspace.html#dashboard`;
const APP_ID = 'com.wanxiang.life-workspace';
const APP_TOAST_ACTIVATOR_CLSID = '286b4bff-afdb-52d4-9e7c-dd6f04732cb5';
const hasUserDataDir = app.commandLine.hasSwitch('user-data-dir');
const requestedUserDataDir = app.commandLine.getSwitchValue('user-data-dir').trim();
if (hasUserDataDir && (!requestedUserDataDir || !path.isAbsolute(requestedUserDataDir))) {
  throw new Error('The --user-data-dir switch requires an absolute path.');
}
const USER_DATA_PATH = hasUserDataDir
  ? path.resolve(requestedUserDataDir)
  : path.join(app.getPath('appData'), 'Wanxiang Life Workspace');
const LOCAL_CONTENT_PATH = path.join(USER_DATA_PATH, 'content');

app.setName('万象来信');
app.setPath('userData', USER_DATA_PATH);
if (process.platform === 'win32') {
  app.setAppUserModelId(APP_ID);
  app.setToastActivatorCLSID(APP_TOAST_ACTIVATOR_CLSID);
}

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
let tray = null;
let reminderService = null;
let calendarSubscriptionService = null;
let calendarSubscriptionTimer = null;
let calDavService = null;
let calDavTimer = null;
let webDavBackupService = null;
let isQuitting = false;
let closeToTrayRequested = false;
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
  ['.cjs', 'text/javascript; charset=utf-8'],
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

function isAppOrigin(value) {
  try {
    const origin = new URL(value);
    return origin.protocol === `${APP_SCHEME}:` && origin.host === APP_HOST;
  } catch {
    return false;
  }
}

function isTrustedAppEvent(event) {
  const frame = event && event.senderFrame;
  return Boolean(
    mainWindow && !mainWindow.isDestroyed()
      && event.sender === mainWindow.webContents
      && frame && frame.isMainFrame
      && isAppOrigin(frame.url)
  );
}

function sendCalendarSubscriptionResults(results) {
  if (!Array.isArray(results) || !results.length || !mainWindow || mainWindow.isDestroyed()) return;
  mainWindow.webContents.send('planner:calendar-subscriptions-updated', results);
}

function sendCalDavResults(results) {
  if (!Array.isArray(results) || !results.length || !mainWindow || mainWindow.isDestroyed()) return;
  mainWindow.webContents.send('planner:caldav-updated', results);
}

function removeTray() {
  if (!tray) return;
  tray.destroy();
  tray = null;
}

function showMainWindow() {
  closeToTrayRequested = false;
  removeTray();
  if (!mainWindow) createMainWindow();
  if (mainWindow.isMinimized()) mainWindow.restore();
  mainWindow.show();
  mainWindow.focus();
}

function ensureTray() {
  if (tray || process.platform !== 'win32') return;
  tray = new Tray(path.join(APP_ROOT, 'assets', 'wanxiang.ico'));
  tray.setToolTip('万象来信仍在后台运行，日程提醒会继续');
  tray.setContextMenu(Menu.buildFromTemplate([
    { label: '打开万象来信', click: showMainWindow },
    { type: 'separator' },
    { label: '退出万象来信', click: () => app.quit() },
  ]));
  tray.on('click', showMainWindow);
}

function handleReminderCountChanged(count) {
  if (mainWindow && !mainWindow.isDestroyed()) mainWindow.webContents.setBackgroundThrottling(count === 0);
  if (count > 0) return;
  if (!closeToTrayRequested) removeTray();
}

function notifyReminder(reminder) {
  if (!Notification.isSupported()) return false;
  const notification = new Notification({
    title: reminder.title,
    body: reminder.body || '该处理这项日程了。',
    icon: path.join(APP_ROOT, 'assets', 'wanxiang.ico'),
  });
  notification.on('click', showMainWindow);
  notification.show();
  return true;
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
      webSecurity: true,
      preload: path.join(APP_ROOT, 'desktop', 'preload.cjs')
    }
  });
  window.webContents.setBackgroundThrottling(!reminderService || reminderService.pendingCount === 0);

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
  window.on('close', (event) => {
    if (process.platform !== 'win32' || isQuitting || !reminderService || reminderService.pendingCount === 0) return;
    event.preventDefault();
    closeToTrayRequested = true;
    window.hide();
    ensureTray();
  });
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

  app.on('before-quit', () => {
    isQuitting = true;
  });

  app.whenReady().then(async () => {
    protocol.handle(APP_SCHEME, serveAppResource);
    session.defaultSession.setPermissionRequestHandler((_webContents, permission, callback, details) => {
      callback(permission === 'notifications' && details.isMainFrame && isAppOrigin(details.requestingUrl));
    });
    session.defaultSession.setPermissionCheckHandler((_webContents, permission, requestingOrigin) => {
      return permission === 'notifications' && isAppOrigin(requestingOrigin);
    });

    reminderService = new ReminderService({
      storagePath: path.join(USER_DATA_PATH, 'planner-reminders.json'),
      notify: notifyReminder,
      onFired: (reminder) => mainWindow?.webContents.send('planner:reminders-fired', [reminder]),
      onPendingChanged: handleReminderCountChanged,
      onError: (error) => console.error('日程提醒服务错误：', error),
    });
    await reminderService.load().catch((error) => console.error('恢复日程提醒失败：', error));

    if (safeStorage.isEncryptionAvailable()) {
      calendarSubscriptionService = new CalendarSubscriptionService({
        storagePath: path.join(USER_DATA_PATH, 'calendar-subscriptions.json'),
        encrypt: async (value) => safeStorage.encryptString(value).toString('base64'),
        decrypt: async (value) => safeStorage.decryptString(Buffer.from(value, 'base64')),
        parseIcs: WanxiangCalendar.parseIcs,
      });
      await calendarSubscriptionService.load().catch((error) => {
        console.error('恢复日历订阅失败：', error);
        calendarSubscriptionService = null;
      });
      calDavService = new CalDavService({
        storagePath: path.join(USER_DATA_PATH, 'caldav-accounts.json'),
        encrypt: async (value) => safeStorage.encryptString(value).toString('base64'),
        decrypt: async (value) => safeStorage.decryptString(Buffer.from(value, 'base64')),
        combineIcs: WanxiangCalendar.combineIcsResources,
        todoResourceUids: WanxiangCalendar.todoResourceUids,
        updateVtodoCompletion: WanxiangCalendar.updateVtodoCompletion,
      });
      await calDavService.load().catch((error) => {
        console.error('恢复 CalDAV 账户失败：', error);
        calDavService = null;
      });
      webDavBackupService = new WebDavBackupService({
        storagePath: path.join(USER_DATA_PATH, 'webdav-backup.json'),
        encrypt: async (value) => safeStorage.encryptString(value).toString('base64'),
        decrypt: async (value) => safeStorage.decryptString(Buffer.from(value, 'base64')),
      });
      await webDavBackupService.load().catch((error) => {
        console.error('恢复 WebDAV 备份设置失败：', error);
        webDavBackupService = null;
      });
    } else {
      console.error('Windows 用户加密服务不可用，在线日历与 WebDAV 备份不会保存明文地址或凭据。');
    }

    ipcMain.handle('planner:sync-reminders', async (event, reminders) => {
      if (!isTrustedAppEvent(event)) return { fired: [], pendingCount: 0 };
      const result = await reminderService.sync(reminders);
      if (result.fired.length) event.sender.send('planner:reminders-fired', result.fired);
      return { pendingCount: result.pendingCount };
    });

    ipcMain.handle('planner:calendar-subscriptions-list', (event) => {
      if (!isTrustedAppEvent(event)) return [];
      if (!calendarSubscriptionService) return { ok: false, error: '日历订阅加密服务暂不可用。' };
      return calendarSubscriptionService.list();
    });
    ipcMain.handle('planner:calendar-subscriptions-add', async (event, input) => {
      if (!isTrustedAppEvent(event) || !calendarSubscriptionService) {
        return { ok: false, error: '日历订阅加密服务暂不可用。' };
      }
      try {
        const subscription = await calendarSubscriptionService.add(input);
        const result = await calendarSubscriptionService.refresh(subscription.id);
        return { ok: true, subscription, result };
      } catch (error) {
        return { ok: false, error: error instanceof Error ? error.message : '无法添加日历订阅。' };
      }
    });
    ipcMain.handle('planner:calendar-subscriptions-refresh', async (event, id, options) => {
      if (!isTrustedAppEvent(event) || !calendarSubscriptionService) {
        return { kind: 'error', id: String(id || ''), error: '日历订阅服务暂不可用。' };
      }
      return calendarSubscriptionService.refresh(id, options);
    });
    ipcMain.handle('planner:calendar-subscriptions-refresh-all', async (event) => {
      if (!isTrustedAppEvent(event) || !calendarSubscriptionService) return [];
      return calendarSubscriptionService.refreshAll();
    });
    ipcMain.handle('planner:calendar-subscriptions-commit', async (event, id, token) => {
      if (!isTrustedAppEvent(event) || !calendarSubscriptionService) return false;
      return calendarSubscriptionService.commit(id, token);
    });
    ipcMain.handle('planner:calendar-subscriptions-remove', async (event, id) => {
      if (!isTrustedAppEvent(event) || !calendarSubscriptionService) return false;
      return calendarSubscriptionService.remove(id);
    });

    ipcMain.handle('planner:caldav-list', (event) => {
      if (!isTrustedAppEvent(event)) return [];
      if (!calDavService) return { ok: false, error: 'CalDAV 加密服务暂不可用。' };
      return calDavService.list();
    });
    ipcMain.handle('planner:caldav-add', async (event, input) => {
      if (!isTrustedAppEvent(event) || !calDavService) return { ok: false, error: 'CalDAV 加密服务暂不可用。' };
      try { return { ok: true, account: await calDavService.add(input) }; }
      catch (error) { return { ok: false, error: error instanceof Error ? error.message : '无法添加 CalDAV 日历。' }; }
    });
    ipcMain.handle('planner:caldav-sync', async (event, id, options) => {
      if (!isTrustedAppEvent(event) || !calDavService) {
        return { kind: 'error', id: String(id || ''), error: 'CalDAV 服务暂不可用。' };
      }
      return calDavService.sync(id, { force: Boolean(options && options.force) });
    });
    ipcMain.handle('planner:caldav-commit', async (event, id, token) => {
      if (!isTrustedAppEvent(event) || !calDavService) return false;
      return calDavService.commit(id, token);
    });
    ipcMain.handle('planner:caldav-todo-completion', async (event, id, uid, done) => {
      if (!isTrustedAppEvent(event) || !calDavService) {
        return { ok: false, error: 'CalDAV 服务暂不可用。' };
      }
      return calDavService.setTodoCompletion(String(id || ''), uid, done);
    });
    ipcMain.handle('planner:caldav-remove', async (event, id) => {
      if (!isTrustedAppEvent(event) || !calDavService) return false;
      return calDavService.remove(id);
    });

    ipcMain.handle('planner:webdav-backup-list', (event) => {
      if (!isTrustedAppEvent(event)) return null;
      return webDavBackupService ? webDavBackupService.list() : { ok: false, error: 'WebDAV 加密服务暂不可用。' };
    });
    ipcMain.handle('planner:webdav-backup-configure', async (event, input) => {
      if (!isTrustedAppEvent(event) || !webDavBackupService) return { ok: false, error: 'WebDAV 加密服务暂不可用。' };
      try { return await webDavBackupService.configure(input); }
      catch (error) { return { ok: false, error: error instanceof Error ? error.message : '无法保存 WebDAV 设置。' }; }
    });
    ipcMain.handle('planner:webdav-backup-fetch', async (event) => {
      if (!isTrustedAppEvent(event) || !webDavBackupService) return { kind: 'error', error: 'WebDAV 加密服务暂不可用。' };
      return webDavBackupService.fetchSnapshot();
    });
    ipcMain.handle('planner:webdav-backup-push', async (event, content) => {
      if (!isTrustedAppEvent(event) || !webDavBackupService) return { kind: 'error', error: 'WebDAV 加密服务暂不可用。' };
      return webDavBackupService.pushSnapshot(content);
    });
    ipcMain.handle('planner:webdav-planner-key', async (event) => {
      if (!isTrustedAppEvent(event) || !webDavBackupService) return { ok: false, error: 'WebDAV 加密服务暂不可用。' };
      return webDavBackupService.getPlannerSyncPassphrase();
    });
    ipcMain.handle('planner:webdav-planner-fetch', async (event) => {
      if (!isTrustedAppEvent(event) || !webDavBackupService) return { kind: 'error', error: 'WebDAV 加密服务暂不可用。' };
      return webDavBackupService.fetchPlannerSnapshot();
    });
    ipcMain.handle('planner:webdav-planner-push', async (event, content) => {
      if (!isTrustedAppEvent(event) || !webDavBackupService) return { kind: 'error', error: 'WebDAV 加密服务暂不可用。' };
      return webDavBackupService.pushPlannerSnapshot(content);
    });
    ipcMain.handle('planner:webdav-backup-remove', async (event) => {
      if (!isTrustedAppEvent(event) || !webDavBackupService) return false;
      return webDavBackupService.remove();
    });

    if (calendarSubscriptionService) {
      calendarSubscriptionTimer = setInterval(() => {
        void calendarSubscriptionService.refreshDue()
          .then(sendCalendarSubscriptionResults)
          .catch((error) => console.error('定时刷新日历订阅失败：', error));
      }, 15 * 60 * 1000);
      calendarSubscriptionTimer.unref();
    }
    if (calDavService) {
      calDavTimer = setInterval(() => {
        void calDavService.syncDue().then(sendCalDavResults)
          .catch((error) => console.error('定时同步 CalDAV 日历失败：', error));
      }, 15 * 60 * 1000);
      calDavTimer.unref();
    }

    app.on('web-contents-created', (_event, contents) => {
      contents.on('will-attach-webview', (event) => event.preventDefault());
    });

    createMainWindow();
    if (calDavService) {
      setTimeout(() => {
        void calDavService.syncDue(true).then(sendCalDavResults)
          .catch((error) => console.error('启动时同步 CalDAV 日历失败：', error));
      }, 1200).unref();
    }
    configureUpdates();
    app.on('activate', () => {
      if (BrowserWindow.getAllWindows().length === 0) createMainWindow();
    });
  }).catch((error) => {
    console.error('万象来信启动失败：', error);
    app.quit();
  });

  app.on('window-all-closed', () => {
    if (process.platform === 'darwin') return;
    if (reminderService?.pendingCount > 0 && !isQuitting) {
      closeToTrayRequested = true;
      ensureTray();
      return;
    }
    app.quit();
  });
}
