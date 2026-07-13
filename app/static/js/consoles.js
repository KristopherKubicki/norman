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
  const runtimeBadgeEl = document.getElementById('consoles-runtime-status-badge');
  const runtimeMetricsEl = document.getElementById('consoles-runtime-metrics');
  const runtimeRefreshEl = document.getElementById('consoles-runtime-refresh');
  const runtimeWorkerStartEl = document.getElementById('consoles-runtime-worker-start');
  const runtimeWorkerStopEl = document.getElementById('consoles-runtime-worker-stop');
  const runtimeStatusEl = document.getElementById('consoles-runtime-status');
  const runtimeJobsEl = document.getElementById('consoles-runtime-jobs');
  const runtimeJobCountEl = document.getElementById('consoles-runtime-job-count');
  const runtimeSelectedEl = document.getElementById('consoles-runtime-selected');
  const runtimeSelectedMetaEl = document.getElementById('consoles-runtime-selected-meta');
  const runtimeRunDryEl = document.getElementById('consoles-runtime-run-dry');
  const runtimeRunLiveEl = document.getElementById('consoles-runtime-run-live');
  const runtimeRejectEl = document.getElementById('consoles-runtime-reject');
  const runtimeConfirmEl = document.getElementById('consoles-runtime-confirm');
  const runtimeTimelineEl = document.getElementById('consoles-runtime-timeline');

  if (!paneListEl || !outputEl) return;

  let panes = [];
  let favorites = [];
  let selectedTarget = '';
  let activeSocketPath = '';
  let pendingSelectTarget = '';
  let followTimer = null;
  let activeCaptureSeq = 0;
  let runtimeJobs = [];
  let selectedRuntimeJobId = '';
  let selectedRuntimeSnapshot = null;
  let selectedRuntimeRouteSummary = null;
  let runtimeAfter = 0;
  let runtimePollTimer = null;
  let runtimeConfirmation = 'ENABLE LIVE RUNTIME';

  const SAVED_SOCKETS_KEY = 'norman_tmux_saved_sockets_v1';
  const ACTIVE_SOCKET_KEY = 'norman_tmux_active_socket_v1';
  const CONSOLES_MOBILE_PANE_KEY = 'norman.mobile.consoles.pane.v1';
  const CONSOLES_SELECTED_TARGET_KEY = 'norman.consoles.selected_target.v1';
  const CONSOLES_RUNTIME_SELECTED_JOB_KEY = 'norman.consoles.runtime.selected_job.v1';
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
      return ['viewer', 'panes', 'runtime'].includes(value) ? value : null;
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

  function readStoredRuntimeJob() {
    try {
      return String(localStorage.getItem(CONSOLES_RUNTIME_SELECTED_JOB_KEY) || '').trim();
    } catch (err) {
      return '';
    }
  }

  function writeStoredRuntimeJob(jobId) {
    try {
      if (!jobId) {
        localStorage.removeItem(CONSOLES_RUNTIME_SELECTED_JOB_KEY);
        return;
      }
      localStorage.setItem(CONSOLES_RUNTIME_SELECTED_JOB_KEY, String(jobId));
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

  function setRuntimeStatus(message, level = 'info') {
    if (!runtimeStatusEl) return;
    if (!message) {
      runtimeStatusEl.classList.add('d-none');
      runtimeStatusEl.textContent = '';
      runtimeStatusEl.classList.remove('alert-danger', 'alert-success', 'alert-warning');
      runtimeStatusEl.classList.add('alert-info');
      return;
    }
    runtimeStatusEl.classList.remove('d-none');
    runtimeStatusEl.textContent = message;
    runtimeStatusEl.classList.remove('alert-info', 'alert-danger', 'alert-success', 'alert-warning');
    if (level === 'danger') runtimeStatusEl.classList.add('alert-danger');
    else if (level === 'ok') runtimeStatusEl.classList.add('alert-success');
    else if (level === 'warn') runtimeStatusEl.classList.add('alert-warning');
    else runtimeStatusEl.classList.add('alert-info');
  }

  function runtimeStatusBadgeClass(config, snapshot) {
    if (config?.live_execution_enabled) return 'bg-danger';
    if (snapshot?.running) return 'bg-success';
    if (config?.enabled) return 'bg-primary';
    return 'bg-secondary';
  }

  function runtimeModeLabel(config = {}) {
    if (config.live_execution_enabled) return 'live enabled';
    if (config.dry_run) return 'dry-run';
    return 'live gated';
  }

  function metricChip(label, value, tone = '', title = '') {
    const chip = document.createElement('div');
    chip.className = `consoles-runtime-metric ${tone}`.trim();
    if (title) chip.title = title;
    const key = document.createElement('span');
    key.className = 'consoles-runtime-metric__key';
    key.textContent = label;
    const val = document.createElement('span');
    val.className = 'consoles-runtime-metric__value';
    val.textContent = String(value ?? '');
    chip.appendChild(key);
    chip.appendChild(val);
    return chip;
  }

  function norllamaStatusTone(norllama = {}) {
    const mesh = String(norllama.mesh_status || norllama.status || '').toLowerCase();
    const posture = String(norllama.residency_posture || '').toLowerCase();
    if (mesh === 'offline' || mesh === 'error' || posture === 'unavailable') return 'is-danger';
    if (mesh === 'degraded' || posture === 'degraded' || Number(norllama.degraded_count || 0) > 0) return 'is-warn';
    return '';
  }

  function localFirstTone(kpi = {}) {
    const status = String(kpi.status || '').toLowerCase();
    if (status === 'cloud_heavy') return 'is-danger';
    if (status === 'watch' || status === 'no_data') return 'is-warn';
    return '';
  }

  function renderRuntimeWorkerStatus(payload = {}) {
    if (!runtimeBadgeEl || !runtimeMetricsEl) return;
    const config = payload.config || {};
    const snapshot = payload.snapshot || {};
    const norllama = payload.norllama && typeof payload.norllama === 'object' ? payload.norllama : {};
    const localFirst = payload.local_first_kpi && typeof payload.local_first_kpi === 'object' ? payload.local_first_kpi : {};
    const proof = payload.local_first_proof && typeof payload.local_first_proof === 'object' ? payload.local_first_proof : {};
    const proofTotals = proof.totals && typeof proof.totals === 'object' ? proof.totals : {};
    const proofGate = proof.release_gate && typeof proof.release_gate === 'object' ? proof.release_gate : {};
    const workerCount = Number(norllama.worker_count || 0);
    const healthyWorkers = Number(norllama.healthy_worker_count || 0);
    const readiness = Number(localFirst.readiness_percent || 0);
    const cloudLlmPercent = Number(localFirst.cloud_llm_token_percent || 0);
    const proofSessions = Number(proof.session_count || 0);
    const proofSpark = Number(proofTotals.spark_evidence_count || 0);
    const workers = Array.isArray(norllama.workers) ? norllama.workers : [];
    const pressureLine = workers
      .filter((worker) => worker && typeof worker === 'object')
      .map((worker) => {
        const pressure = worker.pressure && typeof worker.pressure === 'object' ? worker.pressure : {};
        const state = String(pressure.state || 'unknown');
        return `${String(worker.id || 'worker')} ${state}`;
      })
      .slice(0, 3)
      .join(', ');
    runtimeConfirmation = payload.live_execution_confirmation || runtimeConfirmation;
    runtimeBadgeEl.className = `badge ${runtimeStatusBadgeClass(config, snapshot)}`;
    runtimeBadgeEl.textContent = snapshot.running ? 'Running' : (config.enabled ? 'Enabled' : 'Stopped');
    runtimeMetricsEl.replaceChildren(
      metricChip('worker', config.enabled ? 'on' : 'off'),
      metricChip('mode', runtimeModeLabel(config), config.live_execution_enabled ? 'is-danger' : ''),
      metricChip('runnable', payload.runnable_count ?? 0),
      metricChip('ticks', snapshot.tick_count ?? 0),
      metricChip('done', snapshot.jobs_completed ?? 0),
      metricChip('failures', snapshot.failures ?? 0, snapshot.failures ? 'is-danger' : ''),
      metricChip(
        'local-first',
        localFirst.status ? `${localFirst.status} ${readiness}%` : 'no data',
        localFirstTone(localFirst),
        (localFirst.reasons || []).join(' • '),
      ),
      metricChip(
        'cloud llm',
        `${Math.round(cloudLlmPercent)}%`,
        cloudLlmPercent > 20 ? 'is-warn' : '',
        `${localFirst.cloud_llm_tokens || 0} cloud LLM tokens`,
      ),
      metricChip(
        'norllama',
        norllama.residency_posture || norllama.route_posture || 'unknown',
        norllamaStatusTone(norllama),
        pressureLine || String(norllama.route_posture || ''),
      ),
      metricChip(
        'proof',
        proofSessions ? `${proofSessions} sess / ${proofSpark} spark` : 'no data',
        proofSessions && !proofGate.proves_local_first ? 'is-warn' : '',
        proofGate.cloud_proxy_visible ? 'cloud proxy visible in ledger' : 'local-first proof sessions',
      ),
      metricChip(
        'mesh',
        workerCount ? `${healthyWorkers}/${workerCount}` : (norllama.mesh_status || 'unknown'),
        norllamaStatusTone(norllama),
        pressureLine,
      ),
      metricChip('prefetch', norllama.prefetch_count ?? 0),
    );
  }

  function formatRuntimeJobObjective(job) {
    return String(job?.contract?.objective || job?.objective || '').trim();
  }

  function compactRuntimeRouteSummary(summary) {
    if (!summary || typeof summary !== 'object') return '';
    const route = summary.route && typeof summary.route === 'object' ? summary.route : {};
    const workers = summary.workers && typeof summary.workers === 'object' ? summary.workers : {};
    const ledger = summary.usage_ledger && typeof summary.usage_ledger === 'object' ? summary.usage_ledger : {};
    const kpi = summary.local_first_kpi && typeof summary.local_first_kpi === 'object' ? summary.local_first_kpi : {};
    const byWorker = workers.by_id && typeof workers.by_id === 'object' ? workers.by_id : {};
    const parts = [];
    const routeTotal = Number(route.total || 0);
    const routeLocal = Number(route.offline_safe || route.local_or_lan || 0);
    const localPercent = Number(summary.local_evidence_percent || route.offline_safe_percent || 0);
    const sparkEvidence = Number(summary.spark_evidence_count || route.spark_hint || 0);
    const cloudEvidence = Number(summary.cloud_evidence_count || route.cloud_llm || route.cloud_proxy || 0);
    const totalTokens = Number(ledger.total_tokens || 0);
    const offlineTokens = Number(ledger.offline_tokens || 0);
    const cloudTokens = Number(ledger.cloud_tokens || 0);
    const cloudLlmTokens = Number(ledger.cloud_llm_tokens || 0);
    if (routeTotal > 0) parts.push(`routes ${routeLocal}/${routeTotal} local`);
    if (Number.isFinite(localPercent) && localPercent > 0) parts.push(`local ${Math.round(localPercent)}%`);
    if (sparkEvidence > 0) parts.push(`spark ${sparkEvidence}`);
    if (cloudEvidence > 0) parts.push(`cloud ${cloudEvidence}`);
    if (totalTokens > 0) {
      parts.push(`tok local ${offlineTokens}/${totalTokens}`);
      if (cloudLlmTokens > 0) parts.push(`cloud llm ${cloudLlmTokens}`);
      else if (cloudTokens > 0) parts.push(`cloud tok ${cloudTokens}`);
    }
    if (kpi.status) parts.push(`kpi ${kpi.status}`);
    const workerLine = Object.entries(byWorker)
      .filter(([workerId, count]) => workerId && Number(count || 0) > 0)
      .slice(0, 2)
      .map(([workerId, count]) => `${workerId} ${count}`)
      .join(', ');
    if (workerLine) parts.push(workerLine);
    return parts.join(' • ');
  }

  function renderRuntimeJobs() {
    if (!runtimeJobsEl) return;
    runtimeJobsEl.innerHTML = '';
    if (runtimeJobCountEl) runtimeJobCountEl.textContent = String(runtimeJobs.length);
    if (!runtimeJobs.length) {
      const empty = document.createElement('div');
      empty.className = 'text-muted small';
      empty.textContent = 'No runtime jobs yet.';
      runtimeJobsEl.appendChild(empty);
      renderSelectedRuntimeJob(null);
      return;
    }

    runtimeJobs.forEach((job) => {
      const jobId = String(job?.job_id || '');
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = `list-group-item list-group-item-action consoles-runtime-job ${jobId === selectedRuntimeJobId ? 'active' : ''}`;
      btn.dataset.jobId = jobId;
      btn.setAttribute('role', 'option');
      btn.setAttribute('aria-selected', jobId === selectedRuntimeJobId ? 'true' : 'false');

      const top = document.createElement('div');
      top.className = 'd-flex align-items-center justify-content-between gap-2';
      const title = document.createElement('span');
      title.className = 'consoles-runtime-job__id';
      title.textContent = jobId || 'runtime job';
      const status = document.createElement('span');
      status.className = 'badge bg-light text-dark consoles-runtime-job__status';
      status.textContent = String(job?.status || 'unknown');
      top.appendChild(title);
      top.appendChild(status);

      const objective = document.createElement('div');
      objective.className = 'small consoles-runtime-job__objective';
      objective.textContent = formatRuntimeJobObjective(job) || 'No objective recorded.';

      btn.appendChild(top);
      btn.appendChild(objective);
      btn.addEventListener('click', () => selectRuntimeJob(jobId));
      runtimeJobsEl.appendChild(btn);
    });
  }

  function renderSelectedRuntimeJob(job, routeSummary = null) {
    selectedRuntimeSnapshot = job || null;
    selectedRuntimeRouteSummary = routeSummary && typeof routeSummary === 'object' ? routeSummary : null;
    const hasJob = Boolean(job?.job_id || selectedRuntimeJobId);
    if (runtimeSelectedEl) runtimeSelectedEl.textContent = job?.job_id || selectedRuntimeJobId || 'None';
    if (runtimeSelectedMetaEl) {
      if (!hasJob) {
        runtimeSelectedMetaEl.textContent = 'Pick a runtime job to inspect events.';
      } else {
        const parts = [job?.status || 'unknown'];
        const objective = formatRuntimeJobObjective(job);
        if (objective) parts.push(objective);
        const routeLine = compactRuntimeRouteSummary(selectedRuntimeRouteSummary);
        if (routeLine) parts.push(routeLine);
        runtimeSelectedMetaEl.textContent = parts.join(' • ');
      }
    }
    if (runtimeRunDryEl) runtimeRunDryEl.disabled = !hasJob;
    if (runtimeRunLiveEl) runtimeRunLiveEl.disabled = !hasJob;
    if (runtimeRejectEl) runtimeRejectEl.disabled = job?.status !== 'waiting_approval';
  }

  function runtimeEventClass(category) {
    const cat = String(category || 'runtime').toLowerCase();
    if ([
      'approval',
      'behavior',
      'checkpoint',
      'goal',
      'job',
      'model',
      'planner',
      'policy',
      'route',
      'shell',
      'tool',
      'verification',
    ].includes(cat)) {
      return `consoles-runtime-event--${cat}`;
    }
    return 'consoles-runtime-event--runtime';
  }

  function compactRuntimePayload(event) {
    const payload = event?.payload || {};
    const type = String(event?.event_type || '');
    if (type === 'behavior.observed') return payload.summary || event.summary || '';
    if (type === 'tool.started') return [payload.tool_name, payload.args_summary].filter(Boolean).join(' • ');
    if (type === 'tool.completed') return [payload.tool_name, payload.output_preview].filter(Boolean).join(' • ');
    if (type === 'tool.failed') return [payload.tool_name, payload.error].filter(Boolean).join(' • ');
    if (type === 'model.delta') return payload.text || event.detail || '';
    if (type === 'model.completed') {
      const usage = payload.usage || {};
      const total = usage.total_tokens ? `${usage.total_tokens} tokens` : '';
      return [payload.provider, payload.model, payload.stop_reason, total].filter(Boolean).join(' • ');
    }
    if (type === 'model.requested') return [payload.provider, payload.model, payload.route_key].filter(Boolean).join(' • ');
    if (type === 'planner.receipt') return [payload.provider, payload.capability, payload.status].filter(Boolean).join(' • ');
    if (type === 'policy.mode_selected') return [payload.active_mode, payload.egress_policy, ...(payload.notices || [])].filter(Boolean).join(' • ');
    if (type === 'policy.egress_blocked') return payload.reason || event.detail || '';
    if (type === 'route.decided') return [
      payload.selected_provider,
      payload.selected_runner,
      payload.selected_model,
      payload.egress_class,
      payload.cost_basis,
      payload.allowed === false ? 'blocked' : 'allowed',
    ].filter(Boolean).join(' • ');
    if (type === 'shell.started') return [payload.command, payload.policy?.decision].filter(Boolean).join(' • ');
    if (type === 'shell.output') return [payload.stream, payload.text].filter(Boolean).join(' • ');
    if (type === 'shell.completed') return [payload.command, `exit ${payload.returncode}`, payload.output_preview].filter(Boolean).join(' • ');
    if (type === 'shell.failed') return [payload.command, payload.error].filter(Boolean).join(' • ');
    if (type.startsWith('checkpoint.')) return payload.summary || event.detail || '';
    if (type.startsWith('verification.')) return payload.summary || payload.result || event.detail || '';
    if (type.startsWith('approval.')) return payload.reason || event.detail || '';
    if (type.startsWith('job.')) return event.detail || payload.reason || payload.summary || '';
    try {
      const text = JSON.stringify(payload);
      return text.length > 360 ? `${text.slice(0, 360)}…` : text;
    } catch (err) {
      return '';
    }
  }

  function appendRuntimeEvent(event) {
    if (!runtimeTimelineEl) return;
    runtimeTimelineEl.querySelectorAll('.consoles-runtime-empty').forEach((node) => node.remove());
    const item = document.createElement('div');
    item.className = `consoles-runtime-event ${runtimeEventClass(event?.category)}`;

    const head = document.createElement('div');
    head.className = 'consoles-runtime-event__head';
    const badge = document.createElement('span');
    badge.className = 'badge consoles-runtime-event__badge';
    badge.textContent = String(event?.category || 'runtime');
    const title = document.createElement('span');
    title.className = 'consoles-runtime-event__type';
    title.textContent = String(event?.event_type || 'runtime.event');
    const seq = document.createElement('span');
    seq.className = 'consoles-runtime-event__sequence';
    seq.textContent = `#${event?.sequence || 0}`;
    head.appendChild(badge);
    head.appendChild(title);
    head.appendChild(seq);

    const summary = document.createElement('div');
    summary.className = 'consoles-runtime-event__summary';
    summary.textContent = event?.summary || compactRuntimePayload(event) || 'Runtime event';
    const detailText = compactRuntimePayload(event);

    item.appendChild(head);
    item.appendChild(summary);
    if (detailText && detailText !== summary.textContent) {
      const detail = document.createElement('div');
      detail.className = 'consoles-runtime-event__detail';
      detail.textContent = detailText;
      item.appendChild(detail);
    }
    runtimeTimelineEl.appendChild(item);
    runtimeTimelineEl.scrollTop = runtimeTimelineEl.scrollHeight;
  }

  async function loadRuntimeStatus({ silent = false } = {}) {
    if (!runtimeBadgeEl) return;
    if (!silent) setRuntimeStatus('Loading runtime worker status…');
    const payload = await fetchJson('/api/v1/console-runtime/worker/status');
    renderRuntimeWorkerStatus(payload);
    if (!silent) setRuntimeStatus('');
  }

  async function loadRuntimeJob({ reset = false } = {}) {
    if (!selectedRuntimeJobId || !runtimeTimelineEl) {
      renderSelectedRuntimeJob(null);
      return;
    }
    const after = reset ? 0 : runtimeAfter;
    const payload = await fetchJson(
      buildUrl(`/api/v1/console-runtime/jobs/${encodeURIComponent(selectedRuntimeJobId)}`, {
        after,
        limit: 200,
      }),
    );
    renderSelectedRuntimeJob(payload.job || null, payload.route_summary || null);
    if (reset) {
      runtimeTimelineEl.innerHTML = '';
    }
    const events = Array.isArray(payload.events) ? payload.events : [];
    events.forEach((event) => appendRuntimeEvent(event));
    runtimeAfter = Number(payload.next_after || runtimeAfter || 0);
    if (!runtimeTimelineEl.childElementCount) {
      const empty = document.createElement('div');
      empty.className = 'text-muted small consoles-runtime-empty';
      empty.textContent = 'No runtime events visible for this job yet.';
      runtimeTimelineEl.appendChild(empty);
    }
  }

  async function loadRuntimeJobs({ resetEvents = false } = {}) {
    if (!runtimeJobsEl) return;
    const payload = await fetchJson(buildUrl('/api/v1/console-runtime/jobs', { limit: 25 }));
    runtimeJobs = Array.isArray(payload.items) ? payload.items : [];
    if (!selectedRuntimeJobId) {
      const saved = readStoredRuntimeJob();
      const savedJob = runtimeJobs.find((job) => String(job?.job_id || '') === saved);
      selectedRuntimeJobId = savedJob?.job_id || runtimeJobs[0]?.job_id || '';
    }
    if (selectedRuntimeJobId && !runtimeJobs.some((job) => String(job?.job_id || '') === selectedRuntimeJobId)) {
      selectedRuntimeJobId = runtimeJobs[0]?.job_id || '';
    }
    writeStoredRuntimeJob(selectedRuntimeJobId);
    renderRuntimeJobs();
    if (selectedRuntimeJobId) {
      await loadRuntimeJob({ reset: resetEvents });
    } else if (runtimeTimelineEl) {
      runtimeTimelineEl.innerHTML = '';
      renderSelectedRuntimeJob(null);
    }
  }

  async function refreshRuntime({ silent = false, resetEvents = false } = {}) {
    if (!runtimeJobsEl) return;
    try {
      if (!silent) setRuntimeStatus('Refreshing runtime state…');
      await loadRuntimeStatus({ silent: true });
      await loadRuntimeJobs({ resetEvents });
      if (!silent) setRuntimeStatus('Runtime state refreshed.', 'ok');
    } catch (err) {
      setRuntimeStatus(`Runtime refresh failed: ${err?.message || err}`, 'danger');
    }
  }

  function selectRuntimeJob(jobId) {
    selectedRuntimeJobId = String(jobId || '').trim();
    runtimeAfter = 0;
    writeStoredRuntimeJob(selectedRuntimeJobId);
    renderRuntimeJobs();
    loadRuntimeJob({ reset: true }).catch((err) => {
      setRuntimeStatus(`Failed to load runtime job: ${err?.message || err}`, 'danger');
    });
    if (isCompactViewport()) {
      setMobilePane('runtime');
    }
  }

  async function controlRuntimeWorker(payload) {
    setRuntimeStatus('Updating runtime worker…');
    await fetchJson('/api/v1/console-runtime/worker/control', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    await refreshRuntime({ silent: true });
    setRuntimeStatus('Runtime worker updated.', 'ok');
  }

  async function approveRuntimeHoldIfNeeded(confirmation) {
    if (!selectedRuntimeJobId) return;
    if (selectedRuntimeSnapshot?.status !== 'waiting_approval') return;
    await fetchJson(`/api/v1/console-runtime/jobs/${encodeURIComponent(selectedRuntimeJobId)}/approval`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        decision: 'approve',
        reason: 'Operator approved one live step from the consoles runtime panel.',
        confirm_live_execution: confirmation,
      }),
    });
  }

  async function runRuntimeStep({ live = false } = {}) {
    if (!selectedRuntimeJobId) {
      setRuntimeStatus('Pick a runtime job first.', 'warn');
      return;
    }
    const confirmation = String(runtimeConfirmEl?.value || '').trim();
    if (live && confirmation !== runtimeConfirmation) {
      setRuntimeStatus(`Type ${runtimeConfirmation} before approving live execution.`, 'warn');
      return;
    }
    const maxSteps = live ? 4 : 6;
    setRuntimeStatus(live ? 'Approving and running a live runtime goal…' : 'Running a dry local-first runtime goal…');
    try {
      if (live) {
        await approveRuntimeHoldIfNeeded(confirmation);
      }
      await fetchJson(`/api/v1/console-runtime/jobs/${encodeURIComponent(selectedRuntimeJobId)}/runs`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          worker_id: 'runtime-tui',
          dry_run: !live,
          continuous: true,
          max_steps: maxSteps,
          max_runtime_seconds: live ? 1800 : 3600,
          goal_phase_sequence: ['plan', 'work', 'verify'],
          cloud_token_budget: 0,
          route_policy: {
            provider: 'norllama',
            use_capability_catalog: true,
            "model_selection": "warm_policy",
          },
          include_capabilities: false,
          live_execution_approved: live,
          confirm_live_execution: live ? confirmation : '',
          metadata: {
            source: 'web_tui',
            goal_loop: true,
            local_first: true,
          },
        }),
      });
      await refreshRuntime({ silent: true, resetEvents: true });
      setRuntimeStatus(live ? 'Live runtime goal finished.' : 'Dry runtime goal finished.', 'ok');
    } catch (err) {
      setRuntimeStatus(`Runtime goal failed: ${err?.message || err}`, 'danger');
      await refreshRuntime({ silent: true, resetEvents: true });
    }
  }

  async function rejectRuntimeHold() {
    if (!selectedRuntimeJobId) return;
    setRuntimeStatus('Rejecting runtime approval hold…');
    try {
      await fetchJson(`/api/v1/console-runtime/jobs/${encodeURIComponent(selectedRuntimeJobId)}/approval`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          decision: 'reject',
          reason: 'Operator rejected the runtime approval hold from the consoles panel.',
        }),
      });
      await refreshRuntime({ silent: true, resetEvents: true });
      setRuntimeStatus('Runtime approval hold rejected.', 'ok');
    } catch (err) {
      setRuntimeStatus(`Failed to reject approval hold: ${err?.message || err}`, 'danger');
    }
  }

  function startRuntimePolling() {
    if (!runtimeJobsEl) return;
    if (runtimePollTimer) window.clearInterval(runtimePollTimer);
    runtimePollTimer = window.setInterval(() => {
      if (!document.hidden) refreshRuntime({ silent: true }).catch(() => {});
    }, 4000);
  }

  function initRuntimePanel() {
    if (!runtimeJobsEl) return;
    selectedRuntimeJobId = readStoredRuntimeJob();
    runtimeRefreshEl?.addEventListener('click', () => {
      refreshRuntime({ resetEvents: true }).catch((err) => {
        setRuntimeStatus(`Runtime refresh failed: ${err?.message || err}`, 'danger');
      });
    });
    runtimeWorkerStartEl?.addEventListener('click', () => {
      controlRuntimeWorker({
        enabled: true,
        dry_run: true,
        live_execution_enabled: false,
      }).catch((err) => setRuntimeStatus(`Failed to start worker: ${err?.message || err}`, 'danger'));
    });
    runtimeWorkerStopEl?.addEventListener('click', () => {
      controlRuntimeWorker({ enabled: false }).catch((err) => {
        setRuntimeStatus(`Failed to stop worker: ${err?.message || err}`, 'danger');
      });
    });
    runtimeRunDryEl?.addEventListener('click', () => {
      runRuntimeStep({ live: false });
    });
    runtimeRunLiveEl?.addEventListener('click', () => {
      runRuntimeStep({ live: true });
    });
    runtimeRejectEl?.addEventListener('click', () => {
      rejectRuntimeHold();
    });
    refreshRuntime({ resetEvents: true });
    startRuntimePolling();
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
    refreshRuntime({ silent: true }).catch(() => {});
  });

  initMobilePaneSwitcher();
  initRuntimePanel();
  selectedTarget = readStoredSelectedTarget();
  activeSocketPath = loadActiveSocket();
  renderSocketControls();
  loadFavorites();
  loadPanes().catch((err) => setStatus(`Failed to load panes: ${err?.message || err}`, 'danger'));
})();
