// approvals_badge.js - lightweight global pending approvals indicator

(function () {
  const BADGE_ID = 'nav-approvals-badge';
  const LS_KEY = 'norman.approvals.pending_count.v1';
  const LS_TS_KEY = 'norman.approvals.pending_count_ts.v1';
  const POLL_MS = 20000;
  const MIN_FETCH_MS = 3000;
  const AUTH_BACKOFF_MS = 5 * 60 * 1000;

  let timer = null;
  let inFlight = false;
  let lastFetchAt = 0;
  let clickBound = false;
  let authBlockedUntil = 0;

  function readCachedCount() {
    try {
      const raw = localStorage.getItem(LS_KEY);
      const ts = Number.parseInt(localStorage.getItem(LS_TS_KEY) || '0', 10);
      const count = Number.parseInt(raw || '0', 10);
      if (!Number.isFinite(ts) || !Number.isFinite(count)) return null;
      return { count, ts };
    } catch (err) {
      return null;
    }
  }

  function writeCachedCount(count) {
    try {
      localStorage.setItem(LS_KEY, String(count));
      localStorage.setItem(LS_TS_KEY, String(Date.now()));
    } catch (err) {
      // ignore
    }
  }

  function setBadge(count) {
    const badge = document.getElementById(BADGE_ID);
    if (!badge) return;

    if (!clickBound) {
      clickBound = true;
      badge.addEventListener('click', (evt) => {
        evt.preventDefault();
        evt.stopPropagation();
        window.location.href = '/connectors.html?panel=approvals';
      });
    }

    const n = Number.isFinite(count) ? count : 0;
    badge.textContent = String(n);
    badge.classList.toggle('d-none', n <= 0);
  }

  async function fetchCount({ force = false } = {}) {
    const now = Date.now();
    if (!force && (now - lastFetchAt) < MIN_FETCH_MS) return;
    if (inFlight) return;
    if (document.hidden) return;
    if (now < authBlockedUntil) return;

    inFlight = true;
    try {
      const resp = await fetch('/api/v1/approvals/count?status=pending', { cache: 'no-store' });
      if (resp.status === 401 || resp.status === 403) {
        // Not logged in (or forbidden). Stop polling to avoid noisy logs.
        authBlockedUntil = Date.now() + AUTH_BACKOFF_MS;
        setBadge(0);
        stopPolling();
        lastFetchAt = Date.now();
        return;
      }
      if (!resp.ok) return;
      const data = await resp.json();
      const count = Number.parseInt(String(data?.count ?? '0'), 10);
      if (Number.isFinite(count)) {
        writeCachedCount(count);
        setBadge(count);
      }
      lastFetchAt = Date.now();
    } catch (err) {
      // ignore
    } finally {
      inFlight = false;
    }
  }

  function startPolling() {
    if (timer) return;
    timer = setInterval(() => {
      fetchCount();
    }, POLL_MS);
  }

  function stopPolling() {
    if (!timer) return;
    clearInterval(timer);
    timer = null;
  }

  document.addEventListener('visibilitychange', () => {
    if (document.hidden) {
      stopPolling();
      return;
    }
    fetchCount({ force: true });
    startPolling();
  });

  document.addEventListener('DOMContentLoaded', () => {
    const badge = document.getElementById(BADGE_ID);
    if (!badge) return;

    const cached = readCachedCount();
    if (cached) setBadge(cached.count);

    fetchCount({ force: true });
    startPolling();
  });
})();
