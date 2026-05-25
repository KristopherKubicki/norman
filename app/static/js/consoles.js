(() => {
  const paneListEl = document.getElementById('consoles-pane-list');
  const countEl = document.getElementById('consoles-count');
  const searchEl = document.getElementById('consoles-search');
  const refreshBtn = document.getElementById('consoles-refresh');
  const socketSelectEl = document.getElementById('consoles-socket-select');
  const socketCustomEl = document.getElementById('consoles-socket-custom');
  const socketSaveEl = document.getElementById('consoles-socket-save');
  const favoritesListEl = document.getElementById('consoles-favorites-list');
  const favoritesRefreshEl = document.getElementById('consoles-favorites-refresh');
  const favoriteSaveEl = document.getElementById('consoles-favorite-save');
  const captureBtn = document.getElementById('consoles-capture');
  const followEl = document.getElementById('consoles-follow');
  const linesEl = document.getElementById('consoles-lines');
  const statusEl = document.getElementById('consoles-status');
  const outputEl = document.getElementById('consoles-output');
  const selectedEl = document.getElementById('consoles-selected');
  const selectedMetaEl = document.getElementById('consoles-selected-meta');
  const pageEl = document.querySelector('.consoles-page');
  const mobilePaneButtons = Array.from(document.querySelectorAll('[data-consoles-pane]'));

  if (!paneListEl || !outputEl) return;

  let panes = [];
  let favorites = [];
  let selectedTarget = '';
  let activeSocketPath = '';
  let pendingSelectTarget = '';
  let followTimer = null;
  let activeCaptureSeq = 0;

  const SAVED_SOCKETS_KEY = 'norman_tmux_saved_sockets_v1';
  const ACTIVE_SOCKET_KEY = 'norman_tmux_active_socket_v1';
  const CONSOLES_MOBILE_PANE_KEY = 'norman.mobile.consoles.pane.v1';
  const CONSOLES_SELECTED_TARGET_KEY = 'norman.consoles.selected_target.v1';
  const CUSTOM_SENTINEL = '__custom__';
  const TMUX_SIMPLIFIED_MAX_LINES = 260;
  const TMUX_SIMPLIFIED_TAIL_LINES = 180;
  let activeMobilePane = 'viewer';
  const mobilePaneMedia = window.matchMedia('(max-width: 991px)');

  function simplifyTmuxCaptureText(value = '') {
    const raw = String(value || '')
      .replace(/\r\n/g, '\n')
      .replace(/\r/g, '\n');
    if (!raw) return '[empty pane output]';

    const noAnsi = raw
      .replace(/\u001b\][^\u0007]*(?:\u0007|\u001b\\)/g, '')
      .replace(/\u001b\[[0-?]*[ -/]*[@-~]/g, '')
      .replace(/[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]/g, '');

    const lines = noAnsi.split('\n').map((line) => line.replace(/[ \t]+$/g, ''));
    const isHudLine = (line) => {
      const text = String(line || '').trim().toLowerCase();
      if (!text) return false;
      if (/^\d+%\s+context left\b/.test(text)) return true;
      if (/^context left\b/.test(text)) return true;
      if (/^\?\s+for shortcuts\b/.test(text)) return true;
      if (/tab to queue message/.test(text)) return true;
      return false;
    };

    const hasHudMarkers = lines.some((line) => isHudLine(line));
    const collapsed = [];
    let blankRun = 0;
    lines.forEach((line) => {
      if (isHudLine(line)) return;
      if (!line.trim()) {
        blankRun += 1;
        if (blankRun <= 1) collapsed.push('');
        return;
      }
      blankRun = 0;
      collapsed.push(line);
    });

    while (collapsed.length && !collapsed[collapsed.length - 1].trim()) {
      collapsed.pop();
    }

    let focused = collapsed;
    if (hasHudMarkers && collapsed.length > TMUX_SIMPLIFIED_MAX_LINES) {
      const removed = collapsed.length - TMUX_SIMPLIFIED_TAIL_LINES;
      focused = collapsed.slice(-TMUX_SIMPLIFIED_TAIL_LINES);
      focused.unshift(`[trimmed ${removed} earlier lines]`);
    }

    const text = focused.join('\n').trimEnd();
    return text || '[empty pane output]';
  }

  function readStoredConsolesMobilePane() {
    try {
      const value = (localStorage.getItem(CONSOLES_MOBILE_PANE_KEY) || '').trim();
      return ['viewer', 'panes'].includes(value) ? value : null;
    } catch (err) {
      return null;
    }
  }

  function writeStoredConsolesMobilePane(pane) {
    try {
      localStorage.setItem(CONSOLES_MOBILE_PANE_KEY, pane);
    } catch (err) {
      // ignore storage errors
    }
  }

  function readStoredSelectedTarget() {
    try {
      return String(localStorage.getItem(CONSOLES_SELECTED_TARGET_KEY) || '').trim();
    } catch (err) {
      return '';
    }
  }

  function writeStoredSelectedTarget(target) {
    try {
      if (!target) {
        localStorage.removeItem(CONSOLES_SELECTED_TARGET_KEY);
        return;
      }
      localStorage.setItem(CONSOLES_SELECTED_TARGET_KEY, String(target));
    } catch (err) {
      // ignore storage errors
    }
  }

  function isCompactViewport() {
    return Boolean(mobilePaneMedia?.matches);
  }

  function setMobilePane(pane) {
    if (!pageEl) return;
    activeMobilePane = pane;
    writeStoredConsolesMobilePane(pane);
    pageEl.dataset.mobilePane = pane;
    mobilePaneButtons.forEach((btn) => {
      btn.classList.toggle('is-active', btn.getAttribute('data-consoles-pane') === pane);
    });
  }

  function initMobilePaneSwitcher() {
    if (!pageEl || !mobilePaneButtons.length) return;
    const savedPane = readStoredConsolesMobilePane();
    if (savedPane) {
      activeMobilePane = savedPane;
    }
    if (isCompactViewport()) {
      // Mobile should open in the live pane first.
      activeMobilePane = 'viewer';
    }
    setMobilePane(activeMobilePane);
    const syncMode = () => {
      if (isCompactViewport()) {
        pageEl.dataset.mobilePane = activeMobilePane;
        return;
      }
      pageEl.removeAttribute('data-mobile-pane');
    };
    syncMode();
    mobilePaneButtons.forEach((btn) => {
      btn.addEventListener('click', () => {
        setMobilePane(btn.getAttribute('data-consoles-pane') || 'viewer');
      });
    });
    if (typeof mobilePaneMedia.addEventListener === 'function') {
      mobilePaneMedia.addEventListener('change', syncMode);
    } else if (typeof mobilePaneMedia.addListener === 'function') {
      mobilePaneMedia.addListener(syncMode);
    }
  }

  function setStatus(message, level = 'info') {
    if (!statusEl) return;
    if (!message) {
      statusEl.classList.add('d-none');
      statusEl.textContent = '';
      statusEl.classList.remove('alert-danger', 'alert-success', 'alert-warning');
      statusEl.classList.add('alert-info');
      return;
    }
    statusEl.classList.remove('d-none');
    statusEl.textContent = message;
    statusEl.classList.remove('alert-info', 'alert-danger', 'alert-success', 'alert-warning');
    if (level === 'danger') statusEl.classList.add('alert-danger');
    else if (level === 'ok') statusEl.classList.add('alert-success');
    else if (level === 'warn') statusEl.classList.add('alert-warning');
    else statusEl.classList.add('alert-info');
  }

  function normalize(s) {
    return String(s || '').toLowerCase();
  }

  function formatPaneLabel(pane) {
    const target = pane?.target || '';
    const title = pane?.pane_title || '';
    const cmd = pane?.pane_current_command || '';
    const path = pane?.pane_current_path || '';
    const parts = [target];
    if (title && title !== 'tmux') parts.push(title);
    if (cmd) parts.push(cmd);
    if (path) parts.push(path);
    return parts.filter(Boolean).join(' • ');
  }

  function buildUrl(path, params = {}) {
    const url = new URL(path, window.location.origin);
    Object.entries(params).forEach(([key, value]) => {
      if (value === undefined || value === null) return;
      const text = String(value).trim();
      if (!text) return;
      url.searchParams.set(key, text);
    });
    return url.toString();
  }

  async function fetchJson(url, options = {}) {
    const headers = { 'Accept': 'application/json', ...(options.headers || {}) };
    const resp = await fetch(url, { ...options, headers });
    if (!resp.ok) {
      const detail = await resp.text().catch(() => '');
      const msg = detail && detail.length < 240 ? detail : `HTTP ${resp.status}`;
      throw new Error(msg);
    }
    return resp.json();
  }

  function loadSavedSockets() {
    try {
      const raw = localStorage.getItem(SAVED_SOCKETS_KEY);
      if (!raw) return [];
      const parsed = JSON.parse(raw);
      if (!Array.isArray(parsed)) return [];
      return parsed
        .filter((item) => item && typeof item === 'object')
        .map((item) => ({ name: String(item.name || '').trim(), path: String(item.path || '').trim() }))
        .filter((item) => item.path);
    } catch (e) {
      return [];
    }
  }

  function saveSockets(items) {
    try {
      localStorage.setItem(SAVED_SOCKETS_KEY, JSON.stringify(items));
    } catch (e) {
      // ignore storage errors
    }
  }

  function loadActiveSocket() {
    try {
      const raw = localStorage.getItem(ACTIVE_SOCKET_KEY);
      return raw ? String(raw) : '';
    } catch (e) {
      return '';
    }
  }

  function saveActiveSocket(path) {
    try {
      localStorage.setItem(ACTIVE_SOCKET_KEY, String(path || ''));
    } catch (e) {
      // ignore
    }
  }

  function guessSocketLabel(path) {
    if (!path) return 'tmux';
    const parts = String(path).split('/');
    const last = parts[parts.length - 1] || '';
    const parent = parts[parts.length - 2] || '';
    if (parent && last) return `${parent}/${last}`;
    return last || path;
  }

  function renderSocketControls() {
    if (!socketSelectEl) return;
    const saved = loadSavedSockets();
    const active = loadActiveSocket();
    activeSocketPath = activeSocketPath || active || '';

    socketSelectEl.innerHTML = '';

    const defaultOpt = document.createElement('option');
    defaultOpt.value = '';
    defaultOpt.textContent = 'Default tmux server';
    socketSelectEl.appendChild(defaultOpt);

    saved.forEach((item) => {
      const opt = document.createElement('option');
      opt.value = item.path;
      opt.textContent = item.name || guessSocketLabel(item.path);
      socketSelectEl.appendChild(opt);
    });

    const customOpt = document.createElement('option');
    customOpt.value = CUSTOM_SENTINEL;
    customOpt.textContent = 'Custom socket…';
    socketSelectEl.appendChild(customOpt);

    const hasSaved = saved.some((s) => s.path === activeSocketPath);
    if (activeSocketPath && !hasSaved) {
      socketSelectEl.value = CUSTOM_SENTINEL;
      if (socketCustomEl) {
        socketCustomEl.classList.remove('d-none');
        socketCustomEl.value = activeSocketPath;
      }
    } else {
      socketSelectEl.value = activeSocketPath || '';
      if (socketCustomEl) {
        socketCustomEl.classList.add('d-none');
        socketCustomEl.value = '';
      }
    }

    socketSelectEl.onchange = () => {
      const value = socketSelectEl.value || '';
      if (value === CUSTOM_SENTINEL) {
        if (socketCustomEl) socketCustomEl.classList.remove('d-none');
        activeSocketPath = socketCustomEl ? String(socketCustomEl.value || '').trim() : '';
      } else {
        if (socketCustomEl) socketCustomEl.classList.add('d-none');
        activeSocketPath = value;
      }
      saveActiveSocket(activeSocketPath);
      selectedTarget = '';
      pendingSelectTarget = '';
      if (captureBtn) captureBtn.disabled = true;
      if (favoriteSaveEl) favoriteSaveEl.disabled = true;
      outputEl.textContent = '';
      setStatus('');
      loadPanes().catch((err) => setStatus(`Failed to load panes: ${err?.message || err}`, 'danger'));
    };

    if (socketCustomEl) socketCustomEl.onkeydown = (ev) => {
      if (ev.key === 'Enter') {
        ev.preventDefault();
        activeSocketPath = String(socketCustomEl.value || '').trim();
        saveActiveSocket(activeSocketPath);
        loadPanes().catch((err) => setStatus(`Failed to load panes: ${err?.message || err}`, 'danger'));
      }
    };

    if (socketSaveEl) socketSaveEl.onclick = () => {
      const path = socketSelectEl.value === CUSTOM_SENTINEL
        ? String(socketCustomEl?.value || '').trim()
        : String(socketSelectEl.value || '').trim();
      if (!path) {
        setStatus('Nothing to save: pick "Custom socket…" and enter a socket path.', 'warn');
        return;
      }
      const defaultName = guessSocketLabel(path);
      const name = window.prompt('Name this tmux socket', defaultName);
      if (!name) return;
      const cleanedName = String(name).trim();
      if (!cleanedName) return;
      const items = loadSavedSockets();
      const existing = items.find((it) => it.path === path);
      if (existing) existing.name = cleanedName;
      else items.push({ name: cleanedName, path });
      saveSockets(items);
      activeSocketPath = path;
      saveActiveSocket(activeSocketPath);
      renderSocketControls();
      loadPanes().catch((err) => setStatus(`Failed to load panes: ${err?.message || err}`, 'danger'));
    };
  }

  async function loadPanes() {
    setStatus('Loading tmux panes…');
    const url = buildUrl('/api/v1/tmux/panes', { socket_path: activeSocketPath });
    const data = await fetchJson(url);
    panes = Array.isArray(data?.items) ? data.items : [];

    panes.sort((a, b) => {
      const sa = String(a?.session_name || '');
      const sb = String(b?.session_name || '');
      if (sa !== sb) return sa.localeCompare(sb);
      const wa = Number(a?.window_index || 0);
      const wb = Number(b?.window_index || 0);
      if (wa !== wb) return wa - wb;
      const pa = Number(a?.pane_index || 0);
      const pb = Number(b?.pane_index || 0);
      return pa - pb;
    });

    renderPaneList(searchEl?.value || '');
    if (pendingSelectTarget) {
      const target = pendingSelectTarget;
      pendingSelectTarget = '';
      selectTargetByString(target);
      return;
    }
    if (!selectedTarget && panes.length) {
      selectPane(panes[0]);
      return;
    }
    if (selectedTarget) {
      const selectedPane = panes.find((pane) => String(pane?.target || '') === String(selectedTarget));
      if (selectedPane) {
        updateSelectedMeta(selectedPane);
        if (captureBtn) captureBtn.disabled = false;
        if (favoriteSaveEl) favoriteSaveEl.disabled = false;
        if (isCompactViewport()) {
          setMobilePane('viewer');
        }
        captureSelected();
        return;
      }
      selectedTarget = '';
      writeStoredSelectedTarget('');
      if (captureBtn) captureBtn.disabled = true;
      if (favoriteSaveEl) favoriteSaveEl.disabled = true;
      updateSelectedMeta(null);
    }
    if (isCompactViewport()) {
      setMobilePane(panes.length ? 'viewer' : 'panes');
    }
    setStatus('');
  }

  function renderPaneList(queryRaw) {
    const query = normalize(queryRaw);
    const filtered = panes.filter((pane) => {
      if (!query) return true;
      const label = formatPaneLabel(pane);
      return normalize(label).includes(query) || normalize(pane?.session_name).includes(query);
    });

    if (countEl) countEl.textContent = String(filtered.length);

    const bySession = new Map();
    filtered.forEach((pane) => {
      const session = pane?.session_name || 'unknown';
      if (!bySession.has(session)) bySession.set(session, []);
      bySession.get(session).push(pane);
    });

    paneListEl.innerHTML = '';
    if (!filtered.length) {
      const empty = document.createElement('div');
      empty.className = 'text-muted small';
      empty.textContent = 'No panes found.';
      paneListEl.appendChild(empty);
      return;
    }

    Array.from(bySession.keys()).sort().forEach((session) => {
      const header = document.createElement('div');
      header.className = 'list-group-item console-session-header';
      header.textContent = session;
      header.setAttribute('role', 'presentation');
      paneListEl.appendChild(header);

      bySession.get(session).forEach((pane) => {
        const target = pane?.target || '';
        const btn = document.createElement('button');
        btn.type = 'button';
        btn.className = `list-group-item list-group-item-action console-pane-item ${target === selectedTarget ? 'active' : ''}`;
        btn.textContent = formatPaneLabel(pane);
        btn.dataset.target = target;
        btn.setAttribute('role', 'option');
        btn.setAttribute('aria-selected', target === selectedTarget ? 'true' : 'false');
        btn.addEventListener('click', () => selectPane(pane));
        paneListEl.appendChild(btn);
      });
    });
  }

  function updateSelectedMeta(pane) {
    if (selectedEl) selectedEl.textContent = pane?.target || 'None';
    if (selectedMetaEl) {
      const meta = [];
      if (pane?.pane_title) meta.push(`title: ${pane.pane_title}`);
      if (pane?.pane_current_command) meta.push(`cmd: ${pane.pane_current_command}`);
      if (pane?.pane_current_path) meta.push(pane.pane_current_path);
      selectedMetaEl.textContent = meta.length ? meta.join(' • ') : 'Pick a pane to view output.';
    }
  }

  function selectTargetByString(target) {
    if (!target) return;
    writeStoredSelectedTarget(target);
    const found = panes.find((p) => String(p?.target || '') === String(target));
    if (found) {
      selectPane(found);
      return;
    }
    // Pane not in list (different socket or stale target). Still allow a capture attempt.
    selectedTarget = target;
    if (selectedEl) selectedEl.textContent = target;
    if (selectedMetaEl) selectedMetaEl.textContent = 'Saved target not currently listed. Try Capture to verify.';
    if (captureBtn) captureBtn.disabled = false;
    if (favoriteSaveEl) favoriteSaveEl.disabled = false;
    renderPaneList(searchEl?.value || '');
    if (isCompactViewport()) {
      setMobilePane('viewer');
    }
    captureSelected();
  }

  function selectPane(pane) {
    selectedTarget = pane?.target || '';
    writeStoredSelectedTarget(selectedTarget);
    updateSelectedMeta(pane);
    if (captureBtn) captureBtn.disabled = !selectedTarget;
    if (favoriteSaveEl) favoriteSaveEl.disabled = !selectedTarget;
    renderPaneList(searchEl?.value || '');
    if (isCompactViewport()) {
      setMobilePane('viewer');
    }
    captureSelected();
  }

  function getLines() {
    const raw = linesEl?.value || '200';
    const value = Number.parseInt(raw, 10);
    if (!Number.isFinite(value)) return 200;
    return Math.max(10, Math.min(2000, value));
  }

  async function captureSelected() {
    if (!selectedTarget) return;
    const seq = ++activeCaptureSeq;
    const lines = getLines();
    setStatus(`Capturing ${lines} lines from ${selectedTarget}…`);
    try {
      const url = buildUrl('/api/v1/tmux/capture', {
        target: selectedTarget,
        lines: lines,
        socket_path: activeSocketPath,
      });
      const data = await fetchJson(url);
      if (seq !== activeCaptureSeq) return; // stale response
      outputEl.textContent = simplifyTmuxCaptureText(data?.text || '');
      setStatus(`Captured ${lines} lines from ${selectedTarget}.`, 'ok');
    } catch (err) {
      if (seq !== activeCaptureSeq) return;
      setStatus(`Capture failed: ${err?.message || err}`, 'danger');
    }
  }

  function stopFollow() {
    if (followTimer) window.clearInterval(followTimer);
    followTimer = null;
  }

  function startFollow() {
    stopFollow();
    followTimer = window.setInterval(() => {
      if (!document.hidden) captureSelected();
    }, 2000);
  }

  refreshBtn?.addEventListener('click', () => {
    loadPanes().catch((err) => setStatus(`Failed to load panes: ${err?.message || err}`, 'danger'));
  });

  captureBtn?.addEventListener('click', () => {
    captureSelected();
  });

  async function loadFavorites() {
    try {
      const data = await fetchJson(
        buildUrl('/api/v1/console_targets/', { kind: 'tmux' }),
      );
      favorites = Array.isArray(data) ? data : [];
      renderFavorites();
    } catch (err) {
      setStatus(`Failed to load favorites: ${err?.message || err}`, 'danger');
    }
  }

  function renderFavorites() {
    if (!favoritesListEl) return;
    favoritesListEl.innerHTML = '';
    if (!favorites.length) {
      const empty = document.createElement('div');
      empty.className = 'text-muted small';
      empty.textContent = 'No favorites yet. Select a pane and click Save.';
      favoritesListEl.appendChild(empty);
      return;
    }

    favorites.forEach((fav) => {
      const item = document.createElement('div');
      item.className = 'list-group-item console-favorite-row d-flex align-items-center justify-content-between gap-2';
      const selectBtn = document.createElement('button');
      selectBtn.type = 'button';
      selectBtn.className = 'btn btn-link p-0 text-start console-favorite-select';
      selectBtn.textContent = fav.name || fav.target || 'favorite';
      selectBtn.title = `${fav.target || ''}${fav.socket_path ? ` • ${fav.socket_path}` : ''}`;
      selectBtn.addEventListener('click', () => {
        activeSocketPath = String(fav.socket_path || '').trim();
        saveActiveSocket(activeSocketPath);
        renderSocketControls();
        pendingSelectTarget = String(fav.target || '').trim();
        loadPanes().catch((err) => setStatus(`Failed to load panes: ${err?.message || err}`, 'danger'));
      });

      const actions = document.createElement('div');
      actions.className = 'd-flex align-items-center gap-1';

      const delBtn = document.createElement('button');
      delBtn.type = 'button';
      delBtn.className = 'btn btn-outline-danger btn-sm';
      delBtn.textContent = 'Remove';
      delBtn.addEventListener('click', async (ev) => {
        ev.preventDefault();
        ev.stopPropagation();
        if (!window.confirm(`Remove favorite "${fav.name}"?`)) return;
        try {
          await fetchJson(`/api/v1/console_targets/${encodeURIComponent(fav.id)}`, {
            method: 'DELETE',
          });
        } catch (err) {
          setStatus(`Failed to remove favorite: ${err?.message || err}`, 'danger');
          return;
        }
        await loadFavorites();
      });

      actions.appendChild(delBtn);
      item.appendChild(selectBtn);
      item.appendChild(actions);
      favoritesListEl.appendChild(item);
    });
  }

  favoritesRefreshEl?.addEventListener('click', () => {
    loadFavorites();
  });

  favoriteSaveEl?.addEventListener('click', async () => {
    if (!selectedTarget) return;
    const pane = panes.find((p) => String(p?.target || '') === String(selectedTarget)) || null;
    const sessionName = pane?.session_name || (String(selectedTarget).split(':')[0] || '');
    const defaultName = pane?.pane_title
      ? `${sessionName} • ${pane.pane_title}`
      : selectedTarget;
    const name = window.prompt('Save favorite as', defaultName);
    if (!name) return;
    const cleaned = String(name).trim();
    if (!cleaned) return;

    const payload = {
      name: cleaned,
      kind: 'tmux',
      socket_path: activeSocketPath || '',
      session_name: sessionName || null,
      target: selectedTarget,
    };
    setStatus('Saving favorite…');
    try {
      const resp = await fetch('/api/v1/console_targets/', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'Accept': 'application/json' },
        body: JSON.stringify(payload),
      });
      if (!resp.ok) {
        const data = await resp.json().catch(() => ({}));
        const msg = data?.detail || `HTTP ${resp.status}`;
        throw new Error(msg);
      }
      setStatus('Favorite saved.', 'ok');
      await loadFavorites();
    } catch (err) {
      setStatus(`Failed to save favorite: ${err?.message || err}`, 'danger');
    }
  });

  followEl?.addEventListener('change', () => {
    if (followEl.checked) startFollow();
    else stopFollow();
  });

  linesEl?.addEventListener('change', () => {
    captureSelected();
  });

  searchEl?.addEventListener('input', () => {
    renderPaneList(searchEl.value || '');
  });

  document.addEventListener('visibilitychange', () => {
    if (document.hidden) return;
    if (followEl?.checked) captureSelected();
  });

  initMobilePaneSwitcher();
  selectedTarget = readStoredSelectedTarget();
  activeSocketPath = loadActiveSocket();
  renderSocketControls();
  loadFavorites();
  loadPanes().catch((err) => setStatus(`Failed to load panes: ${err?.message || err}`, 'danger'));
})();
