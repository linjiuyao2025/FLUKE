'use strict';

const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('wanxiangDesktop', Object.freeze({
  syncPlannerReminders: (reminders) => ipcRenderer.invoke('planner:sync-reminders', Array.isArray(reminders) ? reminders : []),
  listCalendarSubscriptions: () => ipcRenderer.invoke('planner:calendar-subscriptions-list'),
  addCalendarSubscription: (input) => ipcRenderer.invoke('planner:calendar-subscriptions-add', input && typeof input === 'object' ? input : {}),
  refreshCalendarSubscription: (id, force) => ipcRenderer.invoke('planner:calendar-subscriptions-refresh', String(id || ''), { force: Boolean(force) }),
  refreshAllCalendarSubscriptions: () => ipcRenderer.invoke('planner:calendar-subscriptions-refresh-all'),
  commitCalendarSubscription: (id, token) => ipcRenderer.invoke('planner:calendar-subscriptions-commit', String(id || ''), String(token || '')),
  removeCalendarSubscription: (id) => ipcRenderer.invoke('planner:calendar-subscriptions-remove', String(id || '')),
  listCalDavCalendars: () => ipcRenderer.invoke('planner:caldav-list'),
  addCalDavCalendar: (input) => ipcRenderer.invoke('planner:caldav-add', input && typeof input === 'object' ? input : {}),
  syncCalDavCalendar: (id, force) => ipcRenderer.invoke('planner:caldav-sync', String(id || ''), { force: Boolean(force) }),
  commitCalDavSync: (id, token) => ipcRenderer.invoke('planner:caldav-commit', String(id || ''), String(token || '')),
  setCalDavTodoCompletion: (id, uid, done) => ipcRenderer.invoke('planner:caldav-todo-completion', String(id || ''), String(uid || ''), done === true),
  removeCalDavCalendar: (id) => ipcRenderer.invoke('planner:caldav-remove', String(id || '')),
  getWebDavBackupAccount: () => ipcRenderer.invoke('planner:webdav-backup-list'),
  configureWebDavBackup: (input) => ipcRenderer.invoke('planner:webdav-backup-configure', input && typeof input === 'object' ? input : {}),
  fetchWebDavBackup: () => ipcRenderer.invoke('planner:webdav-backup-fetch'),
  pushWebDavBackup: (content) => ipcRenderer.invoke('planner:webdav-backup-push', typeof content === 'string' ? content : ''),
  getWebDavPlannerPassphrase: () => ipcRenderer.invoke('planner:webdav-planner-key'),
  fetchWebDavPlannerSnapshot: () => ipcRenderer.invoke('planner:webdav-planner-fetch'),
  pushWebDavPlannerSnapshot: (content) => ipcRenderer.invoke('planner:webdav-planner-push', typeof content === 'string' ? content : ''),
  removeWebDavBackup: () => ipcRenderer.invoke('planner:webdav-backup-remove'),
  onCalDavUpdated: (callback) => {
    if (typeof callback !== 'function') return () => {};
    const listener = (_event, results) => callback(Array.isArray(results) ? results : []);
    ipcRenderer.on('planner:caldav-updated', listener);
    return () => ipcRenderer.removeListener('planner:caldav-updated', listener);
  },
  onCalendarSubscriptionsUpdated: (callback) => {
    if (typeof callback !== 'function') return () => {};
    const listener = (_event, results) => callback(Array.isArray(results) ? results : []);
    ipcRenderer.on('planner:calendar-subscriptions-updated', listener);
    return () => ipcRenderer.removeListener('planner:calendar-subscriptions-updated', listener);
  },
  onPlannerRemindersFired: (callback) => {
    if (typeof callback !== 'function') return () => {};
    const listener = (_event, reminders) => callback(Array.isArray(reminders) ? reminders : []);
    ipcRenderer.on('planner:reminders-fired', listener);
    return () => ipcRenderer.removeListener('planner:reminders-fired', listener);
  },
}));
