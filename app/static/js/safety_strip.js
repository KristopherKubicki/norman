// Global safety strip with quick panic control.
(function () {
  const strip = document.getElementById('global-safety-strip');
  if (!strip) return;

  const chipEl = document.getElementById('safety-strip-chip');
  const textEl = document.getElementById('safety-strip-text');
  const refreshBtn = document.getElementById('safety-strip-refresh');
  const panicBtn = document.getElementById('safety-strip-panic');
  const statusBar = document.getElementById('global-status-bar');

  const POLL_MS = 30000;
  const MIN_FETCH_MS = 2500;
  const AUTH_BACKOFF_MS = 3 * 60 * 1000;
  const PANIC_CONFIRM_WINDOW_MS = 6000;
  const LEVEL_LABELS = {
    0: 'normal',
    1: 'action hold',
    2: 'command hold',
    3: 'quarantine',
    4: 'read only',
    5: 'hard kill',
  };

  let pollTimer = null;
  let inFlight = false;
  let panicInFlight = false;
  let panicConfirmArmedUntil = 0;
  let panicConfirmTimer = null;
  let lastFetchAt = 0;
  let authBlockedUntil = 0;

  function parseBool(value) {
    const text = String(value || '').trim().toLowerCase();
    return text === '1' || text === 'true' || text === 'yes' || text === 'on';
  }

  function parseIntSafe(value, fallback = 0) {
    const parsed = Number.parseInt(String(value ?? ''), 10);
    return Number.isFinite(parsed) ? parsed : fallback;
  }

  function setStatusBarText(message) {
    if (!statusBar || !message) return;
    const text = statusBar.querySelector('.status-text');
    if (!text) return;
    text.textContent = message;
  }

  function setPanicButtonState({ armed = false, busy = false } = {}) {
    if (!panicBtn) return;
    const isArmed = Boolean(armed);
    panicBtn.disabled = busy || panicBtn.classList.contains('d-none');
    panicBtn.textContent = busy ? 'Panic...' : (isArmed ? 'Confirm' : 'Panic');
    panicBtn.classList.toggle('btn-warning', isArmed && !busy);
    panicBtn.classList.toggle('btn-danger', !isArmed || busy);
    strip.dataset.panicArmed = isArmed ? '1' : '0';
  }

  function clearPanicConfirmArmed() {
    panicConfirmArmedUntil = 0;
    if (panicConfirmTimer) {
      window.clearTimeout(panicConfirmTimer);
      panicConfirmTimer = null;
    }
    setPanicButtonState({ armed: false, busy: panicInFlight });
  }

  function armPanicConfirm() {
    panicConfirmArmedUntil = Date.now() + PANIC_CONFIRM_WINDOW_MS;
    setPanicButtonState({ armed: true, busy: false });
    if (textEl) {
      textEl.textContent = 'Tap Confirm within 6s to arm hard kill.';
    }
    if (panicConfirmTimer) {
      window.clearTimeout(panicConfirmTimer);
    }
    panicConfirmTimer = window.setTimeout(() => {
      clearPanicConfirmArmed();
    }, PANIC_CONFIRM_WINDOW_MS);
  }

  function setPanicVisible(canPanic) {
    if (!panicBtn) return;
    panicBtn.classList.toggle('d-none', !canPanic);
    if (!canPanic) {
      clearPanicConfirmArmed();
    }
    setPanicButtonState({ armed: Date.now() < panicConfirmArmedUntil, busy: panicInFlight });
  }

  function summaryFromStatus(state) {
    const level = parseIntSafe(state.kill_switch_level, 0);
    if (level >= 5) return 'All outbound actions and tmux control are blocked.';
    if (state.tmux_commands_block_reason) return String(state.tmux_commands_block_reason);
    if (state.routing_actions_block_reason) return String(state.routing_actions_block_reason);
    if (state.execution_blocked_reason) return String(state.execution_blocked_reason);
    if (parseBool(state.effective_read_only) || parseBool(state.read_only)) {
      return 'Read-only mode is active.';
    }
    if (!parseBool(state.execution_enabled)) {
      return 'Execution is disabled globally.';
    }
    return 'Safety controls normal.';
  }

  function applyStatus(state = {}, options = {}) {
    const level = parseIntSafe(state.kill_switch_level, 0);
    const label = String(state.kill_switch_label || LEVEL_LABELS[level] || 'normal')
      .replace(/_/g, ' ')
      .trim();
    strip.dataset.level = String(level);
    if (chipEl) {
      chipEl.textContent = `L${level} ${label}`;
    }
    if (textEl) {
      textEl.textContent = summaryFromStatus(state);
    }
    if (!options.keepStatusBar) {
      setStatusBarText(`Safety L${level} · ${label}`);
    }
    setPanicVisible(parseBool(state.can_panic));
    if (level >= 5) {
      clearPanicConfirmArmed();
    }
  }

  async function fetchStatus(options = {}) {
    const force = Boolean(options.force);
    const now = Date.now();
    if (!force && now - lastFetchAt < MIN_FETCH_MS) return;
    if (inFlight) return;
    if (document.hidden && !force) return;
    if (now < authBlockedUntil && !force) return;

    inFlight = true;
    try {
      const resp = await fetch('/api/v1/safety/status', { cache: 'no-store' });
      if (resp.status === 401 || resp.status === 403) {
        authBlockedUntil = Date.now() + AUTH_BACKOFF_MS;
        if (refreshBtn) refreshBtn.classList.add('d-none');
        setPanicVisible(false);
        return;
      }
      const body = await resp.json().catch(() => ({}));
      if (!resp.ok) {
        throw new Error(String(body.detail || `HTTP ${resp.status}`));
      }
      applyStatus(body);
      lastFetchAt = Date.now();
    } catch (err) {
      if (textEl) {
        textEl.textContent = String(err?.message || 'Unable to read safety state.');
      }
      strip.dataset.level = 'unknown';
    } finally {
      inFlight = false;
    }
  }

  async function triggerPanic() {
    if (!panicBtn || panicInFlight || panicBtn.classList.contains('d-none')) return;
    clearPanicConfirmArmed();
    panicInFlight = true;
    setPanicButtonState({ armed: false, busy: true });
    if (textEl) {
      textEl.textContent = 'Arming hard kill...';
    }
    try {
      const resp = await fetch('/api/v1/safety/panic', {
        method: 'POST',
        headers: {
          Accept: 'application/json',
        },
      });
      const body = await resp.json().catch(() => ({}));
      if (!resp.ok) {
        throw new Error(String(body.detail || body.reason || `HTTP ${resp.status}`));
      }
      applyStatus(body, { keepStatusBar: true });
      const locked = parseIntSafe(body.locked_connectors, 0);
      setStatusBarText(`PANIC L5 active · ${locked} tmux connector${locked === 1 ? '' : 's'} locked`);
      if (textEl) {
        textEl.textContent = `Hard kill armed. Locked ${locked} tmux connector${locked === 1 ? '' : 's'}.`;
      }
    } catch (err) {
      if (textEl) {
        textEl.textContent = `Panic failed: ${String(err?.message || 'Unknown error')}`;
      }
    } finally {
      panicInFlight = false;
      setPanicButtonState({ armed: false, busy: false });
      fetchStatus({ force: true }).catch(() => {});
    }
  }

  function handlePanicClick() {
    if (!panicBtn || panicInFlight || panicBtn.classList.contains('d-none')) return;
    const now = Date.now();
    if (now >= panicConfirmArmedUntil) {
      armPanicConfirm();
      return;
    }
    triggerPanic().catch(() => {});
  }

  function startPolling() {
    if (pollTimer) return;
    pollTimer = window.setInterval(() => {
      fetchStatus().catch(() => {});
    }, POLL_MS);
  }

  function stopPolling() {
    if (!pollTimer) return;
    window.clearInterval(pollTimer);
    pollTimer = null;
  }

  applyStatus(
    {
      kill_switch_level: parseIntSafe(strip.dataset.killSwitchLevel, 0),
      execution_enabled: parseBool(strip.dataset.executionEnabled),
      read_only: parseBool(strip.dataset.readOnly),
      effective_read_only: parseBool(strip.dataset.readOnly),
      can_panic: parseBool(strip.dataset.canPanic),
      kill_switch_label: LEVEL_LABELS[parseIntSafe(strip.dataset.killSwitchLevel, 0)] || 'normal',
    },
    { keepStatusBar: true },
  );

  if (refreshBtn) {
    refreshBtn.addEventListener('click', () => {
      fetchStatus({ force: true }).catch(() => {});
    });
  }
  if (panicBtn) {
    panicBtn.addEventListener('click', handlePanicClick);
  }

  document.addEventListener('visibilitychange', () => {
    if (document.hidden) {
      stopPolling();
      clearPanicConfirmArmed();
      return;
    }
    fetchStatus({ force: true }).catch(() => {});
    startPolling();
  });

  window.addEventListener('blur', () => {
    clearPanicConfirmArmed();
  });

  fetchStatus({ force: true }).catch(() => {});
  startPolling();
})();
