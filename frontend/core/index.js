import { initLayout } from './layout';
import { initAuth } from './auth';

document.addEventListener('DOMContentLoaded', () => {
  initLayout();
  initAuth();
});

// Lazy-load route specific views
export function loadView(name) {
  if (name === 'settings') {
    return import('../views/settings').then(m => m.initSettings());
  }
  if (name === 'audit') {
    return import('../views/audit-log').then(m => m.initAudit());
  }
}
