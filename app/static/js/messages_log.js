let selectedChannelId = null;
let channelsCache = [];
let randomSim = {
  timer: null,
  stopAt: null,
  channelId: null
};
let connectorsById = new Map();
let consolePanesCache = [];
let selectedConsoleTarget = '';
let consoleFollowTimer = null;
let consoleFollowInFlight = false;
let consoleRequestSeq = 0;
let activeConversationConsoleTarget = '';
let activeConversationConsoleSocketPath = '';
let consoleConversationRequestSeq = 0;
let messagesRequestSeq = 0;
let messagesFollowTimer = null;
let messagesFollowInFlight = false;
let streamsFocusMode = false;
let messagesViewportTrackingCleanup = null;
let streamsLayout = { hideLeft: false, hideRight: false, wide: false };
let streamsFullscreen = false;
let streamsThreadMode = true;
let streamsSimpleMode = true;
let activeMobilePane = 'conversation';
let mobilePaneMedia = null;
let openConsoleInspectorOnMobile = false;
let sendInFlight = false;
let composerResizeObserver = null;
let pendingConsoleResponse = null;
let streamsProfilePanelOpen = false;
let tmuxProfilesCache = [];
let tmuxControlSessionsCache = [];
let tmuxAutoHuntTimer = null;
let tmuxAutoHuntInFlight = false;
let tmuxAutoHuntEnabled = true;
let agentControlBusy = false;
let inboxApprovalsCache = [];
let inboxApprovalsInFlight = false;
let inboxApprovalsLastFetchAt = 0;
let inboxPollTimer = null;
let launchThreadHint = '';
let launchDraftMessage = '';
let launchFocusComposer = false;
let launchContextApplied = false;
let estateServicesCache = [];
let currentConsoleConversationText = '';
let secretPanelOpen = false;
let secretStashCache = [];
let secretDraftState = { value: '', concealed: false };
const tmuxAutoResumeAttempts = new Map();
const MESSAGES_MOBILE_PANE_KEY = 'norman.mobile.messages.pane.v1';
const STREAMS_FOCUS_MODE_KEY = 'norman.streams.focus_mode.v1';
const STREAMS_SELECTED_CHANNEL_KEY = 'norman.streams.selected_channel.v1';
const STREAMS_LAYOUT_KEY = 'norman.streams.layout.v1';
const STREAMS_THREAD_MODE_KEY = 'norman.streams.thread_mode.v1';
const STREAMS_SIMPLE_MODE_KEY = 'norman.streams.simple_mode.v1';
const STREAMS_UI_SCHEMA_KEY = 'norman.streams.ui.schema.v1';
const STREAMS_UI_SCHEMA_VERSION = '2026-02-22-1';
const STREAMS_TMUX_PROFILE_KEY = 'norman.streams.tmux_profile.v1';
const STREAMS_TMUX_HUNT_KEY = 'norman.streams.tmux_hunt_enabled.v1';
const STREAMS_TMUX_PROFILE_DEFAULT = 'default_pack';
const STREAMS_TMUX_RUNNING_PROFILE = 'running_now';
const MESSAGE_FOLLOW_INTERVAL_MS = 4000;
const CONSOLE_FOLLOW_INTERVAL_MS = 2500;
const TMUX_AUTO_HUNT_INTERVAL_MS = 15000;
const TMUX_SEND_TIMEOUT_MS = 12000;
const CHANNEL_SEND_TIMEOUT_MS = 12000;
const CONSOLE_RESPONSE_STALE_MS = 45000;
const DEFAULT_COMPOSE_HINT = 'Send or Enter · Shift+Enter adds a new line · @session routes thread';
const TMUX_SEND_ENTER_COUNT = 2;
const TMUX_SIMPLIFIED_MAX_LINES = 60;
const TMUX_SIMPLIFIED_TAIL_LINES = 45;
const TMUX_AUTO_RESUME_COOLDOWN_MS = 12000;
const INBOX_POLL_INTERVAL_MS = 20000;
const INBOX_MIN_FETCH_INTERVAL_MS = 8000;
const SECRET_STASH_DEFAULT_TTL_SECONDS = 86400;
const LLM_STATUS_POLL_INTERVAL_MS = 30000;
const SUPER_TUI_PRIME_OPEN_KEY = 'norman.messages.super_tui.prime_open.v1';
let llmStatusPollTimer = null;
const CONSOLE_COMMAND_PREFIXES = [
  'sudo', 'cd', 'ls', 'pwd', 'git', 'npm', 'node', 'python', 'python3', 'pytest',
  'make', 'cat', 'sed', 'rg', 'grep', 'find', 'tmux', 'screen', 'uv', 'docker',
  'kubectl', 'aws', 'ssh', 'curl', 'wget', 'export', 'source', 'bash', 'sh',
  'ln', 'cp', 'mv', 'rm', 'mkdir', 'touch',
];
const TMUX_RECOVERY_PATTERNS = [
  'error connecting to',
  'no server running',
  'no such file or directory',
  "can't find pane",
  "can't find window",
  'missing tmux target',
  'stale',
];
const SYSTEM_THREAD_SESSIONS = new Set(['operator', 'logs', 'castlegoals']);
const SENSITIVE_QUERY_PARAM_NAMES = new Set([
  'api_key',
  'apikey',
  'access_token',
  'refresh_token',
  'client_secret',
  'signing_secret',
  'webhook_secret',
  'app_password',
  'password',
  'passwd',
  'passphrase',
  'passcode',
  'private_key',
  'secret',
  'token',
  'pwd',
]);
const SENSITIVE_LABEL_PATTERN = '(?:api[_ -]?key|access[_ -]?token|refresh[_ -]?token|client[_ -]?secret|signing[_ -]?secret|webhook[_ -]?secret|app[_ -]?password|mcp[_ -]?api[_ -]?key|password|passwd|passphrase|passcode|private[_ -]?key|secret|token|pwd)';
const SENSITIVE_ASSIGNMENT_RE = new RegExp(
  `((?:"|')?${SENSITIVE_LABEL_PATTERN}(?:"|')?\\s*[:=]\\s*)(\\"(?:[^"\\\\n]|\\\\.)*\\"|'(?:[^'\\\\n]|\\\\.)*'|[^\\s,;]+)`,
  'gi',
);
const SENSITIVE_QUERY_RE = /((?:[?&])(?:api(?:[_-]?key)?|access[_-]?token|refresh[_-]?token|client[_-]?secret|signing[_-]?secret|webhook[_-]?secret|app[_-]?password|password|passwd|passphrase|passcode|private[_-]?key|secret|token|pwd)=)([^&#\s]+)/gi;
const SENSITIVE_BEARER_RE = /(\bBearer\s+)([A-Za-z0-9._~+/=-]+)/gi;
const SENSITIVE_PRIVATE_KEY_BLOCK_RE = /-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z0-9 ]*PRIVATE KEY-----/gi;
const SENSITIVE_JWT_RE = /\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9._-]{8,}\.[A-Za-z0-9._-]{8,}\b/g;
const SENSITIVE_AWS_KEY_RE = /\b(?:AKIA|ASIA)[A-Z0-9]{16}\b/g;
const SENSITIVE_OPAQUE_TOKEN_RE = /^[A-Za-z0-9._~+/=-]{24,}$/;

function readStoredTmuxProfileName() {
  try {
    return String(localStorage.getItem(STREAMS_TMUX_PROFILE_KEY) || '').trim();
  } catch (err) {
    return '';
  }
}

function writeStoredTmuxProfileName(name) {
  const value = String(name || '').trim();
  try {
    if (!value) {
      localStorage.removeItem(STREAMS_TMUX_PROFILE_KEY);
      return;
    }
    localStorage.setItem(STREAMS_TMUX_PROFILE_KEY, value);
  } catch (err) {
    // ignore storage errors
  }
}

function readStoredTmuxAutoHuntEnabled() {
  try {
    const raw = localStorage.getItem(STREAMS_TMUX_HUNT_KEY);
    if (raw == null || raw === '') return true;
    return raw !== '0';
  } catch (err) {
    return true;
  }
}

function writeStoredTmuxAutoHuntEnabled(enabled) {
  try {
    localStorage.setItem(STREAMS_TMUX_HUNT_KEY, enabled ? '1' : '0');
  } catch (err) {
    // ignore storage errors
  }
}

function normalizeTmuxProfileName(value) {
  const name = String(value || '').trim();
  if (!/^[A-Za-z0-9_.-]{1,64}$/.test(name)) {
    throw new Error('Profile name must use letters, numbers, dot, underscore, or dash.');
  }
  return name;
}

function tmuxControlSessionSignature(items = tmuxControlSessionsCache) {
  if (!Array.isArray(items) || !items.length) return '';
  return items
    .map((item) => normalizeKey(item?.session_name))
    .filter((value) => value)
    .sort()
    .join('|');
}

function setComposeFeedback(message = '', tone = 'muted') {
  const el = document.getElementById('streams-compose-feedback');
  if (!el) return;
  const text = String(message || '').trim();
  if (!text) {
    el.textContent = '';
    el.className = 'streams-compose-feedback';
    return;
  }
  el.textContent = text;
  el.className = `streams-compose-feedback is-${tone}`;
}

function llmStatusTone(payload = {}) {
  const mode = String(payload.mode || '').trim();
  if (mode === 'primary') return 'ok';
  if (mode === 'backup_online' || mode === 'offline_local') return 'warn';
  if (mode === 'control_only') return 'danger';
  return 'idle';
}

function renderLlmStatus(payload = {}) {
  const chip = document.getElementById('messages-llm-status-chip');
  const detail = document.getElementById('messages-llm-status-detail');
  const wrap = document.getElementById('messages-llm-status');
  if (!chip || !detail || !wrap) return;
  const modeLabel = String(payload.mode_label || payload.mode || 'Unknown').trim() || 'Unknown';
  const providerLabel = String(payload.active_provider_label || 'Unavailable').trim() || 'Unavailable';
  const activeModel = String(payload.active_model || '').trim();
  const fallbackReason = String(payload.fallback_reason || payload.last_error || '').trim();
  const tone = llmStatusTone(payload);
  chip.className = `status-chip ${tone}`;
  chip.textContent = modeLabel;
  const parts = [providerLabel];
  if (activeModel) parts.push(activeModel);
  detail.textContent = parts.join(' · ') || 'Unavailable';
  wrap.title = fallbackReason || `${modeLabel} via ${providerLabel}${activeModel ? ` (${activeModel})` : ''}`;
}

async function loadLlmStatus({ silent = false } = {}) {
  try {
    const response = await fetch('/api/llm/status', { cache: 'no-store' });
    if (!response.ok) {
      throw new Error(`status ${response.status}`);
    }
    const payload = await response.json();
    renderLlmStatus(payload);
  } catch (err) {
    if (!silent) {
      renderLlmStatus({
        mode: 'control_only',
        mode_label: 'Control only',
        active_provider_label: 'Unavailable',
        last_error: err.message || 'Unable to load LLM status',
      });
    }
  }
}

function startLlmStatusPolling() {
  if (llmStatusPollTimer) return;
  llmStatusPollTimer = window.setInterval(() => {
    loadLlmStatus({ silent: true });
  }, LLM_STATUS_POLL_INTERVAL_MS);
}

function escapeHtml(value) {
  return String(value || '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function readStoredSuperTuiPrimeOpen() {
  try {
    const raw = localStorage.getItem(SUPER_TUI_PRIME_OPEN_KEY);
    if (raw == null || raw === '') return false;
    return raw !== '0';
  } catch (err) {
    return false;
  }
}

function writeStoredSuperTuiPrimeOpen(open) {
  try {
    localStorage.setItem(SUPER_TUI_PRIME_OPEN_KEY, open ? '1' : '0');
  } catch (err) {
    // ignore storage errors
  }
}

function setSuperTuiPrimeOpen(open) {
  const page = document.querySelector('.messages-page--super');
  const layer = document.getElementById('messages-prime-layer');
  const body = document.getElementById('messages-prime-layer-body');
  const toggle = document.getElementById('messages-prime-layer-toggle');
  const frame = document.getElementById('messages-prime-layer-frame');
  if (!page || !layer || !body || !toggle) return;
  const next = !!open;
  page.classList.toggle('super-prime-open', next);
  layer.dataset.open = next ? 'true' : 'false';
  body.hidden = !next;
  toggle.setAttribute('aria-expanded', next ? 'true' : 'false');
  toggle.textContent = next ? 'Hide Prime' : 'Prime Deck';
  if (next && frame && !frame.getAttribute('src')) {
    const src = String(layer.dataset.src || '').trim();
    if (src) frame.setAttribute('src', src);
  }
  writeStoredSuperTuiPrimeOpen(next);
}

function initSuperTuiPrimeLayer() {
  const page = document.querySelector('.messages-page--super');
  const layer = document.getElementById('messages-prime-layer');
  const toggle = document.getElementById('messages-prime-layer-toggle');
  if (!page || !layer || !toggle) return;
  setSuperTuiPrimeOpen(readStoredSuperTuiPrimeOpen());
  toggle.addEventListener('click', () => {
    const isOpen = String(layer.dataset.open || 'true') === 'true';
    setSuperTuiPrimeOpen(!isOpen);
  });
}

function hasRegexMatch(regex, value) {
  regex.lastIndex = 0;
  const matched = regex.test(String(value || ''));
  regex.lastIndex = 0;
  return matched;
}

function redactSensitiveText(value = '', options = {}) {
  const { maskQueryParams = true } = options;
  let text = String(value || '').replace(/\r\n/g, '\n').replace(/\r/g, '\n');
  text = text.replace(SENSITIVE_PRIVATE_KEY_BLOCK_RE, '[private key redacted]');
  text = text.replace(SENSITIVE_ASSIGNMENT_RE, (_, prefix) => `${prefix}[secret redacted]`);
  if (maskQueryParams) {
    text = text.replace(SENSITIVE_QUERY_RE, (_, prefix) => `${prefix}[secret redacted]`);
  }
  text = text.replace(SENSITIVE_BEARER_RE, (_, prefix) => `${prefix}[secret redacted]`);
  text = text.replace(SENSITIVE_JWT_RE, '[secret redacted]');
  text = text.replace(SENSITIVE_AWS_KEY_RE, '[secret redacted]');
  return text;
}

function renderMaskedPlainText(value = '') {
  return escapeHtml(redactSensitiveText(value, { maskQueryParams: true })).replace(/\n/g, '<br>');
}

function renderMaskedPreformattedText(value = '') {
  return escapeHtml(redactSensitiveText(value, { maskQueryParams: true }));
}

function analyzeSensitiveText(value = '') {
  const text = String(value || '').trim();
  if (!text) {
    return { flagged: false, reasons: [] };
  }
  const reasons = [];
  if (hasRegexMatch(SENSITIVE_PRIVATE_KEY_BLOCK_RE, text)) {
    reasons.push('private key');
  }
  if (hasRegexMatch(SENSITIVE_ASSIGNMENT_RE, text)) {
    reasons.push('secret assignment');
  }
  if (hasRegexMatch(SENSITIVE_QUERY_RE, text)) {
    reasons.push('secret query parameter');
  }
  if (hasRegexMatch(SENSITIVE_BEARER_RE, text)) {
    reasons.push('bearer token');
  }
  if (hasRegexMatch(SENSITIVE_JWT_RE, text)) {
    reasons.push('JWT token');
  }
  if (hasRegexMatch(SENSITIVE_AWS_KEY_RE, text)) {
    reasons.push('AWS access key');
  }
  if (!reasons.length && SENSITIVE_OPAQUE_TOKEN_RE.test(text)) {
    reasons.push('opaque token');
  }
  return {
    flagged: reasons.length > 0,
    reasons,
  };
}

function getSecretSummaryDefault() {
  return 'Keep raw values out of the thread. Stash them here and send only a pointer.';
}

function setSecretSummary(message = '', tone = 'muted') {
  const el = document.getElementById('streams-secret-summary');
  if (!el) return;
  const text = String(message || '').trim() || getSecretSummaryDefault();
  el.textContent = text;
  el.className = `streams-secret-summary is-${tone}`;
}

function setSecretStatus(message = '', tone = 'muted') {
  const el = document.getElementById('streams-secret-status');
  if (!el) return;
  const text = String(message || '').trim();
  if (!text) {
    el.textContent = '';
    el.className = 'streams-secret-status';
    return;
  }
  el.textContent = text;
  el.className = `streams-secret-status is-${tone}`;
}

function setSecretPanelOpen(open) {
  secretPanelOpen = Boolean(open);
  const panel = document.getElementById('streams-secret-panel');
  const toggle = document.getElementById('streams-secret-toggle');
  if (panel) panel.classList.toggle('d-none', !secretPanelOpen);
  if (toggle) {
    toggle.setAttribute('aria-expanded', secretPanelOpen ? 'true' : 'false');
    toggle.classList.toggle('btn-outline-secondary', !secretPanelOpen);
    toggle.classList.toggle('btn-outline-primary', secretPanelOpen);
  }
}

function formatSecretDraftPreview(value = '') {
  const raw = String(value || '').replace(/\r\n/g, '\n').replace(/\r/g, '\n');
  if (!raw) return '0 lines · 0 chars';
  const lineCount = Math.max(1, raw.split('\n').length);
  const charCount = raw.length;
  const lineLabel = lineCount === 1 ? 'line' : 'lines';
  const charLabel = charCount === 1 ? 'char' : 'chars';
  return `${lineCount} ${lineLabel} · ${charCount} ${charLabel}`;
}

function syncSecretDraftUi(options = {}) {
  const { syncField = true } = options;
  const valueInput = document.getElementById('streams-secret-value');
  const meta = document.getElementById('streams-secret-draft-meta');
  const visibilityButton = document.getElementById('streams-secret-visibility');
  const rawValue = String(secretDraftState.value || '');
  const hasValue = Boolean(rawValue);
  if (valueInput && syncField) {
    if (secretDraftState.concealed && hasValue) {
      valueInput.value = '';
      valueInput.readOnly = true;
      valueInput.classList.add('is-concealed');
      valueInput.placeholder = `Draft concealed. ${formatSecretDraftPreview(rawValue)}. Reveal to inspect or stash now.`;
    } else {
      valueInput.readOnly = false;
      valueInput.classList.remove('is-concealed');
      if (valueInput.value !== rawValue) {
        valueInput.value = rawValue;
      }
      valueInput.placeholder = 'Paste a secret here. It will not be added to the thread.';
    }
  }
  if (meta) {
    if (!hasValue) {
      meta.textContent = 'No draft loaded.';
      meta.className = 'streams-secret-draft-meta';
    } else {
      meta.textContent = secretDraftState.concealed
        ? `Draft concealed • ${formatSecretDraftPreview(rawValue)}`
        : `Draft visible • ${formatSecretDraftPreview(rawValue)}`;
      meta.className = `streams-secret-draft-meta ${secretDraftState.concealed ? 'is-concealed' : 'is-visible'}`;
    }
  }
  if (visibilityButton) {
    visibilityButton.disabled = Boolean(valueInput?.disabled) || !hasValue;
    visibilityButton.textContent = secretDraftState.concealed ? 'Reveal Draft' : 'Conceal Draft';
  }
}

function getSecretDraftValue() {
  const valueInput = document.getElementById('streams-secret-value');
  if (!secretDraftState.concealed && valueInput) {
    secretDraftState.value = String(valueInput.value || '');
  }
  return String(secretDraftState.value || '');
}

function concealSecretDraft() {
  const value = getSecretDraftValue();
  if (!value.trim()) return false;
  secretDraftState.value = value;
  secretDraftState.concealed = true;
  syncSecretDraftUi();
  setSecretStatus(`Draft concealed. ${formatSecretDraftPreview(value)} ready to stash.`, 'muted');
  return true;
}

function revealSecretDraft(options = {}) {
  const { focus = true } = options;
  if (!String(secretDraftState.value || '').trim()) return false;
  secretDraftState.concealed = false;
  syncSecretDraftUi();
  if (focus) {
    const valueInput = document.getElementById('streams-secret-value');
    if (valueInput) {
      valueInput.focus({ preventScroll: true });
      const end = valueInput.value.length;
      valueInput.setSelectionRange(end, end);
    }
  }
  setSecretStatus('Draft revealed for review.', 'muted');
  return true;
}

function clearSecretDraft() {
  const labelInput = document.getElementById('streams-secret-label');
  const valueInput = document.getElementById('streams-secret-value');
  if (labelInput) labelInput.value = '';
  if (valueInput) {
    valueInput.value = '';
    valueInput.readOnly = false;
    valueInput.classList.remove('is-concealed');
    valueInput.placeholder = 'Paste a secret here. It will not be added to the thread.';
  }
  secretDraftState = { value: '', concealed: false };
  syncSecretDraftUi({ syncField: false });
}

function appendPointerToComposer(reference = '') {
  const input = document.getElementById('messageInput');
  const text = String(reference || '').trim();
  if (!input || !text) return;
  const prefix = input.value && !String(input.value).endsWith('\n') ? '\n' : '';
  input.value = `${input.value || ''}${prefix}${text}`;
  autoResizeComposer();
  window.requestAnimationFrame(syncComposerOffset);
  input.focus({ preventScroll: true });
  updateComposerSecretState();
}

function stageSecretDraft(value = '', options = {}) {
  const { label = '', reason = '', conceal = true } = options;
  const channelId = Number(selectedChannelId || 0);
  if (!channelId) {
    setStatus('channels-status', 'Select a thread before moving a secret into the stash.', 'warning');
    setSecretSummary('Select a thread before moving secrets into the stash.', 'warn');
    return false;
  }
  const labelInput = document.getElementById('streams-secret-label');
  const valueInput = document.getElementById('streams-secret-value');
  setSecretPanelOpen(true);
  if (labelInput && !String(labelInput.value || '').trim() && label) {
    labelInput.value = label;
  }
  secretDraftState.value = String(value || '');
  secretDraftState.concealed = Boolean(secretDraftState.value && conceal);
  syncSecretDraftUi();
  if (valueInput && !secretDraftState.concealed) {
    valueInput.focus({ preventScroll: true });
  }
  setSecretStatus(
    reason || 'Potential secret moved into the private stash. Review it, stash it, then send the pointer instead.',
    'warn',
  );
  setSecretSummary('Potential secret detected. Use the stash instead of sending raw values.', 'warn');
  return true;
}

function renderSecretStashList() {
  const list = document.getElementById('streams-secret-list');
  if (!list) return;
  list.innerHTML = '';
  if (!selectedChannelId) {
    list.innerHTML = '<div class="small text-muted">Select a thread to see its secret pointers.</div>';
    return;
  }
  if (!secretStashCache.length) {
    list.innerHTML = '<div class="small text-muted">No secret pointers for this thread yet.</div>';
    return;
  }
  secretStashCache.forEach((item) => {
    const row = document.createElement('div');
    row.className = 'streams-secret-item';
    row.innerHTML = `
      <div class="streams-secret-item__head">
        <div>
          <div class="streams-secret-item__label">${escapeHtml(item.label || 'Secret')}</div>
          <div class="streams-secret-item__meta">${escapeHtml(item.masked_preview || '')}</div>
        </div>
        <div class="streams-secret-item__expires">${escapeHtml(formatSecretExpiryLabel(item.expires_at))}</div>
      </div>
      <code class="streams-secret-item__pointer">${escapeHtml(item.pointer || '')}</code>
      <div class="streams-secret-item__buttons">
        <button type="button" class="btn btn-sm btn-outline-secondary" data-secret-insert="${escapeHtml(item.prompt_reference || '')}">Insert Pointer</button>
        <button type="button" class="btn btn-sm btn-outline-secondary" data-secret-copy="${escapeHtml(item.pointer || '')}">Copy Pointer</button>
        <button type="button" class="btn btn-sm btn-outline-danger" data-secret-revoke="${Number(item.id || 0)}">Revoke</button>
      </div>
    `;
    list.appendChild(row);
  });
}

function syncSecretPanelState() {
  const hasThread = Number(selectedChannelId || 0) > 0;
  const labelInput = document.getElementById('streams-secret-label');
  const valueInput = document.getElementById('streams-secret-value');
  const stashButton = document.getElementById('streams-secret-stash');
  const stashOnlyButton = document.getElementById('streams-secret-stash-only');
  const clearButton = document.getElementById('streams-secret-clear');
  const visibilityButton = document.getElementById('streams-secret-visibility');
  if (labelInput) labelInput.disabled = !hasThread;
  if (valueInput) valueInput.disabled = !hasThread;
  if (stashButton) stashButton.disabled = !hasThread;
  if (stashOnlyButton) stashOnlyButton.disabled = !hasThread;
  if (clearButton) clearButton.disabled = !hasThread;
  if (visibilityButton) visibilityButton.disabled = !hasThread || !String(secretDraftState.value || '').trim();
  syncSecretDraftUi();
  if (!hasThread) {
    secretStashCache = [];
    renderSecretStashList();
    setSecretStatus('Select a thread, then stash a secret.', 'muted');
    setSecretSummary('Select a thread to stash secrets and send only a pointer.', 'muted');
    return;
  }
  setSecretSummary(getSecretSummaryDefault(), 'muted');
}

async function loadSecretStash(channelId = selectedChannelId) {
  const activeChannelId = Number(channelId || 0);
  if (!activeChannelId) {
    secretStashCache = [];
    renderSecretStashList();
    return;
  }
  const resp = await fetchWithTimeout(
    `/api/v1/keys/stash?channel_id=${activeChannelId}`,
    { cache: 'no-store' },
    CHANNEL_SEND_TIMEOUT_MS,
  );
  const body = await resp.json().catch(() => ([]));
  if (!resp.ok) {
    throw new Error(body.detail || 'Unable to load secret stash.');
  }
  if (Number(selectedChannelId || 0) !== activeChannelId) return;
  secretStashCache = Array.isArray(body) ? body : [];
  renderSecretStashList();
}

async function stashSecretDraft(options = {}) {
  const { insertPointer = true } = options;
  const channelId = Number(selectedChannelId || 0);
  const labelInput = document.getElementById('streams-secret-label');
  const valueInput = document.getElementById('streams-secret-value');
  const stashButton = document.getElementById('streams-secret-stash');
  const stashOnlyButton = document.getElementById('streams-secret-stash-only');
  if (!channelId || !labelInput || !valueInput || !stashButton) {
    setSecretStatus('Select a thread before stashing a secret.', 'warn');
    return;
  }
  const value = getSecretDraftValue();
  const label = String(labelInput.value || '').trim();
  if (!value.trim()) {
    setSecretStatus('Paste a secret first.', 'warn');
    return;
  }
  stashButton.disabled = true;
  if (stashOnlyButton) stashOnlyButton.disabled = true;
  setSecretStatus('Stashing secret…', 'pending');
  try {
    const resp = await fetchWithTimeout(
      '/api/v1/keys/stash',
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          channel_id: channelId,
          label,
          value,
          ttl_seconds: SECRET_STASH_DEFAULT_TTL_SECONDS,
          source: 'editor_manual',
        }),
      },
      CHANNEL_SEND_TIMEOUT_MS,
    );
    const body = await resp.json().catch(() => ({}));
    if (!resp.ok) {
      throw new Error(body.detail || 'Unable to stash secret.');
    }
    clearSecretDraft();
    secretStashCache = [body, ...secretStashCache.filter((item) => Number(item.id) !== Number(body.id))];
    renderSecretStashList();
    if (insertPointer) {
      appendPointerToComposer(body.prompt_reference || body.pointer || '');
    }
    setSecretStatus(
      insertPointer
        ? `Stashed ${body.label || 'secret'} and inserted its pointer into the composer.`
        : `Stashed ${body.label || 'secret'}. Insert or copy the pointer when needed.`,
      'ok',
    );
    setComposeFeedback(
      insertPointer ? 'Secret pointer ready.' : 'Secret stashed. Insert or copy the pointer when needed.',
      'ok',
    );
    setSecretSummary(getSecretSummaryDefault(), 'ok');
  } catch (err) {
    setSecretStatus(err.message || 'Unable to stash secret.', 'err');
  } finally {
    stashButton.disabled = false;
    if (stashOnlyButton) stashOnlyButton.disabled = false;
  }
}

async function revokeSecretStashItem(stashId) {
  const id = Number(stashId || 0);
  if (!id) return;
  setSecretStatus('Revoking secret pointer…', 'pending');
  try {
    const resp = await fetchWithTimeout(
      `/api/v1/keys/stash/${id}/revoke`,
      { method: 'POST' },
      CHANNEL_SEND_TIMEOUT_MS,
    );
    const body = await resp.json().catch(() => ({}));
    if (!resp.ok) {
      throw new Error(body.detail || 'Unable to revoke secret pointer.');
    }
    secretStashCache = secretStashCache.filter((item) => Number(item.id) !== id);
    renderSecretStashList();
    setSecretStatus(`Revoked ${body.label || 'secret pointer'}.`, 'ok');
  } catch (err) {
    setSecretStatus(err.message || 'Unable to revoke secret pointer.', 'err');
  }
}

async function copyTextToClipboard(value = '') {
  const text = String(value || '').trim();
  if (!text) return false;
  if (navigator?.clipboard?.writeText) {
    await navigator.clipboard.writeText(text);
    return true;
  }
  const fallback = document.createElement('textarea');
  fallback.value = text;
  fallback.setAttribute('readonly', 'readonly');
  fallback.style.position = 'fixed';
  fallback.style.opacity = '0';
  fallback.style.pointerEvents = 'none';
  document.body.appendChild(fallback);
  fallback.focus();
  fallback.select();
  const copied = document.execCommand('copy');
  document.body.removeChild(fallback);
  return copied;
}

function shouldCaptureSensitiveText(value = '') {
  return analyzeSensitiveText(value).flagged;
}

function updateComposerSecretState() {
  const composer = document.getElementById('messageInput');
  const directPaneInput = document.getElementById('messages-console-input');
  const composerFlagged = composer ? shouldCaptureSensitiveText(composer.value || '') : false;
  const directFlagged = directPaneInput ? shouldCaptureSensitiveText(directPaneInput.value || '') : false;
  if (composer) composer.classList.toggle('is-secret-risk', composerFlagged);
  if (directPaneInput) directPaneInput.classList.toggle('is-secret-risk', directFlagged);
  if (composerFlagged || directFlagged) {
    const analysis = analyzeSensitiveText(
      composerFlagged ? composer.value || '' : directPaneInput?.value || '',
    );
    const label = analysis.reasons[0] || 'secret';
    setSecretSummary(`Potential ${label} detected. Use Secrets to stash it and send only a pointer.`, 'warn');
    return;
  }
  setSecretSummary(getSecretSummaryDefault(), 'muted');
}

function maybeCaptureSensitivePaste(event, options = {}) {
  const { source = 'composer' } = options;
  const text = String(event?.clipboardData?.getData('text/plain') || '');
  if (!text || !shouldCaptureSensitiveText(text)) {
    return false;
  }
  event.preventDefault();
  const staged = stageSecretDraft(
    text,
    {
      reason: source === 'composer'
        ? 'Secret-like paste diverted to the private stash. Review it, stash it, then send the pointer.'
        : 'Secret-like paste diverted to the private stash instead of the direct pane input.',
    },
  );
  if (!staged) return true;
  if (source === 'composer') {
    setComposeFeedback('Secret-like paste diverted to Secrets.', 'warn');
  } else {
    setConsoleStatus('Secret-like paste diverted to Secrets.', 'warning');
  }
  return true;
}

function createSendError(message, code = 'send_error') {
  const err = new Error(String(message || 'Unable to send.'));
  err.code = String(code || 'send_error');
  return err;
}

function classifySendFailure(error) {
  const message = String(error?.message || 'Unable to send.').trim();
  const code = String(error?.code || '').trim().toLowerCase();
  const lower = message.toLowerCase();
  if (
    code === 'blocked'
    || lower.includes('blocked')
    || lower.includes('kill-switch')
    || lower.includes('read-only')
  ) {
    return { type: 'warning', tone: 'warn', message };
  }
  if (code === 'needs_approval' || lower.includes('approval')) {
    return { type: 'warning', tone: 'warn', message };
  }
  if (lower.includes('not found') || lower.includes('unavailable')) {
    return { type: 'warning', tone: 'warn', message };
  }
  return { type: 'danger', tone: 'err', message };
}

function simplifyTmuxCaptureText(value = '') {
  const raw = String(value || '')
    .replace(/\r\n/g, '\n')
    .replace(/\r/g, '\n')
    // Some panes can concatenate inline heartbeat text into the user input.
    .replace(/(\S)(\[\s*norman goal tick\b)/gi, '$1\n$2');
  if (!raw) return '[empty pane output]';

  // Strip terminal control sequences and non-printable control bytes.
  const noAnsi = raw
    .replace(/\u001b\][^\u0007]*(?:\u0007|\u001b\\)/g, '')
    .replace(/\u001b\[[0-?]*[ -/]*[@-~]/g, '')
    .replace(/[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]/g, '');

  const lines = noAnsi.split('\n').map((line) => line.replace(/[ \t]+$/g, ''));

  const isTmuxHudLine = (line) => {
    const text = String(line || '').trim().toLowerCase();
    if (!text) return false;
    if (/^\d+%\s+context left\b/.test(text)) return true;
    if (/^context left\b/.test(text)) return true;
    if (/^\?\s+for shortcuts\b/.test(text)) return true;
    if (/tab to queue message/.test(text)) return true;
    if (/^\/ps to view\b/.test(text)) return true;
    if (/^\/clean to close\b/.test(text)) return true;
    if (/^■\s+conversation interrupted\b/.test(text)) return true;
    return false;
  };

  const isTmuxNoiseLine = (line) => {
    const text = String(line || '').trim();
    if (!text) return false;
    const lower = text.toLowerCase();
    if (/^[│└├╰╭]/.test(text)) return true;
    if (/^↳\s+interacted with\b/.test(lower)) return true;
    if (/^─{12,}$/.test(text)) return true;
    if (/^›(?:\s+|$)/.test(text)) return true;
    if (/^\?\s+for shortcuts\b/.test(lower)) return true;
    if (/^\d+%\s+context left\b/.test(lower)) return true;
    if (/^context left\b/.test(lower)) return true;
    if (/^•\s+(ran|explored|edited|planning|investigating|working)\b/.test(lower)) return true;
    if (/^booting mcp server\b/.test(lower)) return true;
    return false;
  };

  const normalized = lines.map((line) => {
    if (!line) return '';
    if (isTmuxHudLine(line) || isTmuxNoiseLine(line)) {
      return '';
    }
    return line;
  });

  const collapsed = [];
  let blankRun = 0;
  let hiddenGoalTickCount = 0;
  const isNormanGoalTickLine = (text) => (
    /^\[[^\]]*norman goal tick\b/i.test(text)
    || /\bgoal tick\b.*\bproject=/i.test(text)
    || /::\s*reply with objective\s*\|\s*next\s*\|\s*blockers\s*\|\s*verification/i.test(text)
    || /^castle notes window\./i.test(text)
  );
  const flushHiddenGoalTicks = () => {
    if (!hiddenGoalTickCount) return;
    if (hiddenGoalTickCount === 1) {
      collapsed.push('[hidden 1 norman goal tick]');
    } else {
      collapsed.push(`[hidden ${hiddenGoalTickCount} norman goal ticks]`);
    }
    hiddenGoalTickCount = 0;
  };
  normalized.forEach((line) => {
    const text = String(line || '').trim();
    if (isNormanGoalTickLine(text)) {
      hiddenGoalTickCount += 1;
      return;
    }
    if (!text) {
      if (hiddenGoalTickCount) {
        return;
      }
      blankRun += 1;
      if (blankRun <= 1) collapsed.push('');
      return;
    }
    flushHiddenGoalTicks();
    blankRun = 0;
    collapsed.push(line);
  });
  flushHiddenGoalTicks();

  // Drop duplicate consecutive lines caused by repeated pane polls.
  const deduped = [];
  for (let idx = 0; idx < collapsed.length; idx += 1) {
    const current = String(collapsed[idx] || '');
    const previous = idx > 0 ? String(collapsed[idx - 1] || '') : '';
    if (current && current === previous) continue;
    deduped.push(current);
  }

  while (deduped.length && !deduped[deduped.length - 1].trim()) {
    deduped.pop();
  }

  let focused = deduped;
  if (deduped.length > TMUX_SIMPLIFIED_MAX_LINES) {
    const removed = deduped.length - TMUX_SIMPLIFIED_TAIL_LINES;
    focused = deduped.slice(-TMUX_SIMPLIFIED_TAIL_LINES);
    if (removed > 0) {
      focused.unshift(`[trimmed ${removed} earlier lines]`);
    }
  }

  const text = focused.join('\n').trimEnd();
  return text || '[empty pane output]';
}

function getCurrentConsoleConversationText() {
  return String(currentConsoleConversationText || '');
}

function classifyConsoleTranscriptLine(line = '') {
  const text = String(line || '').trim();
  if (!text) return 'blank';
  const lower = text.toLowerCase();

  if (
    /^\[(trimmed|hidden|empty)/i.test(text)
    || /^token usage:/i.test(text)
    || /^to continue this session,\s*run /i.test(text)
    || /^\^\w+$/.test(text)
    || /^\[\d+\]\+\s+stopped\b/i.test(text)
    || /stream disconnected before completion/i.test(lower)
  ) {
    return 'meta';
  }

  if (/^[A-Za-z0-9._-]+@[^:]+:.*[$#]\s+.+/.test(text)) {
    return 'command';
  }

  if (/^(?:\(.+\)\s+)?CODEX_HOME=/.test(text)) {
    return 'command';
  }

  if (CONSOLE_COMMAND_PREFIXES.some((prefix) => lower.startsWith(`${prefix} `) || lower === prefix)) {
    return 'command';
  }

  return 'response';
}

function buildConsoleTranscriptSegments(text = '') {
  const raw = String(text || '').replace(/\r\n/g, '\n');
  if (!raw.trim()) {
    return [{ type: 'meta', text: '[empty pane output]' }];
  }
  const lines = raw.split('\n');
  const segments = [];
  let current = null;

  const pushCurrent = () => {
    if (!current || !current.lines.length) return;
    segments.push({
      type: current.type,
      text: current.lines.join('\n').trimEnd(),
    });
    current = null;
  };

  lines.forEach((line) => {
    const kind = classifyConsoleTranscriptLine(line);
    if (kind === 'blank') {
      pushCurrent();
      return;
    }
    if (!current || current.type !== kind) {
      pushCurrent();
      current = { type: kind, lines: [line] };
      return;
    }
    current.lines.push(line);
  });
  pushCurrent();

  if (!segments.length) {
    return [{ type: 'meta', text: '[empty pane output]' }];
  }
  return segments;
}

function clearPendingConsoleResponse() {
  pendingConsoleResponse = null;
}

function startPendingConsoleResponse(channel, target, baselineText = '') {
  if (!channel || !Number.isFinite(Number(channel.id))) return;
  const resolvedTarget = String(target || '').trim();
  pendingConsoleResponse = {
    channelId: Number(channel.id),
    target: resolvedTarget,
    baselineText: String(baselineText || ''),
    startedAt: Date.now(),
  };
  if (resolvedTarget) {
    setComposeFeedback(`Seen. Delivered to ${resolvedTarget}. Waiting for response`, 'pending');
    return;
  }
  setComposeFeedback('Seen. Delivered. Waiting for response', 'pending');
}

function updatePendingConsoleResponse(channel, latestText = '') {
  if (!pendingConsoleResponse || !channel) return;
  if (Number(channel.id) !== Number(pendingConsoleResponse.channelId)) return;

  const text = String(latestText || '');
  if (text && text !== pendingConsoleResponse.baselineText) {
    clearPendingConsoleResponse();
    setComposeFeedback('Response updated.', 'ok');
    return;
  }

  if ((Date.now() - pendingConsoleResponse.startedAt) < CONSOLE_RESPONSE_STALE_MS) return;
  pendingConsoleResponse.startedAt = Date.now();
  const target = String(pendingConsoleResponse.target || '').trim();
  if (target) {
    setComposeFeedback(`Delivered to ${target}. Still thinking`, 'pending');
    return;
  }
  setComposeFeedback('Delivered. Still thinking', 'pending');
}

function setActiveChannelName(name = 'None') {
  const el = document.getElementById('active-channel-name');
  if (!el) return;
  const label = String(name || '').trim();
  el.textContent = label || 'None';
  const mobileLabel = document.getElementById('messages-mobile-thread-label');
  if (mobileLabel) {
    mobileLabel.textContent = label || 'None';
  }
}

function setActiveDeliveryTarget(target = 'None', tone = 'muted') {
  const el = document.getElementById('active-delivery-target');
  if (!el) return;
  const label = String(target || '').trim();
  el.textContent = label || 'None';
  el.dataset.tone = tone || 'muted';
}

function formatWebUrlLabel(url = '') {
  return String(url || '')
    .trim()
    .replace(/^https?:\/\//i, '')
    .replace(/\/$/, '') || 'Open App';
}

function setActiveWebLink(channel = null) {
  const link = document.getElementById('active-web-link');
  const empty = document.getElementById('active-web-link-empty');
  if (!link || !empty) return;
  const webUrl = getChannelWebUrl(channel);
  if (webUrl) {
    link.href = webUrl;
    link.textContent = formatWebUrlLabel(webUrl);
    link.title = webUrl;
    link.classList.remove('d-none');
    empty.classList.add('d-none');
    return;
  }
  link.removeAttribute('href');
  link.textContent = 'Open App';
  link.title = '';
  link.classList.add('d-none');
  empty.classList.remove('d-none');
}

function setActiveOperatorBadge(channel = null) {
  const operatorMode = normalizeOperatorMode(getChannelOperatorState(channel)?.mode || 'observe');
  const descriptor = operatorMode === 'take'
    ? { label: 'manual', tone: 'warn' }
    : operatorMode === 'co_pilot'
      ? { label: 'shared', tone: 'ok' }
      : { label: 'auto', tone: 'muted' };
  [
    document.getElementById('messages-active-mode'),
    document.getElementById('messages-mobile-thread-mode'),
  ].forEach((el) => {
    if (!el) return;
    el.textContent = descriptor.label;
    el.classList.remove(
      'messages-thread-state--ok',
      'messages-thread-state--warn',
      'messages-thread-state--muted',
    );
    el.classList.add(`messages-thread-state--${descriptor.tone}`);
  });
}

async function triggerSendMessage() {
  if (sendInFlight) return;
  sendInFlight = true;
  try {
    await sendMessage();
  } finally {
    sendInFlight = false;
  }
}

function readStoredMessagesMobilePane() {
  try {
    const value = (localStorage.getItem(MESSAGES_MOBILE_PANE_KEY) || '').trim();
    return normalizeMessagesMobilePane(value);
  } catch (err) {
    return null;
  }
}

function writeStoredMessagesMobilePane(pane) {
  try {
    localStorage.setItem(MESSAGES_MOBILE_PANE_KEY, pane);
  } catch (err) {
    // ignore storage errors
  }
}

function migrateStreamsUiState() {
  try {
    const current = String(localStorage.getItem(STREAMS_UI_SCHEMA_KEY) || '').trim();
    if (current === STREAMS_UI_SCHEMA_VERSION) return;
    [
      MESSAGES_MOBILE_PANE_KEY,
      STREAMS_FOCUS_MODE_KEY,
      STREAMS_LAYOUT_KEY,
      STREAMS_THREAD_MODE_KEY,
    ].forEach((key) => localStorage.removeItem(key));
    localStorage.setItem(STREAMS_UI_SCHEMA_KEY, STREAMS_UI_SCHEMA_VERSION);
  } catch (err) {
    // ignore storage errors
  }
}

function readMessagesPaneFromUrl() {
  try {
    const params = new URLSearchParams(window.location.search || '');
    const rawPane = String(params.get('pane') || '').trim().toLowerCase();
    if (rawPane === 'consoles') {
      openConsoleInspectorOnMobile = true;
    }
    return normalizeMessagesMobilePane(rawPane);
  } catch (err) {
    return null;
  }
}

function readLaunchContextFromUrl() {
  try {
    const params = new URLSearchParams(window.location.search || '');
    launchThreadHint = String(params.get('thread') || '').trim();
    launchDraftMessage = String(params.get('draft') || '').trim();
    launchFocusComposer = String(params.get('focus') || '').trim() === '1';
  } catch (err) {
    launchThreadHint = '';
    launchDraftMessage = '';
    launchFocusComposer = false;
  }
}

function clearLaunchContextFromUrl() {
  try {
    const url = new URL(window.location.href);
    ['thread', 'draft', 'focus', 'source'].forEach((key) => url.searchParams.delete(key));
    window.history.replaceState({}, '', `${url.pathname}${url.search}${url.hash}`);
  } catch (err) {
    // ignore URL rewrite errors
  }
}

function normalizeMessagesMobilePane(pane) {
  const value = String(pane || '').trim().toLowerCase();
  if (!value) return null;
  // Legacy "consoles" pane links now fold into consolidated Tools.
  if (value === 'consoles') return 'automation';
  if (['conversation', 'channels', 'automation'].includes(value)) {
    return value;
  }
  return null;
}

function readStoredStreamsLayout() {
  try {
    const raw = localStorage.getItem(STREAMS_LAYOUT_KEY);
    if (!raw) return { hideLeft: false, hideRight: false, wide: false };
    const parsed = JSON.parse(raw);
    return {
      hideLeft: Boolean(parsed?.hideLeft),
      hideRight: Boolean(parsed?.hideRight),
      wide: Boolean(parsed?.wide),
    };
  } catch (err) {
    return { hideLeft: false, hideRight: false, wide: false };
  }
}

function writeStoredStreamsLayout() {
  try {
    localStorage.setItem(STREAMS_LAYOUT_KEY, JSON.stringify(streamsLayout));
  } catch (err) {
    // ignore storage errors
  }
}

function readStoredStreamsThreadMode() {
  try {
    const value = String(localStorage.getItem(STREAMS_THREAD_MODE_KEY) || '').trim().toLowerCase();
    if (!value) return true;
    return value !== 'all';
  } catch (err) {
    return true;
  }
}

function writeStoredStreamsThreadMode() {
  try {
    localStorage.setItem(STREAMS_THREAD_MODE_KEY, streamsThreadMode ? 'threads' : 'all');
  } catch (err) {
    // ignore storage errors
  }
}

function readStoredStreamsSimpleMode() {
  try {
    const value = String(localStorage.getItem(STREAMS_SIMPLE_MODE_KEY) || '').trim().toLowerCase();
    if (!value) return true;
    return value !== '0' && value !== 'false' && value !== 'advanced';
  } catch (err) {
    return true;
  }
}

function writeStoredStreamsSimpleMode() {
  try {
    localStorage.setItem(STREAMS_SIMPLE_MODE_KEY, streamsSimpleMode ? '1' : '0');
  } catch (err) {
    // ignore storage errors
  }
}

function applyStreamsSimpleMode() {
  const page = document.querySelector('.messages-page');
  if (page) {
    page.classList.toggle('simple-mode', Boolean(streamsSimpleMode));
  }

  document.querySelectorAll('.streams-advanced-control').forEach((el) => {
    el.classList.toggle('d-none', Boolean(streamsSimpleMode));
  });

  const desktopToggle = document.getElementById('streams-simple-toggle');
  if (desktopToggle) {
    desktopToggle.textContent = streamsSimpleMode ? 'Menu' : 'Close';
    desktopToggle.setAttribute('aria-pressed', streamsSimpleMode ? 'false' : 'true');
  }
  const mobileToggle = document.getElementById('streams-simple-toggle-mobile');
  if (mobileToggle) {
    mobileToggle.textContent = streamsSimpleMode ? 'Menu' : 'Close';
    mobileToggle.setAttribute('aria-pressed', streamsSimpleMode ? 'false' : 'true');
  }
}

function initStreamsSimpleModeControls() {
  streamsSimpleMode = readStoredStreamsSimpleMode();
  applyStreamsSimpleMode();
  [
    document.getElementById('streams-simple-toggle'),
    document.getElementById('streams-simple-toggle-mobile'),
  ].forEach((toggle) => {
    if (!toggle) return;
    toggle.addEventListener('click', () => {
      streamsSimpleMode = !streamsSimpleMode;
      writeStoredStreamsSimpleMode();
      applyStreamsSimpleMode();
    });
  });
}

function applyStreamsLayout() {
  const page = document.querySelector('.messages-page');
  if (!page) return;
  page.classList.toggle('layout-hide-left', Boolean(streamsLayout.hideLeft));
  page.classList.toggle('layout-hide-right', Boolean(streamsLayout.hideRight));
  page.classList.toggle('layout-wide', Boolean(streamsLayout.wide));
  page.classList.toggle('layout-fullscreen', streamsFullscreen);
  document.body.classList.toggle('streams-fullscreen-ui', streamsFullscreen);

  const leftBtn = document.getElementById('streams-toggle-left');
  const rightBtn = document.getElementById('streams-toggle-right');
  const wideBtn = document.getElementById('streams-wide-toggle');
  const fullscreenBtn = document.getElementById('streams-fullscreen-toggle');
  if (leftBtn) {
    leftBtn.textContent = streamsLayout.hideLeft ? 'Show Threads' : 'Hide Threads';
    leftBtn.setAttribute('aria-pressed', streamsLayout.hideLeft ? 'true' : 'false');
  }
  if (rightBtn) {
    rightBtn.textContent = streamsLayout.hideRight ? 'Show Side' : 'Hide Side';
    rightBtn.setAttribute('aria-pressed', streamsLayout.hideRight ? 'true' : 'false');
  }
  if (wideBtn) {
    wideBtn.textContent = streamsLayout.wide ? 'Normal Width' : 'Wide';
    wideBtn.setAttribute('aria-pressed', streamsLayout.wide ? 'true' : 'false');
  }
  if (fullscreenBtn) {
    fullscreenBtn.textContent = streamsFullscreen ? 'Exit Full' : 'Fullscreen';
    fullscreenBtn.setAttribute('aria-pressed', streamsFullscreen ? 'true' : 'false');
  }
}

async function setStreamsFullscreen(enabled) {
  const page = document.querySelector('.messages-page');
  streamsFullscreen = Boolean(enabled);
  applyStreamsLayout();
  if (!page) return;

  if (streamsFullscreen) {
    if (!document.fullscreenElement && typeof page.requestFullscreen === 'function') {
      try {
        await page.requestFullscreen();
      } catch (err) {
        // keep CSS fullscreen mode as fallback
      }
    }
    return;
  }

  if (document.fullscreenElement && typeof document.exitFullscreen === 'function') {
    try {
      await document.exitFullscreen();
    } catch (err) {
      // ignore exit failures
    }
  }
}

function initStreamsLayoutControls() {
  streamsLayout = readStoredStreamsLayout();
  if (isCompactMessagesViewport()) {
    // Desktop layout toggles can trap mobile in an awkward state.
    streamsLayout = { hideLeft: false, hideRight: false, wide: false };
    streamsFullscreen = false;
    writeStoredStreamsLayout();
    document.body.classList.remove('streams-fullscreen-ui');
  }
  applyStreamsLayout();

  const leftBtn = document.getElementById('streams-toggle-left');
  const rightBtn = document.getElementById('streams-toggle-right');
  const wideBtn = document.getElementById('streams-wide-toggle');
  const fullscreenBtn = document.getElementById('streams-fullscreen-toggle');

  if (leftBtn) {
    leftBtn.addEventListener('click', () => {
      streamsLayout.hideLeft = !streamsLayout.hideLeft;
      writeStoredStreamsLayout();
      applyStreamsLayout();
    });
  }
  if (rightBtn) {
    rightBtn.addEventListener('click', () => {
      streamsLayout.hideRight = !streamsLayout.hideRight;
      writeStoredStreamsLayout();
      applyStreamsLayout();
    });
  }
  if (wideBtn) {
    wideBtn.addEventListener('click', () => {
      streamsLayout.wide = !streamsLayout.wide;
      writeStoredStreamsLayout();
      applyStreamsLayout();
    });
  }
  if (fullscreenBtn) {
    fullscreenBtn.addEventListener('click', () => {
      setStreamsFullscreen(!streamsFullscreen);
    });
  }

  document.addEventListener('fullscreenchange', () => {
    if (document.fullscreenElement) return;
    if (!streamsFullscreen) return;
    streamsFullscreen = false;
    applyStreamsLayout();
  });
}

function applyStreamsThreadMode() {
  const page = document.querySelector('.messages-page');
  if (!page) return;
  page.classList.toggle('threads-only-mode', streamsThreadMode);

  const button = document.getElementById('streams-thread-toggle');
  if (button) {
    button.textContent = 'Switch';
    button.title = streamsThreadMode ? 'Currently showing threads. Click to switch to feeds.' : 'Currently showing feeds. Click to switch to threads.';
    button.setAttribute('aria-label', streamsThreadMode ? 'Switch to feeds' : 'Switch to threads');
    button.setAttribute('aria-pressed', streamsThreadMode ? 'true' : 'false');
  }

  const search = document.getElementById('channelSearch');
  if (search) {
    search.placeholder = streamsThreadMode ? 'Filter threads...' : 'Filter all sources...';
  }

  if (channelsCache.length) {
    const visibleChannels = getVisibleChannels();
    updateThreadsMobileBadge(visibleChannels.length, channelsCache.length);
    renderChannelsList(visibleChannels, document.getElementById('channelSearch')?.value || '');
    renderChannelSelects(visibleChannels, channelsCache);
    if (visibleChannels.length) {
      const selectedVisible = visibleChannels.some((channel) => channel.id === selectedChannelId);
      const normanThread = visibleChannels.find((channel) =>
        /^console\s*[-:]\s*norman$/i.test(String(channel.name || '').trim())
      );
      const nextChannelId = selectedVisible
        ? selectedChannelId
        : (normanThread || visibleChannels[0]).id;
      selectChannel(nextChannelId, { focusComposer: false });
    }
  } else {
    updateThreadsMobileBadge(0, 0);
  }
}

function initStreamsThreadModeControls() {
  streamsThreadMode = readStoredStreamsThreadMode();
  applyStreamsThreadMode();
  const button = document.getElementById('streams-thread-toggle');
  if (!button) return;
  button.addEventListener('click', () => {
    streamsThreadMode = !streamsThreadMode;
    writeStoredStreamsThreadMode();
    applyStreamsThreadMode();
  });
}

function updateThreadsMobileBadge(visibleCount = 0, totalCount = 0) {
  const badge = document.getElementById('messages-threads-badge');
  if (!badge) return;
  const safeVisible = Math.max(0, Number.parseInt(visibleCount, 10) || 0);
  const safeTotal = Math.max(0, Number.parseInt(totalCount, 10) || 0);
  badge.textContent = String(safeVisible);
  const show = safeVisible > 0;
  badge.classList.toggle('d-none', !show);
  if (!show) {
    badge.removeAttribute('title');
    return;
  }
  if (safeTotal > safeVisible) {
    badge.title = `${safeVisible} visible threads of ${safeTotal} total`;
    return;
  }
  badge.title = `${safeVisible} threads`;
}

function isCompactMessagesViewport() {
  return Boolean(mobilePaneMedia?.matches);
}

function setMessagesMobilePane(pane) {
  const page = document.querySelector('.messages-page');
  if (!page) return;
  const normalized = normalizeMessagesMobilePane(pane) || 'conversation';
  activeMobilePane = normalized;
  writeStoredMessagesMobilePane(normalized);
  page.dataset.mobilePane = normalized;
  document.body.classList.toggle(
    'messages-drawer-open',
    isCompactMessagesViewport() && normalized !== 'conversation',
  );
  document.querySelectorAll('[data-messages-pane]').forEach((btn) => {
    btn.classList.toggle('is-active', btn.getAttribute('data-messages-pane') === normalized);
  });
  window.requestAnimationFrame(syncComposerOffset);
}

function initMessagesMobilePaneSwitcher() {
  const page = document.querySelector('.messages-page');
  const buttons = Array.from(document.querySelectorAll('[data-messages-pane]'));
  if (!page || !buttons.length) return;

  const paneFromUrl = readMessagesPaneFromUrl();
  const savedPane = readStoredMessagesMobilePane();
  if (paneFromUrl) {
    activeMobilePane = paneFromUrl;
  } else if (savedPane) {
    activeMobilePane = savedPane;
  }

  mobilePaneMedia = window.matchMedia('(max-width: 991px)');
  if (mobilePaneMedia.matches) {
    // Mobile defaults to chat unless a deep link requested another pane.
    if (!paneFromUrl) {
      activeMobilePane = 'conversation';
    }
  }
  setMessagesMobilePane(activeMobilePane);

  buttons.forEach((btn) => {
    btn.addEventListener('click', () => {
      const pane = btn.getAttribute('data-messages-pane') || 'conversation';
      setMessagesMobilePane(pane);
    });
  });

  const syncPaneMode = () => {
    if (isCompactMessagesViewport()) {
      page.dataset.mobilePane = activeMobilePane;
      document.body.classList.toggle('messages-drawer-open', activeMobilePane !== 'conversation');
      return;
    }
    page.removeAttribute('data-mobile-pane');
    document.body.classList.remove('messages-drawer-open');
  };
  syncPaneMode();
  if (typeof mobilePaneMedia.addEventListener === 'function') {
    mobilePaneMedia.addEventListener('change', syncPaneMode);
  } else if (typeof mobilePaneMedia.addListener === 'function') {
    mobilePaneMedia.addListener(syncPaneMode);
  }
}

function readStoredStreamsFocusMode() {
  try {
    const value = localStorage.getItem(STREAMS_FOCUS_MODE_KEY);
    if (value === null) return null;
    return value === '1';
  } catch (err) {
    return null;
  }
}

function writeStoredStreamsFocusMode(enabled) {
  try {
    localStorage.setItem(STREAMS_FOCUS_MODE_KEY, enabled ? '1' : '0');
  } catch (err) {
    // ignore storage errors
  }
}

function readStoredStreamsChannelId() {
  try {
    const raw = localStorage.getItem(STREAMS_SELECTED_CHANNEL_KEY) || '';
    const value = Number.parseInt(raw, 10);
    if (!Number.isFinite(value) || value <= 0) return null;
    return value;
  } catch (err) {
    return null;
  }
}

function writeStoredStreamsChannelId(channelId) {
  if (!Number.isFinite(Number(channelId))) return;
  try {
    localStorage.setItem(STREAMS_SELECTED_CHANNEL_KEY, String(Number(channelId)));
  } catch (err) {
    // ignore storage errors
  }
}

function setStreamsFocusMode(enabled) {
  const page = document.querySelector('.messages-page');
  const desktopToggle = document.getElementById('streams-focus-toggle');
  const mobileToggle = document.getElementById('streams-focus-toggle-mobile');
  if (!page) return;
  streamsFocusMode = Boolean(enabled);
  page.classList.toggle('is-focus-mode', streamsFocusMode);
  if (desktopToggle) {
    desktopToggle.textContent = streamsFocusMode ? 'Panels' : 'Focus';
    desktopToggle.setAttribute('aria-pressed', streamsFocusMode ? 'true' : 'false');
  }
  if (mobileToggle) {
    mobileToggle.textContent = streamsFocusMode ? 'Panels' : 'Focus';
    mobileToggle.setAttribute('aria-pressed', streamsFocusMode ? 'true' : 'false');
  }
  if (streamsFocusMode && isCompactMessagesViewport()) {
    setMessagesMobilePane('conversation');
  }
  writeStoredStreamsFocusMode(streamsFocusMode);
}

function initStreamsFocusMode() {
  const desktopToggle = document.getElementById('streams-focus-toggle');
  const mobileToggle = document.getElementById('streams-focus-toggle-mobile');
  const stored = readStoredStreamsFocusMode();
  const initial = stored === null ? false : stored;
  setStreamsFocusMode(initial);
  [desktopToggle, mobileToggle].forEach((toggle) => {
    if (!toggle) return;
    toggle.addEventListener('click', () => {
      setStreamsFocusMode(!streamsFocusMode);
    });
  });
}

function initMessagesViewportTracking() {
  const page = document.querySelector('.messages-page');
  if (!page) return;

  const vv = window.visualViewport || null;
  const main = document.querySelector('main.container');
  const statusBar = document.getElementById('global-status-bar');
  const navbarCollapse = document.getElementById('navbarNav');
  document.body.classList.add('streams-mobile-tuned');
  if (main) main.classList.add('streams-main');

  const syncViewport = () => {
    const viewportHeight = vv ? vv.height : window.innerHeight;
    page.style.setProperty('--streams-vh', `${Math.round(viewportHeight)}px`);

    if (main) {
      const top = Math.max(0, Math.round(main.getBoundingClientRect().top));
      let statusHeight = 0;
      if (statusBar) {
        const statusStyle = window.getComputedStyle(statusBar);
        if (statusStyle.display !== 'none' && statusStyle.visibility !== 'hidden') {
          statusHeight = Math.ceil(statusBar.getBoundingClientRect().height);
        }
      }
      const chromeGap = isCompactMessagesViewport() ? 2 : 6;
      const available = Math.max(240, Math.floor(viewportHeight - top - statusHeight - chromeGap));
      main.style.height = `${available}px`;
      main.style.minHeight = '0';
    }

    const keyboardOpen = vv ? (window.innerHeight - vv.height) > 140 : false;
    page.classList.toggle('is-keyboard-open', keyboardOpen);
    document.body.classList.toggle('streams-keyboard-open', keyboardOpen);
    syncComposerOffset();
  };

  const onViewportChange = () => window.requestAnimationFrame(syncViewport);
  syncViewport();
  if (vv) {
    vv.addEventListener('resize', onViewportChange);
  }
  window.addEventListener('resize', onViewportChange);
  window.addEventListener('orientationchange', onViewportChange);
  if (navbarCollapse) {
    navbarCollapse.addEventListener('shown.bs.collapse', onViewportChange);
    navbarCollapse.addEventListener('hidden.bs.collapse', onViewportChange);
  }
  window.setTimeout(onViewportChange, 120);

  messagesViewportTrackingCleanup = () => {
    if (vv) {
      vv.removeEventListener('resize', onViewportChange);
    }
    window.removeEventListener('resize', onViewportChange);
    window.removeEventListener('orientationchange', onViewportChange);
    if (navbarCollapse) {
      navbarCollapse.removeEventListener('shown.bs.collapse', onViewportChange);
      navbarCollapse.removeEventListener('hidden.bs.collapse', onViewportChange);
    }
    page.classList.remove('is-keyboard-open');
    page.style.removeProperty('--streams-vh');
    page.style.removeProperty('--streams-compose-offset');
    document.body.classList.remove('streams-keyboard-open');
    document.body.classList.remove('streams-mobile-tuned');
    if (main) {
      main.classList.remove('streams-main');
      main.style.removeProperty('height');
      main.style.removeProperty('min-height');
    }
  };
}

function hideCollapse(id) {
  const el = document.getElementById(id);
  if (!el || !window.bootstrap?.Collapse) return;
  const instance = window.bootstrap.Collapse.getOrCreateInstance(el, { toggle: false });
  instance.hide();
}

function setStatus(id, message, type = 'info') {
  const el = document.getElementById(id);
  if (!el) return;
  if (!message) {
    el.classList.add('d-none');
    el.textContent = '';
    return;
  }
  el.className = `alert alert-${type}`;
  el.textContent = message;
}

function updateCount(id, count) {
  const el = document.getElementById(id);
  if (el) el.textContent = count;
}

function setInboxCount(count = 0) {
  const safeCount = Math.max(0, Number.parseInt(count, 10) || 0);
  updateCount('messages-inbox-count', safeCount);
  const badge = document.getElementById('messages-inbox-badge');
  if (!badge) return;
  badge.textContent = String(safeCount);
  badge.classList.toggle('d-none', safeCount <= 0);
}

function connectorNameForInboxApproval(approval) {
  const connectorId = Number.parseInt(approval?.connector_id, 10);
  if (!Number.isFinite(connectorId)) return 'Unknown connector';
  const match = connectorsById.get(connectorId);
  if (match?.name) return String(match.name);
  return `Connector ${connectorId}`;
}

function formatInboxTimestamp(value) {
  if (!value) return '';
  const dt = new Date(value);
  if (Number.isNaN(dt.getTime())) return '';
  return dt.toLocaleString([], {
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  });
}

function setInboxStatus(message = '', tone = 'muted') {
  const el = document.getElementById('messages-inbox-status');
  if (!el) return;
  el.textContent = String(message || '').trim();
  el.dataset.tone = tone || 'muted';
}

async function fetchPendingInboxApprovals({ force = false } = {}) {
  const now = Date.now();
  if (!force && inboxApprovalsLastFetchAt && (now - inboxApprovalsLastFetchAt) < INBOX_MIN_FETCH_INTERVAL_MS) {
    return { approvals: inboxApprovalsCache, cached: true };
  }
  if (inboxApprovalsInFlight) {
    return { approvals: inboxApprovalsCache, cached: true };
  }
  inboxApprovalsInFlight = true;
  try {
    const resp = await fetch('/api/v1/approvals?status=pending&limit=100', { cache: 'no-store' });
    if (!resp.ok) {
      return { error: `HTTP ${resp.status}` };
    }
    const approvals = await resp.json();
    inboxApprovalsCache = Array.isArray(approvals) ? approvals : [];
    inboxApprovalsLastFetchAt = Date.now();
    return { approvals: inboxApprovalsCache, cached: false };
  } catch (err) {
    return { error: err?.message || 'request failed' };
  } finally {
    inboxApprovalsInFlight = false;
  }
}

async function decideInboxApproval(approvalId, action, confirmToken = '') {
  const endpoint = action === 'approve' ? 'approve' : 'reject';
  const body = endpoint === 'approve'
    ? { reason: 'approved from editor inbox', confirm_token: confirmToken }
    : { reason: 'rejected from editor inbox' };
  const resp = await fetch(`/api/v1/approvals/${approvalId}/${endpoint}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!resp.ok) {
    const payload = await resp.text().catch(() => '');
    throw new Error(payload || `Unable to ${endpoint} approval #${approvalId}.`);
  }
  return resp.json().catch(() => ({}));
}

function createInboxApprovalItem(approval) {
  const item = document.createElement('div');
  item.className = 'list-group-item messages-inbox-item';
  item.dataset.approvalId = String(approval.id || '');

  const head = document.createElement('div');
  head.className = 'messages-inbox-item-head';
  const copy = document.createElement('div');

  const title = document.createElement('div');
  title.className = 'messages-inbox-item-title';
  title.textContent = connectorNameForInboxApproval(approval);
  copy.appendChild(title);

  const meta = document.createElement('div');
  meta.className = 'messages-inbox-item-meta';
  const created = formatInboxTimestamp(approval.created_at);
  const classLabel = String(approval.command_class || 'change').trim() || 'change';
  meta.textContent = created ? `${classLabel} • ${created}` : classLabel;
  copy.appendChild(meta);
  head.appendChild(copy);

  const idBadge = document.createElement('span');
  idBadge.className = 'messages-thread-state messages-thread-state--warn';
  idBadge.textContent = `#${approval.id}`;
  head.appendChild(idBadge);
  item.appendChild(head);

  const reason = document.createElement('div');
  reason.className = 'messages-inbox-item-reason';
  reason.textContent = String(approval.reason || 'Command requires approval.');
  item.appendChild(reason);

  const command = document.createElement('pre');
  command.className = 'messages-inbox-item-command';
  command.textContent = String(approval.command_text || '');
  item.appendChild(command);

  let tokenInput = null;
  if (String(approval.command_class || '').trim() === 'destructive' && approval.confirm_token) {
    const token = document.createElement('div');
    token.className = 'messages-inbox-token';
    token.textContent = `Confirm token: ${approval.confirm_token}`;
    item.appendChild(token);

    tokenInput = document.createElement('input');
    tokenInput.className = 'form-control form-control-sm';
    tokenInput.placeholder = 'Type token to approve';
    tokenInput.autocomplete = 'off';
    tokenInput.spellcheck = false;
    item.appendChild(tokenInput);
  }

  const actions = document.createElement('div');
  actions.className = 'messages-inbox-actions';
  const approveBtn = document.createElement('button');
  approveBtn.type = 'button';
  approveBtn.className = 'btn btn-sm btn-outline-success';
  approveBtn.textContent = 'Approve';
  const rejectBtn = document.createElement('button');
  rejectBtn.type = 'button';
  rejectBtn.className = 'btn btn-sm btn-outline-danger';
  rejectBtn.textContent = 'Reject';

  approveBtn.addEventListener('click', async () => {
    approveBtn.disabled = true;
    rejectBtn.disabled = true;
    setInboxStatus(`Approving #${approval.id}...`, 'muted');
    try {
      await decideInboxApproval(approval.id, 'approve', tokenInput ? String(tokenInput.value || '').trim() : '');
      setInboxStatus(`Approved #${approval.id}.`, 'ok');
      await loadEditorInbox({ force: true, silent: true });
    } catch (err) {
      setInboxStatus(err.message || `Approve failed for #${approval.id}.`, 'warn');
    } finally {
      approveBtn.disabled = false;
      rejectBtn.disabled = false;
    }
  });

  rejectBtn.addEventListener('click', async () => {
    approveBtn.disabled = true;
    rejectBtn.disabled = true;
    setInboxStatus(`Rejecting #${approval.id}...`, 'muted');
    try {
      await decideInboxApproval(approval.id, 'reject');
      setInboxStatus(`Rejected #${approval.id}.`, 'ok');
      await loadEditorInbox({ force: true, silent: true });
    } catch (err) {
      setInboxStatus(err.message || `Reject failed for #${approval.id}.`, 'warn');
    } finally {
      approveBtn.disabled = false;
      rejectBtn.disabled = false;
    }
  });

  actions.appendChild(approveBtn);
  actions.appendChild(rejectBtn);
  item.appendChild(actions);
  return item;
}

function renderEditorInbox(approvals) {
  const container = document.getElementById('messages-inbox-list');
  if (!container) return;
  const items = Array.isArray(approvals) ? approvals : [];
  container.innerHTML = '';
  setInboxCount(items.length);
  if (!items.length) {
    const empty = document.createElement('div');
    empty.className = 'list-group-item text-muted small';
    empty.textContent = 'Inbox is clear. Approvals and escalations will land here.';
    container.appendChild(empty);
    return;
  }
  items.forEach((approval) => {
    container.appendChild(createInboxApprovalItem(approval));
  });
}

async function loadEditorInbox({ force = false, silent = false } = {}) {
  const result = await fetchPendingInboxApprovals({ force });
  if (!result) return;
  if (result.error) {
    if (!silent) {
      setInboxStatus(`Inbox unavailable: ${result.error}`, 'warn');
    }
    return;
  }
  const approvals = Array.isArray(result.approvals) ? result.approvals : [];
  renderEditorInbox(approvals);
  if (!silent) {
    setInboxStatus(
      approvals.length
        ? `${approvals.length} pending approval${approvals.length === 1 ? '' : 's'}.`
        : 'Inbox is clear.',
      approvals.length ? 'warn' : 'muted',
    );
  }
}

function jumpToEditorInbox() {
  setMessagesMobilePane('automation');
  loadEditorInbox({ force: true, silent: false });
  window.setTimeout(() => {
    document.getElementById('messages-inbox-card')?.scrollIntoView({
      block: 'start',
      behavior: 'smooth',
    });
  }, 80);
}

function startEditorInboxPolling() {
  if (inboxPollTimer) return;
  inboxPollTimer = window.setInterval(() => {
    if (document.hidden) return;
    loadEditorInbox({ silent: true });
  }, INBOX_POLL_INTERVAL_MS);
}

function stopEditorInboxPolling() {
  if (!inboxPollTimer) return;
  window.clearInterval(inboxPollTimer);
  inboxPollTimer = null;
}

function normalizeKey(value) {
  return String(value || '')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '');
}

function isTailnetHostLike(value) {
  const text = String(value || '').trim().toLowerCase();
  if (!text) return false;
  if (text.includes('.tail') || text.includes('.ts.net')) return true;
  return /\b100\.(6[4-9]|[78]\d|9\d|1[01]\d|12[0-7])\.\d{1,3}\.\d{1,3}\b/.test(text);
}

function currentEditorRoutePreference() {
  const host = String(window.location.hostname || '').trim().toLowerCase();
  if (isTailnetHostLike(host)) return 'tailnet';
  return 'lan';
}

function resolvePreferredEditorRoute(primaryUrl, tailnetUrl) {
  const primary = String(primaryUrl || '').trim();
  const tailnet = String(tailnetUrl || '').trim();
  const preferTailnet = currentEditorRoutePreference() === 'tailnet';
  if (preferTailnet) {
    if (tailnet) return { primary: tailnet, alternate: primary, mode: 'tailnet' };
    if (primary) return { primary, alternate: '', mode: 'lan' };
    return { primary: '', alternate: '', mode: 'tailnet' };
  }
  if (primary) return { primary, alternate: tailnet, mode: 'lan' };
  if (tailnet) return { primary: tailnet, alternate: '', mode: 'tailnet' };
  return { primary: '', alternate: '', mode: 'lan' };
}

function stripConsolePrefix(value = '') {
  return String(value || '')
    .trim()
    .replace(/^console\s*[-:]\s*/i, '')
    .replace(/^console\s+/i, '')
    .trim();
}

function findEstateServiceForChannel(channel) {
  if (!channel || !Array.isArray(estateServicesCache) || !estateServicesCache.length) return null;
  const keys = new Set();
  const channelName = stripConsolePrefix(channel?.name || '');
  const sessionName = getChannelSessionName(channel);
  const connector = getChannelConnector(channel);
  [
    channelName,
    sessionName,
    connector?.name,
  ].forEach((value) => {
    const raw = String(value || '').trim();
    if (!raw) return;
    keys.add(normalizeKey(raw));
    keys.add(normalizeKey(raw.replace(/^tmux:/i, '')));
    keys.add(normalizeKey(raw.replace(/_/g, ' ')));
    keys.add(normalizeKey(raw.replace(/_/g, '-')));
  });
  for (const service of estateServicesCache) {
    const serviceKeys = [
      service?.display_name,
      service?.slug,
      service?.bot_name,
      service?.worker_name,
      service?.domain_name,
    ]
      .map((value) => normalizeKey(value))
      .filter(Boolean);
    if (serviceKeys.some((key) => keys.has(key))) {
      return service;
    }
  }
  return null;
}

function getChannelEstateRoute(channel) {
  const service = findEstateServiceForChannel(channel);
  if (!service) {
    return { primary: '', alternate: '', mode: currentEditorRoutePreference(), service: null };
  }
  const route = resolvePreferredEditorRoute(
    service.console_url || service.web_url || '',
    service.console_url_tailnet || service.web_url_tailnet || '',
  );
  return { ...route, service };
}

function normalizePaneTty(value) {
  const tty = String(value || '').trim();
  if (!tty) return '';
  if (tty.startsWith('/dev/')) return tty.toLowerCase();
  return `/dev/${tty}`.toLowerCase();
}

function isRecoverableTmuxError(error) {
  const text = String(error?.message || error || '').toLowerCase();
  if (!text) return false;
  return TMUX_RECOVERY_PATTERNS.some((pattern) => text.includes(pattern));
}

function getSelectedChannel() {
  return channelsCache.find(ch => ch.id === selectedChannelId) || null;
}

function findLaunchChannel(channels) {
  const hintKey = normalizeKey(launchThreadHint);
  if (!hintKey) return null;
  return channels.find((channel) => {
    const name = String(channel?.name || '').trim();
    if (!name) return false;
    const key = normalizeKey(name);
    return key === hintKey || key.includes(hintKey) || hintKey.includes(key);
  }) || null;
}

function applyLaunchDraftToComposer() {
  if (launchContextApplied) return;
  const input = document.getElementById('messageInput');
  if (!input) return;
  if (launchDraftMessage) {
    input.value = launchDraftMessage;
    autoResizeComposer();
    setComposeFeedback('Norman Prime brief loaded.', 'muted');
  }
  if (launchFocusComposer) {
    window.setTimeout(() => {
      focusMainComposer();
    }, 40);
  }
  launchContextApplied = true;
  clearLaunchContextFromUrl();
}

function autoResizeComposer() {
  const input = document.getElementById('messageInput');
  if (!input) return;
  input.style.height = 'auto';
  const next = Math.max(44, Math.min(input.scrollHeight, 220));
  input.style.height = `${next}px`;
}

function initComposerInput() {
  const form = document.getElementById('messageComposerForm');
  const input = document.getElementById('messageInput');
  if (!input) return;
  let allowPendingLineBreak = false;
  const shouldTreatEnterAsSend = () => {
    if (isCompactMessagesViewport()) return true;
    try {
      return (
        window.matchMedia('(pointer: coarse)').matches
        || window.matchMedia('(hover: none)').matches
      );
    } catch (err) {
      return false;
    }
  };
  const isEnterLikeEvent = (event) => {
    const key = String(event?.key || '').toLowerCase();
    return (
      key === 'enter'
      || key === 'return'
      || key === 'go'
      || key === 'send'
      || key === 'done'
      || key === 'search'
      || key === 'newline'
      || event?.code === 'Enter'
      || event?.code === 'NumpadEnter'
      || event?.keyCode === 13
      || event?.keyCode === 10
      || event?.which === 13
      || event?.which === 10
    );
  };
  const submitFromKeyboard = (event = null) => {
    if (event?.shiftKey) return;
    if (event) event.preventDefault();
    if (form) {
      if (typeof form.requestSubmit === 'function') {
        form.requestSubmit();
      } else {
        form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
      }
      return;
    }
    triggerSendMessage();
  };
  if (form) {
    form.addEventListener('submit', (event) => {
      event.preventDefault();
      triggerSendMessage();
    });
  }
  const sendButton = document.getElementById('sendButton');
  if (sendButton) {
    const sendFromButton = (event) => {
      event.preventDefault();
      triggerSendMessage();
    };
    // Keep this to a single click handler to avoid duplicate/ghost sends on mobile.
    sendButton.addEventListener('click', sendFromButton);
  }
  autoResizeComposer();
  syncComposerOffset();
  input.addEventListener('input', autoResizeComposer);
  input.addEventListener('input', updateComposerSecretState);
  input.addEventListener('input', () => {
    window.requestAnimationFrame(syncComposerOffset);
  });
  input.addEventListener('paste', (event) => {
    maybeCaptureSensitivePaste(event, { source: 'composer' });
  });
  input.addEventListener('input', () => {
    const value = String(input.value || '');
    if (!value.endsWith('\n')) {
      allowPendingLineBreak = false;
      return;
    }
    const mobileSendMode = shouldTreatEnterAsSend();
    if (!mobileSendMode && allowPendingLineBreak) {
      allowPendingLineBreak = false;
      return;
    }
    if (!mobileSendMode) return;
    const normalized = value.replace(/\n+$/g, '');
    input.value = normalized;
    autoResizeComposer();
    if (!normalized.trim()) return;
    submitFromKeyboard();
  });
  input.addEventListener('keydown', (event) => {
    if (!isEnterLikeEvent(event)) return;
    const mobileSendMode = shouldTreatEnterAsSend();
    if (!mobileSendMode && event.shiftKey) {
      allowPendingLineBreak = true;
      return;
    }
    if (event.isComposing && !isCompactMessagesViewport()) return;
    submitFromKeyboard(event);
  });
  // Some mobile keyboards do not fire keydown reliably for Enter.
  input.addEventListener('keyup', (event) => {
    if (!isEnterLikeEvent(event)) return;
    if (!shouldTreatEnterAsSend() && event.shiftKey) return;
    submitFromKeyboard(event);
  });
  input.addEventListener('beforeinput', (event) => {
    if (!shouldTreatEnterAsSend()) return;
    const inputType = String(event.inputType || '');
    if (inputType !== 'insertLineBreak' && inputType !== 'insertParagraph') return;
    submitFromKeyboard(event);
  });
  updateComposerSecretState();
}

function formatMessageSource(source) {
  const normalized = String(source || 'system').trim().toLowerCase();
  if (!normalized) return 'SYSTEM';
  if (normalized === 'user') return 'YOU';
  if (normalized === 'assistant') return 'ASSISTANT';
  if (normalized === 'bot') return 'BOT';
  return normalized.replace(/[_-]+/g, ' ').toUpperCase();
}

function formatMessageTime(value) {
  if (!value) return '';
  const dt = new Date(value);
  if (Number.isNaN(dt.getTime())) return '';
  return dt.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });
}

function formatSecretExpiryLabel(value) {
  if (!value) return 'expires later';
  const dt = new Date(value);
  if (Number.isNaN(dt.getTime())) return 'expires later';
  return `expires ${dt.toLocaleString([], {
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  })}`;
}

function getChannelConnector(channel) {
  if (!channel || !Number.isFinite(Number(channel.connector_id))) return null;
  return connectorsById.get(Number(channel.connector_id)) || null;
}

function normalizeOperatorMode(value = 'observe') {
  const raw = String(value || '').trim().toLowerCase().replace(/[\s-]+/g, '_');
  if (raw === 'manual') return 'take';
  if (raw === 'shared') return 'co_pilot';
  if (raw === 'auto' || raw === 'release') return 'observe';
  if (raw === 'copilot') return 'co_pilot';
  if (raw === 'take' || raw === 'co_pilot' || raw === 'observe') return raw;
  return 'observe';
}

function isConsoleChannel(channel) {
  const connector = getChannelConnector(channel);
  if (connector?.connector_type === 'tmux') return true;
  return /^console\s*-/i.test(String(channel?.name || '').trim());
}

function getChannelSessionName(channel) {
  const connector = getChannelConnector(channel);
  const config = connector?.config && typeof connector.config === 'object'
    ? connector.config
    : {};
  return String(config.session || '').trim();
}

function isSystemThreadChannel(channel) {
  if (!isConsoleChannel(channel)) return false;
  const sessionKey = normalizeKey(getChannelSessionName(channel));
  if (!sessionKey) return false;
  return SYSTEM_THREAD_SESSIONS.has(sessionKey);
}

function parseSessionFromTarget(target) {
  const text = String(target || '').trim();
  if (!text) return '';
  const idx = text.indexOf(':');
  if (idx <= 0) return '';
  return text.slice(0, idx).trim();
}

function getChannelTmuxSessionInfo(channel) {
  if (!channel || !isConsoleChannel(channel)) return null;
  const connector = getChannelConnector(channel);
  if (!connector || connector.connector_type !== 'tmux') return null;
  const config = connector?.config && typeof connector.config === 'object'
    ? connector.config
    : {};
  const explicitTarget = String(config.target || '').trim();
  const configuredSession = String(config.session || '').trim();
  const activeTargetSession = parseSessionFromTarget(activeConversationConsoleTarget);
  const selected = Number(selectedChannelId || 0);
  const sameChannelSelected = Number(channel.id || 0) === selected;
  const activeMatchesSession = (
    !configuredSession
    || !activeTargetSession
    || configuredSession === activeTargetSession
  );
  const canUseActiveTarget = sameChannelSelected && activeMatchesSession;
  const mappedTarget = String(
    (canUseActiveTarget ? activeConversationConsoleTarget : '')
    || resolveConsoleTargetForChannel(channel)
    || explicitTarget
    || '',
  ).trim();
  const session = String(
    configuredSession
    || parseSessionFromTarget(mappedTarget)
    || '',
  ).trim();
  if (!session) return null;
  return {
    connectorId: Number(connector.id),
    connectorName: String(connector.name || ''),
    session,
    target: mappedTarget,
    socketPath: String(config.socket_path || '').trim(),
    workingDir: String(config.working_dir || '').trim(),
    bootstrapCommand: String(config.session_bootstrap || '').trim(),
    locked: Boolean(config.locked),
    operatorMode: String(config.operator_mode || 'observe').trim().toLowerCase(),
    operatorNote: String(config.operator_note || '').trim(),
    webUrl: String(config.web_url || '').trim(),
  };
}

function getChannelOperatorState(channel) {
  if (!channel) return null;
  if (isConsoleChannel(channel)) {
    const info = getChannelTmuxSessionInfo(channel);
    if (!info) return null;
    const meta = findTmuxControlSession(info);
    return {
      targetType: 'session',
      connectorId: Number(info.connectorId || 0),
      channelId: Number(channel.id || 0),
      mode: normalizeOperatorMode(meta?.operator_mode || info.operatorMode || 'observe'),
      note: String(meta?.operator_note || info.operatorNote || '').trim(),
      updatedAt: String(meta?.operator_updated_at || '').trim(),
      sessionInfo: info,
      meta,
    };
  }

  const connector = getChannelConnector(channel);
  const config = connector?.config && typeof connector.config === 'object'
    ? connector.config
    : {};
  const channelStates = config?.channel_operator_modes && typeof config.channel_operator_modes === 'object'
    ? config.channel_operator_modes
    : {};
  const entry = channelStates[String(channel.id)] && typeof channelStates[String(channel.id)] === 'object'
    ? channelStates[String(channel.id)]
    : {};
  return {
    targetType: 'channel',
    connectorId: Number(connector?.id || 0),
    channelId: Number(channel.id || 0),
    mode: normalizeOperatorMode(channel?.operator_mode || entry.mode || entry.operator_mode || 'observe'),
    note: String(channel?.operator_note || entry.note || '').trim(),
    updatedAt: String(channel?.operator_updated_at || entry.updated_at || '').trim(),
    connectorName: String(connector?.name || ''),
  };
}

function setAgentControlsStatus(message = '', tone = 'muted') {
  const el = document.getElementById('streams-agent-controls-status');
  if (!el) return;
  el.textContent = String(message || '').trim();
  el.dataset.tone = tone || 'muted';
}

function setAgentControlsVisible(visible) {
  const panel = document.getElementById('streams-agent-controls');
  if (!panel) return;
  panel.classList.toggle('d-none', !visible);
}

function setAgentControlsBusy(busy) {
  agentControlBusy = Boolean(busy);
  [
    document.getElementById('streams-agent-take'),
    document.getElementById('streams-agent-copilot'),
    document.getElementById('streams-agent-release'),
    document.getElementById('streams-agent-refresh'),
    document.getElementById('streams-agent-lock-toggle'),
    document.getElementById('streams-agent-start-stop'),
    document.getElementById('streams-agent-restart'),
    document.getElementById('streams-agent-web-save'),
    document.getElementById('streams-agent-web-url'),
    document.getElementById('streams-agent-auth-browser'),
    document.getElementById('streams-agent-auth-device'),
  ].forEach((btn) => {
    if (!btn) return;
    btn.disabled = agentControlBusy;
  });
}

function findTmuxControlSession(info) {
  if (!info || !Array.isArray(tmuxControlSessionsCache) || !tmuxControlSessionsCache.length) {
    return null;
  }
  const sessionKey = normalizeKey(info.session);
  if (!sessionKey) return null;
  const byName = tmuxControlSessionsCache.find(
    (item) => normalizeKey(item?.session_name) === sessionKey,
  );
  if (byName) return byName;
  const byConnector = tmuxControlSessionsCache.find(
    (item) => Number(item?.connector_id || 0) === Number(info.connectorId || 0),
  );
  return byConnector || null;
}

function getChannelWebUrl(channel) {
  if (!channel) return '';
  if (isConsoleChannel(channel)) {
    const info = getChannelTmuxSessionInfo(channel);
    const meta = findTmuxControlSession(info);
    return String(
      meta?.web_url || info?.webUrl || getChannelEstateRoute(channel).primary || ''
    ).trim();
  }
  const connector = getChannelConnector(channel);
  const config = connector?.config && typeof connector.config === 'object'
    ? connector.config
    : {};
  return String(config.web_url || '').trim();
}

async function loadEstateServices(options = {}) {
  const { silent = false } = options;
  try {
    const resp = await fetch('/api/v1/estate/overview', { cache: 'no-store' });
    if (!resp.ok) {
      const body = await resp.json().catch(() => ({}));
      throw new Error(body.detail || 'Unable to load estate routes.');
    }
    const payload = await resp.json();
    const principals = Array.isArray(payload?.principals) ? payload.principals : [];
    estateServicesCache = principals.flatMap((principal) =>
      Array.isArray(principal?.services) ? principal.services : []
    );
  } catch (err) {
    estateServicesCache = [];
    if (!silent) {
      setStatus('channels-status', err.message || 'Unable to load estate routes.', 'warning');
    }
  } finally {
    const channelSearch = document.getElementById('channelSearch');
    if (channelSearch) {
      renderChannelsList(getVisibleChannels(), channelSearch.value);
    }
    updateAgentControls(getSelectedChannel());
    setActiveWebLink(getSelectedChannel());
  }
}

async function refreshTmuxControlSessions(options = {}) {
  const { silent = false } = options;
  try {
    const resp = await fetch('/api/v1/tmux/control/sessions', { cache: 'no-store' });
    if (!resp.ok) {
      const body = await resp.json().catch(() => ({}));
      throw new Error(body.detail || 'Unable to load tmux session controls.');
    }
    const payload = await resp.json();
    tmuxControlSessionsCache = Array.isArray(payload?.items) ? payload.items : [];
    if (!silent) {
      const count = Number(tmuxControlSessionsCache.length || 0);
      setAgentControlsStatus(`Loaded ${count} tmux session${count === 1 ? '' : 's'}.`, 'muted');
    }
  } catch (err) {
    if (!silent) {
      setAgentControlsStatus(err.message || 'Unable to load tmux sessions.', 'warn');
    }
  } finally {
    const channelSearch = document.getElementById('channelSearch');
    if (channelSearch) {
      renderChannelsList(getVisibleChannels(), channelSearch.value);
    }
    updateAgentControls(getSelectedChannel());
  }
}

function updateAgentControls(channel = null) {
  const panel = document.getElementById('streams-agent-controls');
  if (!panel) return;

  if (!channel) {
    setAgentControlsVisible(false);
    setActiveOperatorBadge(null);
    setActiveWebLink(null);
    return;
  }
  setAgentControlsVisible(true);

  const title = document.getElementById('streams-agent-controls-title');
  const label = document.getElementById('streams-agent-session-label');
  const lockBtn = document.getElementById('streams-agent-lock-toggle');
  const startStopBtn = document.getElementById('streams-agent-start-stop');
  const restartBtn = document.getElementById('streams-agent-restart');
  const takeBtn = document.getElementById('streams-agent-take');
  const coPilotBtn = document.getElementById('streams-agent-copilot');
  const releaseBtn = document.getElementById('streams-agent-release');
  const refreshBtn = document.getElementById('streams-agent-refresh');
  const webPanel = document.getElementById('streams-agent-web');
  const webInput = document.getElementById('streams-agent-web-url');
  const webSave = document.getElementById('streams-agent-web-save');
  const webOpen = document.getElementById('streams-agent-web-open');
  const authPanel = document.getElementById('streams-agent-auth');
  const authSummary = document.getElementById('streams-agent-auth-summary');
  const authBrowserBtn = document.getElementById('streams-agent-auth-browser');
  const authDeviceBtn = document.getElementById('streams-agent-auth-device');
  const authOpen = document.getElementById('streams-agent-auth-open');
  const authDevicePanel = document.getElementById('streams-agent-auth-device-panel');
  const authVerification = document.getElementById('streams-agent-auth-verification');
  const authCode = document.getElementById('streams-agent-auth-code');
  const operator = getChannelOperatorState(channel);

  if (!operator) {
    setAgentControlsVisible(false);
    setActiveOperatorBadge(channel);
    setActiveWebLink(channel);
    return;
  }

  const isSession = operator.targetType === 'session';
  const info = operator.sessionInfo || null;
  const meta = operator.meta || null;
  const operatorMode = normalizeOperatorMode(operator.mode || 'observe');
  const operatorNote = String(operator.note || '').trim();
  const locked = Boolean(meta?.locked ?? info?.locked);
  const running = Boolean(meta?.target);
  const webUrl = isSession ? getChannelWebUrl(channel) : '';
  const authRequired = Boolean(meta?.auth_required);
  const authMode = String(meta?.auth_mode || '').trim();
  const authSummaryText = String(meta?.auth_summary || '').trim();
  const authVerificationUrl = String(meta?.auth_verification_url || '').trim();
  const authDeviceCode = String(meta?.auth_device_code || '').trim();

  if (title) {
    title.textContent = isSession ? 'Session Controls' : 'Thread Controls';
  }
  setActiveOperatorBadge(channel);
  if (label) {
    label.textContent = isSession
      ? (info?.target ? `${info.session} · ${info.target}` : info?.session || 'session: --')
      : String(channel?.name || 'thread');
  }

  if (lockBtn) {
    lockBtn.textContent = locked ? 'Unlock' : 'Lock';
    lockBtn.dataset.nextLocked = locked ? '0' : '1';
    lockBtn.classList.toggle('d-none', !isSession);
  }
  if (startStopBtn) {
    startStopBtn.textContent = running ? 'Stop' : 'Continue';
    startStopBtn.dataset.action = running ? 'stop' : 'start';
    startStopBtn.disabled = agentControlBusy || (!running && locked);
    startStopBtn.classList.toggle('d-none', !isSession);
  }
  if (restartBtn) {
    restartBtn.disabled = agentControlBusy || locked;
    restartBtn.classList.toggle('d-none', !isSession);
  }
  if (refreshBtn) {
    refreshBtn.classList.toggle('d-none', !isSession);
  }
  if (webPanel) {
    webPanel.classList.toggle('d-none', !isSession);
  }
  if (webInput) {
    if (document.activeElement !== webInput) {
      webInput.value = webUrl;
    }
    webInput.disabled = agentControlBusy || !isSession;
  }
  if (webSave) {
    webSave.disabled = agentControlBusy || !isSession;
  }
  if (webOpen) {
    if (isSession && webUrl) {
      webOpen.href = webUrl;
      webOpen.title = webUrl;
      webOpen.classList.remove('d-none');
    } else {
      webOpen.removeAttribute('href');
      webOpen.title = '';
      webOpen.classList.add('d-none');
    }
  }
  if (authPanel) {
    const showAuth = Boolean(
      isSession && (authRequired || authMode || authVerificationUrl || authDeviceCode)
    );
    authPanel.classList.toggle('d-none', !showAuth);
  }
  if (authSummary) {
    authSummary.textContent = authSummaryText || 'Auth is healthy.';
  }
  if (authBrowserBtn) {
    authBrowserBtn.classList.toggle('d-none', !isSession);
    authBrowserBtn.disabled = agentControlBusy || !isSession;
    authBrowserBtn.textContent = authMode === 'browser_signin'
      ? 'Refresh Browser Sign-In'
      : 'Browser Sign-In';
  }
  if (authDeviceBtn) {
    authDeviceBtn.classList.toggle('d-none', !isSession);
    authDeviceBtn.disabled = agentControlBusy || !isSession;
    authDeviceBtn.textContent = authMode === 'device_code'
      ? 'Refresh Device Code'
      : authMode === 'needs_reauth'
        ? 'Start Device Code'
        : 'Device Code';
  }
  if (authOpen) {
    if (isSession && authVerificationUrl) {
      authOpen.href = authVerificationUrl;
      authOpen.classList.remove('d-none');
    } else {
      authOpen.removeAttribute('href');
      authOpen.classList.add('d-none');
    }
  }
  if (authDevicePanel) {
    authDevicePanel.classList.toggle(
      'd-none',
      !(isSession && authDeviceCode),
    );
  }
  if (authVerification) {
    authVerification.textContent = authVerificationUrl || '';
    if (authVerificationUrl) {
      authVerification.href = authVerificationUrl;
    } else {
      authVerification.removeAttribute('href');
    }
  }
  if (authCode) {
    authCode.textContent = authDeviceCode || '';
  }
  if (takeBtn) {
    takeBtn.disabled = agentControlBusy || operatorMode === 'take';
  }
  if (coPilotBtn) {
    coPilotBtn.disabled = agentControlBusy || operatorMode === 'co_pilot';
  }
  if (releaseBtn) {
    releaseBtn.disabled = agentControlBusy || operatorMode === 'observe';
  }

  const detailParts = [];
  if (isSession) {
    detailParts.push(running ? 'running' : 'stopped');
    detailParts.push(locked ? 'locked' : 'unlocked');
  }
  detailParts.push(
    operatorMode === 'take'
      ? 'manual'
      : operatorMode === 'co_pilot'
        ? 'shared'
        : 'auto',
  );
  if (meta?.protected) detailParts.push('protected');
  if (operatorNote) detailParts.push(operatorNote);
  if (meta?.pane_current_command) {
    detailParts.push(`cmd: ${String(meta.pane_current_command).slice(0, 24)}`);
  }
  if (webUrl) {
    detailParts.push(`app: ${formatWebUrlLabel(webUrl)}`);
  }
  if (authRequired) {
    detailParts.push(
      authMode === 'device_code'
        ? 'auth pending'
        : authMode === 'needs_reauth'
          ? 'needs reauth'
          : 'auth required',
    );
  }
  setAgentControlsStatus(
    detailParts.join(' · '),
    locked || operatorMode === 'take' ? 'warn' : operatorMode === 'co_pilot' ? 'ok' : 'muted',
  );
}

function normalizeRouteTarget(value = '') {
  return String(value || '')
    .trim()
    .toLowerCase()
    .replace(/^console\s*[-:]\s*/i, '')
    .replace(/^console\s+/i, '')
    .replace(/[^a-z0-9._:-]+/g, '');
}

function resolveChannelByRouteTarget(target = '') {
  const needle = normalizeRouteTarget(target);
  if (!needle || !Array.isArray(channelsCache) || !channelsCache.length) return null;

  const candidates = channelsCache.filter((channel) => {
    const name = normalizeRouteTarget(channel?.name || '');
    const session = normalizeRouteTarget(getChannelSessionName(channel) || '');
    if (!name && !session) return false;
    return (
      name === needle
      || session === needle
      || name.includes(needle)
      || session.includes(needle)
      || needle.includes(name)
      || needle.includes(session)
    );
  });
  if (!candidates.length) return null;

  candidates.sort((a, b) => {
    const aConsole = isConsoleChannel(a) ? 0 : 1;
    const bConsole = isConsoleChannel(b) ? 0 : 1;
    if (aConsole !== bConsole) return aConsole - bConsole;
    const aName = String(a?.name || '').toLowerCase();
    const bName = String(b?.name || '').toLowerCase();
    return aName.localeCompare(bName);
  });
  return candidates[0] || null;
}

function parseRouteCommand(rawText = '') {
  const text = String(rawText || '');
  if (!text.trim()) return null;

  let match = text.match(/^\/(?:to|route)\s+([^:\n]+?)\s*:\s*([\s\S]+)$/i);
  if (match) {
    return {
      target: String(match[1] || '').trim(),
      content: String(match[2] || '').trim(),
    };
  }

  match = text.match(/^@([A-Za-z0-9._:-]+)\s+([\s\S]+)$/);
  if (match) {
    return {
      target: String(match[1] || '').trim(),
      content: String(match[2] || '').trim(),
    };
  }
  return null;
}

async function runAgentControlAction(action) {
  const channel = getSelectedChannel();
  const actionName = String(action || '').trim().toLowerCase();
  if (!actionName) return;
  const operator = getChannelOperatorState(channel);
  if (!operator) {
    setAgentControlsStatus('No controllable target is mapped for this thread.', 'warn');
    return;
  }
  const isSession = operator.targetType === 'session';
  const info = operator.sessionInfo || null;
  const payload = isSession
    ? {
        connector_id: Number(info?.connectorId || 0),
        session: info?.session,
      }
    : null;
  if (isSession && info?.socketPath) {
    payload.socket_path = info.socketPath;
  }
  setAgentControlsBusy(true);
  setAgentControlsStatus(`Running ${actionName}...`, 'muted');

  try {
    if (actionName === 'manual' || actionName === 'shared' || actionName === 'auto') {
      const mode = actionName === 'manual'
        ? 'take'
        : actionName === 'shared'
          ? 'co_pilot'
          : 'observe';
      const note = actionName === 'manual'
        ? 'manual'
        : actionName === 'shared'
          ? 'shared'
          : '';
      if (isSession) {
        payload.mode = mode;
        payload.note = note;
        await requestTmuxControl('operator', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        });
      } else {
        const response = await requestChannelControl(operator.channelId, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ mode, note }),
        });
        applyChannelOperatorResponse(operator.channelId, response);
      }
      setAgentControlsStatus(
        mode === 'take'
          ? 'Manual mode enabled. Norman can watch and draft privately.'
          : mode === 'co_pilot'
            ? 'Shared mode enabled. You and Norman can both write here.'
            : 'Auto mode enabled. Norman may act here again.',
        mode === 'take' ? 'warn' : 'ok',
      );
    } else if (!isSession) {
      setAgentControlsStatus('This thread supports mode changes only.', 'warn');
    } else if (actionName === 'lock' || actionName === 'unlock') {
      payload.locked = actionName === 'lock';
      payload.stop_session = false;
      await requestTmuxControl('lock', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      setAgentControlsStatus(payload.locked ? 'Session locked.' : 'Session unlocked.', 'ok');
    } else if (actionName === 'start') {
      payload.target = info.target;
      payload.working_dir = info.workingDir;
      payload.bootstrap_command = info.bootstrapCommand;
      await requestTmuxControl('start', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      setAgentControlsStatus('Session started.', 'ok');
    } else if (actionName === 'stop') {
      await requestTmuxControl('stop', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      setAgentControlsStatus('Session stopped.', 'warn');
    } else if (actionName === 'restart') {
      payload.target = info.target;
      payload.working_dir = info.workingDir;
      payload.bootstrap_command = info.bootstrapCommand;
      payload.force_restart = true;
      await requestTmuxControl('restart', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      setAgentControlsStatus('Session restarted.', 'ok');
    }

    if (isSession) {
      await Promise.all([
        loadConsolePanes(),
        refreshTmuxControlSessions({ silent: true }),
      ]);
      await loadConsoleConversation(channel, { focusComposer: false, allowRecovery: true });
    }
  } catch (err) {
    setAgentControlsStatus(err.message || `Unable to ${actionName} target.`, 'err');
  } finally {
    setAgentControlsBusy(false);
    updateAgentControls(channel);
  }
}

function applySessionWebUrlResponse(channel, response) {
  if (!channel) return;
  const webUrl = String(response?.web_url || '').trim();
  const connector = getChannelConnector(channel);
  if (connector) {
    if (!connector.config || typeof connector.config !== 'object') {
      connector.config = {};
    }
    if (webUrl) {
      connector.config.web_url = webUrl;
    } else {
      delete connector.config.web_url;
    }
  }
  const info = getChannelTmuxSessionInfo(channel);
  const sessionKey = normalizeKey(info?.session);
  const connectorId = Number(info?.connectorId || 0);
  if (Array.isArray(tmuxControlSessionsCache)) {
    tmuxControlSessionsCache = tmuxControlSessionsCache.map((item) => {
      const sameSession = sessionKey && normalizeKey(item?.session_name) === sessionKey;
      const sameConnector = connectorId && Number(item?.connector_id || 0) === connectorId;
      if (!sameSession && !sameConnector) return item;
      return { ...item, web_url: webUrl };
    });
  }
}

function applySessionAuthResponse(channel, response = {}) {
  if (!channel) return;
  const info = getChannelTmuxSessionInfo(channel);
  const sessionKey = normalizeKey(info?.session);
  const connectorId = Number(info?.connectorId || 0);
  if (!Array.isArray(tmuxControlSessionsCache)) return;
  tmuxControlSessionsCache = tmuxControlSessionsCache.map((item) => {
    const sameSession = sessionKey && normalizeKey(item?.session_name) === sessionKey;
    const sameConnector = connectorId && Number(item?.connector_id || 0) === connectorId;
    if (!sameSession && !sameConnector) return item;
    return {
      ...item,
      status_available: true,
      status_message: String(response?.detail || item?.status_message || '').trim(),
      auth_required: Boolean(response?.auth_required),
      auth_mode: String(response?.auth_mode || '').trim(),
      auth_summary: String(response?.auth_summary || '').trim(),
      auth_verification_url: String(response?.auth_verification_url || '').trim(),
      auth_device_code: String(response?.auth_device_code || '').trim(),
    };
  });
}

async function saveActiveSessionWebUrl() {
  const channel = getSelectedChannel();
  const operator = getChannelOperatorState(channel);
  if (!channel || !operator || operator.targetType !== 'session') {
    setAgentControlsStatus('Select a session-backed thread first.', 'warn');
    return;
  }
  const input = document.getElementById('streams-agent-web-url');
  const rawWebUrl = String(input?.value || '').trim();
  const payload = {
    connector_id: Number(operator.sessionInfo?.connectorId || 0),
    session: operator.sessionInfo?.session,
    web_url: rawWebUrl,
  };
  setAgentControlsBusy(true);
  setAgentControlsStatus(rawWebUrl ? 'Saving web link...' : 'Clearing web link...', 'muted');
  try {
    const response = await requestTmuxControl('web-url', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    applySessionWebUrlResponse(channel, response);
    setActiveWebLink(channel);
    updateAgentControls(channel);
    renderChannelsList(getVisibleChannels(), document.getElementById('channelSearch').value);
    setAgentControlsStatus(
      response?.web_url
        ? `Web link saved: ${formatWebUrlLabel(response.web_url)}`
        : 'Web link cleared.',
      'ok',
    );
  } catch (err) {
    setAgentControlsStatus(err.message || 'Unable to save web link.', 'err');
  } finally {
    setAgentControlsBusy(false);
  }
}

async function startActiveSessionDeviceAuth() {
  const channel = getSelectedChannel();
  const operator = getChannelOperatorState(channel);
  if (!channel || !operator || operator.targetType !== 'session') {
    setAgentControlsStatus('Select a session-backed thread first.', 'warn');
    return;
  }
  const payload = {
    connector_id: Number(operator.sessionInfo?.connectorId || 0),
    session: operator.sessionInfo?.session,
  };
  setAgentControlsBusy(true);
  setAgentControlsStatus('Preparing device-code sign-in...', 'muted');
  try {
    const response = await requestTmuxControl('auth-device', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    applySessionAuthResponse(channel, response);
    await Promise.all([
      loadConsolePanes(),
      refreshTmuxControlSessions({ silent: true }),
    ]);
    await loadConsoleConversation(channel, { focusComposer: false, allowRecovery: true });
    updateAgentControls(channel);
    setAgentControlsStatus(
      response?.auth_device_code
        ? `Device code ready: ${response.auth_device_code}`
        : String(response?.detail || 'Auth step started.'),
      'warn',
    );
  } catch (err) {
    setAgentControlsStatus(err.message || 'Unable to prepare device-code sign-in.', 'err');
  } finally {
    setAgentControlsBusy(false);
  }
}

async function startActiveSessionBrowserAuth() {
  const channel = getSelectedChannel();
  const operator = getChannelOperatorState(channel);
  if (!channel || !operator || operator.targetType !== 'session') {
    setAgentControlsStatus('Select a session-backed thread first.', 'warn');
    return;
  }
  const payload = {
    connector_id: Number(operator.sessionInfo?.connectorId || 0),
    session: operator.sessionInfo?.session,
  };
  setAgentControlsBusy(true);
  setAgentControlsStatus('Preparing browser sign-in...', 'muted');
  try {
    const response = await requestTmuxControl('auth-browser', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    applySessionAuthResponse(channel, response);
    await Promise.all([
      loadConsolePanes(),
      refreshTmuxControlSessions({ silent: true }),
    ]);
    await loadConsoleConversation(channel, { focusComposer: false, allowRecovery: true });
    updateAgentControls(channel);
    setAgentControlsStatus(
      response?.auth_verification_url
        ? 'Browser sign-in ready.'
        : String(response?.detail || 'Auth step started.'),
      'warn',
    );
  } catch (err) {
    setAgentControlsStatus(err.message || 'Unable to prepare browser sign-in.', 'err');
  } finally {
    setAgentControlsBusy(false);
  }
}

function getVisibleChannels() {
  if (!Array.isArray(channelsCache) || !channelsCache.length) return [];
  if (!streamsThreadMode) {
    return [...channelsCache];
  }
  const threads = channelsCache.filter((channel) =>
    isConsoleChannel(channel) && !isSystemThreadChannel(channel)
  );
  if (threads.length) return threads;
  const fallbackThreads = channelsCache.filter((channel) => isConsoleChannel(channel));
  if (fallbackThreads.length) return fallbackThreads;
  return [...channelsCache];
}

function getThreadRuntimeState(channel) {
  const operator = getChannelOperatorState(channel);
  if (!operator) return null;
  const operatorMode = normalizeOperatorMode(operator.mode || 'observe');
  if (operatorMode === 'take') {
    return { label: 'manual', tone: 'warn' };
  }
  if (operatorMode === 'co_pilot') {
    return { label: 'shared', tone: 'ok' };
  }
  if (!isConsoleChannel(channel)) {
    return null;
  }
  const estateRoute = getChannelEstateRoute(channel);
  const info = operator.sessionInfo || getChannelTmuxSessionInfo(channel);
  if (!info?.session) {
    return estateRoute.primary
      ? { label: 'linked', tone: 'info' }
      : { label: 'unmapped', tone: 'warn' };
  }
  const meta = operator.meta || findTmuxControlSession(info);
  const locked = Boolean(meta?.locked ?? info.locked);
  if (locked) {
    return { label: 'locked', tone: 'warn' };
  }
  const running = Boolean(meta?.target);
  if (running) {
    return { label: 'live', tone: 'ok' };
  }
  if (estateRoute.primary) {
    return { label: 'linked', tone: 'info' };
  }
  return { label: 'idle', tone: 'muted' };
}

function setComposeHint(text = DEFAULT_COMPOSE_HINT) {
  const hint = document.getElementById('streams-compose-hint');
  if (!hint) return;
  hint.textContent = text;
}

function getPreferredTmuxConnectorId(channel = null) {
  const candidate = getChannelConnector(channel || getSelectedChannel());
  if (candidate?.connector_type === 'tmux' && Number.isFinite(Number(candidate.id))) {
    return Number(candidate.id);
  }
  const tmuxConnectors = Array.from(connectorsById.values())
    .filter((connector) =>
      connector?.connector_type === 'tmux' && Number.isFinite(Number(connector.id))
    );
  if (!tmuxConnectors.length) return 0;
  const normanFirst = tmuxConnectors.find((connector) =>
    /norman/i.test(String(connector.name || ''))
  );
  if (normanFirst) return Number(normanFirst.id);
  tmuxConnectors.sort((a, b) => Number(a.id) - Number(b.id));
  return Number(tmuxConnectors[0].id);
}

async function requestTmuxSend(payload) {
  const urls = ['/api/v1/tmux/send', '/api/tmux/send'];
  let sawNotFound = false;
  for (const url of urls) {
    const controller = new AbortController();
    const timeoutHandle = window.setTimeout(() => controller.abort(), TMUX_SEND_TIMEOUT_MS);
    let resp;
    try {
      resp = await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
        signal: controller.signal,
      });
    } catch (err) {
      if (err?.name === 'AbortError') {
        throw new Error('Timed out sending to tmux. Retry and confirm the pane is healthy.');
      }
      throw err;
    } finally {
      window.clearTimeout(timeoutHandle);
    }

    const body = await resp.json().catch(() => ({}));
    if (resp.ok) {
      return body;
    }
    if (resp.status === 404) {
      sawNotFound = true;
      continue;
    }
    throw new Error(body.detail || body.reason || 'Unable to send command to tmux.');
  }
  if (sawNotFound) {
    throw new Error(
      'Tmux send endpoint is unavailable. Restart backend or switch to a non-console stream.',
    );
  }
  throw new Error('Unable to send command to tmux.');
}

async function fetchWithTimeout(url, options = {}, timeoutMs = CHANNEL_SEND_TIMEOUT_MS) {
  const controller = new AbortController();
  const timeoutHandle = window.setTimeout(() => controller.abort(), timeoutMs);
  const merged = { ...options, signal: controller.signal };
  try {
    return await fetch(url, merged);
  } catch (err) {
    if (err?.name === 'AbortError') {
      throw new Error('Request timed out. Retry in a moment.');
    }
    throw err;
  } finally {
    window.clearTimeout(timeoutHandle);
  }
}

function setTmuxProfileButtonsBusy(busy, label = '') {
  [
    document.getElementById('streams-profile-save'),
    document.getElementById('streams-profile-load'),
    document.getElementById('streams-profile-save-mobile'),
    document.getElementById('streams-profile-load-mobile'),
    document.getElementById('streams-profile-refresh'),
    document.getElementById('streams-profile-sync'),
    document.getElementById('streams-profile-rename'),
    document.getElementById('streams-profile-delete'),
  ].forEach((button) => {
    if (!button) return;
    if (!button.dataset.defaultLabel) {
      button.dataset.defaultLabel = button.textContent || '';
    }
    button.disabled = Boolean(busy);
    button.textContent = busy && label ? label : button.dataset.defaultLabel;
  });
}

async function requestTmuxControl(path, options = {}, timeoutMs = TMUX_SEND_TIMEOUT_MS) {
  const urls = [`/api/v1/tmux/control/${path}`, `/api/tmux/control/${path}`];
  let sawNotFound = false;
  for (const url of urls) {
    const resp = await fetchWithTimeout(url, options, timeoutMs);
    const body = await resp.json().catch(() => ({}));
    if (resp.ok) return body;
    if (resp.status === 404) {
      sawNotFound = true;
      continue;
    }
    throw new Error(body.detail || body.reason || 'Tmux control request failed.');
  }
  if (sawNotFound) {
    throw new Error('Tmux control API is unavailable. Restart backend and retry.');
  }
  throw new Error('Tmux control request failed.');
}

async function requestChannelControl(channelId, options = {}, timeoutMs = CHANNEL_SEND_TIMEOUT_MS) {
  const urls = [
    `/api/v1/channels/${channelId}/operator`,
    `/api/channels/${channelId}/operator`,
  ];
  let sawNotFound = false;
  for (const url of urls) {
    const resp = await fetchWithTimeout(url, options, timeoutMs);
    const body = await resp.json().catch(() => ({}));
    if (resp.ok) return body;
    if (resp.status === 404) {
      sawNotFound = true;
      continue;
    }
    throw new Error(body.detail || body.reason || 'Thread control request failed.');
  }
  if (sawNotFound) {
    throw new Error('Thread control API is unavailable. Restart backend and retry.');
  }
  throw new Error('Thread control request failed.');
}

function applyChannelOperatorResponse(channelId, payload = {}) {
  const numericChannelId = Number(channelId || payload.channel_id || 0);
  if (!numericChannelId) return;
  const mode = normalizeOperatorMode(payload.operator_mode || payload.mode || 'observe');
  const note = String(payload.operator_note || payload.note || '').trim();
  const updatedAt = String(payload.operator_updated_at || payload.updated_at || '').trim();

  channelsCache = channelsCache.map((channel) => (
    Number(channel?.id || 0) === numericChannelId
      ? {
          ...channel,
          operator_mode: mode,
          operator_note: note,
          operator_updated_at: updatedAt,
        }
      : channel
  ));

  const connectorId = Number(payload.connector_id || 0);
  if (!connectorId) return;
  const connector = connectorsById.get(connectorId);
  if (!connector) return;
  const config = connector?.config && typeof connector.config === 'object'
    ? { ...connector.config }
    : {};
  const states = config.channel_operator_modes && typeof config.channel_operator_modes === 'object'
    ? { ...config.channel_operator_modes }
    : {};
  states[String(numericChannelId)] = {
    mode,
    note,
    updated_at: updatedAt,
  };
  config.channel_operator_modes = states;
  connectorsById.set(connectorId, { ...connector, config });
}

async function tryAutoResumeConsoleChannel(channel, options = {}) {
  const {
    force = false,
    feedback = true,
    reason = 'auto_resume',
  } = options;
  if (!channel || !isConsoleChannel(channel)) {
    return { status: 'skip', reason: 'not_console' };
  }

  const info = getChannelTmuxSessionInfo(channel);
  if (!info?.session || !Number.isFinite(Number(info.connectorId))) {
    return { status: 'skip', reason: 'missing_mapping' };
  }

  const key = Number(channel.id || 0) || Number(info.connectorId || 0);
  const now = Date.now();
  const lastAttempt = Number(tmuxAutoResumeAttempts.get(key) || 0);
  if (!force && lastAttempt && (now - lastAttempt) < TMUX_AUTO_RESUME_COOLDOWN_MS) {
    return { status: 'skip', reason: 'cooldown' };
  }
  tmuxAutoResumeAttempts.set(key, now);

  const payload = {
    connector_id: Number(info.connectorId),
    session: info.session,
  };
  if (info.socketPath) payload.socket_path = info.socketPath;
  if (info.target) payload.target = info.target;
  if (info.workingDir) payload.working_dir = info.workingDir;
  if (info.bootstrapCommand) payload.bootstrap_command = info.bootstrapCommand;

  if (feedback) {
    setComposeFeedback(`Resuming ${info.session}`, 'pending');
  }

  try {
    const result = await requestTmuxControl(
      'start',
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      },
      TMUX_SEND_TIMEOUT_MS,
    );
    await Promise.all([
      loadConsolePanes(),
      refreshTmuxControlSessions({ silent: true }),
    ]);

    const started = Boolean(result?.started_session || result?.launched_command);
    if (feedback) {
      setComposeFeedback(
        started
          ? `Session resumed: ${info.session}`
          : `Session ready: ${info.session}`,
        'ok',
      );
    }
    return {
      status: started ? 'started' : 'ready',
      target: String(result?.target || ''),
      detail: String(result?.detail || ''),
      session: info.session,
      reason,
    };
  } catch (err) {
    const message = String(err?.message || 'Unable to resume session.').trim();
    const lowered = message.toLowerCase();
    const locked = lowered.includes('locked');
    if (feedback) {
      setComposeFeedback(message, locked ? 'warn' : 'err');
    }
    return {
      status: locked ? 'locked' : 'error',
      message,
      session: info.session,
      reason,
    };
  }
}

async function listTmuxProfiles() {
  const payload = await requestTmuxControl('profiles', {
    method: 'GET',
    headers: { Accept: 'application/json' },
  });
  const items = Array.isArray(payload?.items) ? payload.items : [];
  return items
    .map((item) => String(item?.name || '').trim())
    .filter((name) => name);
}

function setStreamsProfilePanelOpen(open) {
  streamsProfilePanelOpen = Boolean(open);
  const panel = document.getElementById('streams-profile-panel');
  if (panel) {
    panel.classList.toggle('d-none', !streamsProfilePanelOpen);
  }
  [
    document.getElementById('streams-profile-panel-toggle'),
    document.getElementById('streams-profile-panel-toggle-mobile'),
  ].forEach((button) => {
    if (!button) return;
    button.setAttribute('aria-expanded', streamsProfilePanelOpen ? 'true' : 'false');
    button.textContent = streamsProfilePanelOpen ? 'Hide Layouts' : 'Layouts';
  });
}

function getProfileSelectElement() {
  return document.getElementById('streams-profile-select');
}

function getProfileNameInputElement() {
  return document.getElementById('streams-profile-name');
}

function renderTmuxProfileOptions(preferredName = '') {
  const select = getProfileSelectElement();
  const input = getProfileNameInputElement();
  if (!select) return;

  const names = Array.isArray(tmuxProfilesCache) ? tmuxProfilesCache : [];
  select.innerHTML = '';
  if (!names.length) {
    const option = document.createElement('option');
    option.value = '';
    option.textContent = 'No layouts yet';
    option.selected = true;
    select.appendChild(option);
    select.disabled = true;
    if (input && !input.value.trim()) {
      input.value = readStoredTmuxProfileName() || STREAMS_TMUX_PROFILE_DEFAULT;
    }
    return;
  }

  select.disabled = false;
  names.forEach((name) => {
    const option = document.createElement('option');
    option.value = name;
    option.textContent = name;
    select.appendChild(option);
  });

  const stored = readStoredTmuxProfileName();
  const nextName = [preferredName, stored, STREAMS_TMUX_PROFILE_DEFAULT, names[0]]
    .map((item) => String(item || '').trim())
    .find((item) => item && names.includes(item)) || names[0];
  select.value = nextName;
  writeStoredTmuxProfileName(nextName);
  if (input) {
    input.value = nextName;
  }
}

async function refreshTmuxProfiles(preferredName = '') {
  tmuxProfilesCache = await listTmuxProfiles();
  renderTmuxProfileOptions(preferredName);
  return tmuxProfilesCache;
}

function renderTmuxAutoHuntButton() {
  const button = document.getElementById('streams-hunt-toggle');
  if (!button) return;
  button.setAttribute('aria-pressed', tmuxAutoHuntEnabled ? 'true' : 'false');
  button.textContent = tmuxAutoHuntEnabled ? 'Auto Hunt On' : 'Auto Hunt Off';
  button.classList.toggle('btn-outline-secondary', !tmuxAutoHuntEnabled);
  button.classList.toggle('btn-outline-success', tmuxAutoHuntEnabled);
}

async function saveRunningTmuxSnapshot(options = {}) {
  const {
    profileName = STREAMS_TMUX_RUNNING_PROFILE,
    includeProtected = true,
    silent = true,
  } = options;
  const payload = await requestTmuxControl(
    'profiles/save',
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        name: profileName,
        running_only: true,
        include_protected: Boolean(includeProtected),
      }),
    },
    TMUX_SEND_TIMEOUT_MS,
  );
  if (!tmuxProfilesCache.includes(profileName)) {
    tmuxProfilesCache.push(profileName);
    tmuxProfilesCache.sort((a, b) => a.localeCompare(b));
    renderTmuxProfileOptions(readStoredTmuxProfileName());
  }
  if (!silent) {
    setComposeFeedback(`Saved live snapshot "${profileName}".`, 'ok');
  }
  return payload;
}

async function huntRunningTmuxSessions(options = {}) {
  const {
    silent = true,
    includeProtected = true,
    saveSnapshot = true,
    refreshAll = false,
  } = options;
  if (tmuxAutoHuntInFlight) {
    return { status: 'busy' };
  }

  tmuxAutoHuntInFlight = true;
  const beforeSignature = tmuxControlSessionSignature();
  try {
    const adoptPayload = await requestTmuxControl(
      'adopt_all',
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          include_protected: Boolean(includeProtected),
          create_channels: true,
          create_bots: false,
        }),
      },
      TMUX_SEND_TIMEOUT_MS * 2,
    );

    let snapshotPayload = null;
    if (saveSnapshot) {
      snapshotPayload = await saveRunningTmuxSnapshot({
        includeProtected,
        silent: true,
      });
    }

    await refreshTmuxControlSessions({ silent: true });
    const afterSignature = tmuxControlSessionSignature();
    const shouldReload = refreshAll || !beforeSignature || beforeSignature !== afterSignature;
    if (shouldReload) {
      await Promise.all([
        loadConnectors(),
        loadChannels(),
        loadBots(),
        loadConsolePanes(),
        refreshTmuxProfiles(readStoredTmuxProfileName()).catch(() => {}),
      ]);
    }

    if (!silent) {
      const sessionCount = Number(adoptPayload?.adopted || 0);
      const snapshotCount = Number(snapshotPayload?.sessions || sessionCount || 0);
      setStatus(
        'channels-status',
        `Hunted ${sessionCount} running tmux session${sessionCount === 1 ? '' : 's'} and saved "${STREAMS_TMUX_RUNNING_PROFILE}" (${snapshotCount}).`,
        'success',
      );
      setComposeFeedback('Running tmux sessions synced.', 'ok');
    }
    return {
      status: 'ok',
      adopted: Number(adoptPayload?.adopted || 0),
      saved: Number(snapshotPayload?.sessions || 0),
      changed: shouldReload,
    };
  } catch (err) {
    if (!silent) {
      const message = err?.message || 'Unable to hunt tmux sessions.';
      setStatus('channels-status', message, 'danger');
      setComposeFeedback(message, 'err');
    }
    throw err;
  } finally {
    tmuxAutoHuntInFlight = false;
  }
}

function stopTmuxAutoHuntPolling() {
  if (!tmuxAutoHuntTimer) return;
  window.clearInterval(tmuxAutoHuntTimer);
  tmuxAutoHuntTimer = null;
}

function startTmuxAutoHuntPolling() {
  stopTmuxAutoHuntPolling();
  if (!tmuxAutoHuntEnabled) return;
  tmuxAutoHuntTimer = window.setInterval(() => {
    if (document.hidden) return;
    huntRunningTmuxSessions({ silent: true }).catch(() => {});
  }, TMUX_AUTO_HUNT_INTERVAL_MS);
}

function setTmuxAutoHuntEnabled(enabled, options = {}) {
  const { persist = true, announce = false, immediate = false } = options;
  tmuxAutoHuntEnabled = Boolean(enabled);
  if (persist) {
    writeStoredTmuxAutoHuntEnabled(tmuxAutoHuntEnabled);
  }
  renderTmuxAutoHuntButton();
  startTmuxAutoHuntPolling();
  if (announce) {
    setComposeFeedback(
      tmuxAutoHuntEnabled
        ? 'Auto hunt enabled. Norman will adopt and snapshot running tmux sessions.'
        : 'Auto hunt paused.',
      tmuxAutoHuntEnabled ? 'ok' : 'warn',
    );
  }
  if (tmuxAutoHuntEnabled && immediate) {
    huntRunningTmuxSessions({ silent: true, refreshAll: true }).catch(() => {});
  }
}

function resolveProfileNameForSave() {
  const input = getProfileNameInputElement();
  const select = getProfileSelectElement();
  const fromInput = String(input?.value || '').trim();
  const fromSelect = String(select?.value || '').trim();
  const stored = readStoredTmuxProfileName();
  const candidate = fromInput || fromSelect || stored || STREAMS_TMUX_PROFILE_DEFAULT;
  const normalized = normalizeTmuxProfileName(candidate);
  if (input) input.value = normalized;
  return normalized;
}

function resolveProfileNameForLoad() {
  const select = getProfileSelectElement();
  const input = getProfileNameInputElement();
  const fromSelect = String(select?.value || '').trim();
  const fromInput = String(input?.value || '').trim();
  const stored = readStoredTmuxProfileName();
  const candidate = fromSelect || fromInput || stored || '';
  if (!candidate) {
    throw new Error('No saved layouts yet. Tap Save first.');
  }
  const normalized = normalizeTmuxProfileName(candidate);
  if (tmuxProfilesCache.length && !tmuxProfilesCache.includes(normalized)) {
    throw new Error(`Layout "${normalized}" does not exist.`);
  }
  if (input) input.value = normalized;
  return normalized;
}

async function resolveLoadProfileName() {
  const names = await refreshTmuxProfiles();
  if (!names.length) {
    throw new Error('No saved layouts yet. Tap Save first.');
  }

  const stored = readStoredTmuxProfileName();
  if (stored && names.includes(stored)) {
    renderTmuxProfileOptions(stored);
    return stored;
  }
  if (names.includes(STREAMS_TMUX_PROFILE_DEFAULT)) {
    writeStoredTmuxProfileName(STREAMS_TMUX_PROFILE_DEFAULT);
    renderTmuxProfileOptions(STREAMS_TMUX_PROFILE_DEFAULT);
    return STREAMS_TMUX_PROFILE_DEFAULT;
  }
  writeStoredTmuxProfileName(names[0]);
  renderTmuxProfileOptions(names[0]);
  return names[0];
}

async function saveCurrentTmuxLayout(event = null) {
  try {
    const profileName = resolveProfileNameForSave();

    setTmuxProfileButtonsBusy(true, 'Saving…');
    setComposeFeedback(`Saving layout "${profileName}"`, 'pending');
    const payload = await requestTmuxControl(
      'profiles/save',
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: profileName }),
      },
      TMUX_SEND_TIMEOUT_MS,
    );
    writeStoredTmuxProfileName(profileName);
    if (!tmuxProfilesCache.includes(profileName)) {
      tmuxProfilesCache.push(profileName);
      tmuxProfilesCache.sort((a, b) => a.localeCompare(b));
    }
    renderTmuxProfileOptions(profileName);
    setStatus(
      'channels-status',
      `Saved layout "${profileName}" (${Number(payload?.sessions || 0)} sessions).`,
      'success',
    );
    setComposeFeedback(`Saved layout "${profileName}".`, 'ok');
    setTmuxProfileButtonsBusy(false);
  } catch (err) {
    setStatus('channels-status', err.message || 'Unable to save layout.', 'danger');
    setComposeFeedback(err.message || 'Unable to save layout.', 'err');
    setTmuxProfileButtonsBusy(false);
  }
}

async function loadSavedTmuxLayout(event = null) {
  try {
    await resolveLoadProfileName();
    const profileName = resolveProfileNameForLoad();

    setTmuxProfileButtonsBusy(true, 'Loading…');
    setComposeFeedback(`Loading layout "${profileName}"`, 'pending');
    const payload = await requestTmuxControl(
      'profiles/load',
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name: profileName,
          start_sessions: true,
          force_restart: false,
        }),
      },
      TMUX_SEND_TIMEOUT_MS * 2,
    );
    writeStoredTmuxProfileName(profileName);
    renderTmuxProfileOptions(profileName);
    setStatus(
      'channels-status',
      `Loaded layout "${profileName}" (${Number(payload?.applied || 0)}/${Number(payload?.sessions || 0)} sessions).`,
      'success',
    );
    setComposeFeedback(`Loaded layout "${profileName}".`, 'ok');
    await loadConnectors();
    await loadChannels();
    await loadConsolePanes();
    setTmuxProfileButtonsBusy(false);
  } catch (err) {
    setStatus('channels-status', err.message || 'Unable to load layout.', 'danger');
    setComposeFeedback(err.message || 'Unable to load layout.', 'err');
    setTmuxProfileButtonsBusy(false);
  }
}

async function syncTmuxSessionsFromProfile(event = null) {
  try {
    setTmuxProfileButtonsBusy(true, 'Syncing…');
    let loadSummary = 'No saved layout yet';

    try {
      await resolveLoadProfileName();
      const profileName = resolveProfileNameForLoad();
      const payload = await requestTmuxControl(
        'profiles/load',
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            name: profileName,
            start_sessions: true,
            force_restart: false,
          }),
        },
        TMUX_SEND_TIMEOUT_MS * 2,
      );
      writeStoredTmuxProfileName(profileName);
      renderTmuxProfileOptions(profileName);
      loadSummary = `Loaded "${profileName}" (${Number(payload?.applied || 0)}/${Number(payload?.sessions || 0)})`;
    } catch (err) {
      const text = String(err?.message || '').toLowerCase();
      if (!text.includes('no saved layouts yet')) {
        throw err;
      }
    }

    const huntPayload = await huntRunningTmuxSessions({
      silent: true,
      includeProtected: true,
      saveSnapshot: true,
      refreshAll: true,
    });

    setStatus(
      'channels-status',
      `${loadSummary}. Synced running tmux sessions (${Number(huntPayload?.adopted || 0)} hunted, saved "${STREAMS_TMUX_RUNNING_PROFILE}").`,
      'success',
    );
    setComposeFeedback('Running tmux sessions synced and saved.', 'ok');
  } catch (err) {
    setStatus('channels-status', err.message || 'Unable to sync tmux sessions.', 'danger');
    setComposeFeedback(err.message || 'Unable to sync tmux sessions.', 'err');
  } finally {
    setTmuxProfileButtonsBusy(false);
  }
}

async function renameCurrentTmuxLayout(event = null) {
  try {
    await resolveLoadProfileName();
    const fromName = resolveProfileNameForLoad();
    const toName = resolveProfileNameForSave();
    if (fromName === toName) {
      setStatus('channels-status', 'Enter a new layout name to rename.', 'info');
      setComposeFeedback('Enter a different layout name first.', 'muted');
      return;
    }

    setTmuxProfileButtonsBusy(true, 'Renaming…');
    setComposeFeedback(`Renaming "${fromName}" -> "${toName}"`, 'pending');
    const payload = await requestTmuxControl(
      'profiles/rename',
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          from_name: fromName,
          to_name: toName,
          overwrite: Boolean(event?.shiftKey),
        }),
      },
      TMUX_SEND_TIMEOUT_MS,
    );
    tmuxProfilesCache = tmuxProfilesCache
      .filter((name) => name !== fromName);
    if (!tmuxProfilesCache.includes(toName)) {
      tmuxProfilesCache.push(toName);
    }
    tmuxProfilesCache.sort((a, b) => a.localeCompare(b));
    writeStoredTmuxProfileName(toName);
    renderTmuxProfileOptions(toName);
    setStatus(
      'channels-status',
      `Renamed layout "${fromName}" -> "${toName}" (${Number(payload?.sessions || 0)} sessions).`,
      'success',
    );
    setComposeFeedback(`Renamed to "${toName}".`, 'ok');
  } catch (err) {
    setStatus('channels-status', err.message || 'Unable to rename layout.', 'danger');
    setComposeFeedback(err.message || 'Unable to rename layout.', 'err');
  } finally {
    setTmuxProfileButtonsBusy(false);
  }
}

async function deleteCurrentTmuxLayout() {
  try {
    await resolveLoadProfileName();
    const profileName = resolveProfileNameForLoad();
    const confirmed = window.confirm(`Delete layout "${profileName}"?`);
    if (!confirmed) return;

    setTmuxProfileButtonsBusy(true, 'Deleting…');
    setComposeFeedback(`Deleting "${profileName}"`, 'pending');
    const payload = await requestTmuxControl(
      `profiles/${encodeURIComponent(profileName)}`,
      {
        method: 'DELETE',
        headers: { Accept: 'application/json' },
      },
      TMUX_SEND_TIMEOUT_MS,
    );
    tmuxProfilesCache = tmuxProfilesCache.filter((name) => name !== profileName);
    const nextName = tmuxProfilesCache[0] || '';
    writeStoredTmuxProfileName(nextName);
    renderTmuxProfileOptions(nextName);
    setStatus(
      'channels-status',
      `Deleted layout "${profileName}" (${Number(payload?.sessions || 0)} sessions).`,
      'success',
    );
    setComposeFeedback(`Deleted "${profileName}".`, 'ok');
  } catch (err) {
    setStatus('channels-status', err.message || 'Unable to delete layout.', 'danger');
    setComposeFeedback(err.message || 'Unable to delete layout.', 'err');
  } finally {
    setTmuxProfileButtonsBusy(false);
  }
}

function initTmuxProfileControls() {
  const select = getProfileSelectElement();
  const input = getProfileNameInputElement();
  tmuxAutoHuntEnabled = readStoredTmuxAutoHuntEnabled();
  renderTmuxAutoHuntButton();

  [
    document.getElementById('streams-profile-panel-toggle'),
    document.getElementById('streams-profile-panel-toggle-mobile'),
  ].forEach((button) => {
    if (!button) return;
    button.addEventListener('click', (event) => {
      event.preventDefault();
      setStreamsProfilePanelOpen(!streamsProfilePanelOpen);
      if (streamsProfilePanelOpen) {
        refreshTmuxProfiles(input?.value || '').catch(() => {});
      }
    });
  });

  const closeBtn = document.getElementById('streams-profile-close');
  if (closeBtn) {
    closeBtn.addEventListener('click', (event) => {
      event.preventDefault();
      setStreamsProfilePanelOpen(false);
    });
  }

  const refreshBtn = document.getElementById('streams-profile-refresh');
  if (refreshBtn) {
    refreshBtn.addEventListener('click', async (event) => {
      event.preventDefault();
      setTmuxProfileButtonsBusy(true, 'Loading…');
      try {
        const names = await refreshTmuxProfiles(input?.value || '');
        setStatus('channels-status', `Loaded ${names.length} layout${names.length === 1 ? '' : 's'}.`, 'info');
      } catch (err) {
        setStatus('channels-status', err.message || 'Unable to load layouts.', 'warning');
      } finally {
        setTmuxProfileButtonsBusy(false);
      }
    });
  }

  const syncBtn = document.getElementById('streams-profile-sync');
  if (syncBtn) {
    syncBtn.addEventListener('click', (event) => {
      event.preventDefault();
      syncTmuxSessionsFromProfile(event);
    });
  }

  const huntBtn = document.getElementById('streams-hunt-toggle');
  if (huntBtn) {
    huntBtn.addEventListener('click', (event) => {
      event.preventDefault();
      setTmuxAutoHuntEnabled(!tmuxAutoHuntEnabled, {
        persist: true,
        announce: true,
        immediate: !tmuxAutoHuntEnabled,
      });
    });
  }

  const renameBtn = document.getElementById('streams-profile-rename');
  if (renameBtn) {
    renameBtn.addEventListener('click', (event) => {
      event.preventDefault();
      renameCurrentTmuxLayout(event);
    });
  }

  const deleteBtn = document.getElementById('streams-profile-delete');
  if (deleteBtn) {
    deleteBtn.addEventListener('click', (event) => {
      event.preventDefault();
      deleteCurrentTmuxLayout();
    });
  }

  if (select && input) {
    select.addEventListener('change', () => {
      const value = String(select.value || '').trim();
      if (!value) return;
      input.value = value;
      writeStoredTmuxProfileName(value);
    });
  }
}

async function fetchTmuxCaptureText(target, lines = 120, socketPath = '') {
  const params = new URLSearchParams({
    target: String(target || '').trim(),
    lines: String(lines || 120),
  });
  if (socketPath) {
    params.set('socket_path', socketPath);
  }
  const resp = await fetch(`/api/v1/tmux/capture?${params.toString()}`, { cache: 'no-store' });
  if (!resp.ok) {
    const payload = await resp.json().catch(() => ({}));
    throw new Error(payload.detail || 'Unable to capture pane');
  }
  const payload = await resp.json();
  return payload.text || '[empty pane output]';
}

function setConversationConsoleTarget(target, socketPath = '') {
  activeConversationConsoleTarget = String(target || '').trim();
  activeConversationConsoleSocketPath = String(socketPath || '').trim();
  selectedConsoleTarget = activeConversationConsoleTarget;
  const consoleSelect = document.getElementById('messages-console-select');
  if (consoleSelect && activeConversationConsoleTarget) {
    if (consolePanesCache.some((pane) => pane.target === activeConversationConsoleTarget)) {
      consoleSelect.value = activeConversationConsoleTarget;
    }
  }
}

function syncComposerOffset() {
  const page = document.querySelector('.messages-page');
  const composer = document.querySelector('.messages-page .input-message-container');
  if (!page) return;
  if (!composer || !isCompactMessagesViewport()) {
    page.style.removeProperty('--streams-compose-offset');
    return;
  }
  const rect = composer.getBoundingClientRect();
  const offset = Math.max(72, Math.ceil(rect.height) + 10);
  page.style.setProperty('--streams-compose-offset', `${offset}px`);
}

function setConsoleChannelMode(enabled) {
  const page = document.querySelector('.messages-page');
  if (!page) return;
  page.classList.toggle('is-console-channel', Boolean(enabled));
}

function setComposerEnabled(
  enabled,
  placeholder = 'Type your message...',
  focus = false,
  sendLabel = 'Send',
) {
  const input = document.getElementById('messageInput');
  const sendButton = document.getElementById('sendButton');
  if (input) {
    input.disabled = !enabled;
    if (!enabled) input.value = '';
    input.placeholder = placeholder;
    autoResizeComposer();
    if (enabled && focus && document.activeElement !== input) {
      input.focus({ preventScroll: true });
    }
  }
  if (sendButton) {
    sendButton.disabled = !enabled;
    sendButton.textContent = sendLabel;
  }
  if (!enabled) {
    setComposeFeedback('Pick a thread to start typing.', 'muted');
  }
}

function getComposerSendLabel() {
  return 'Send';
}

function syncComposerSendLabel() {
  const sendButton = document.getElementById('sendButton');
  if (!sendButton) return;
  sendButton.textContent = getComposerSendLabel();
}

function focusMainComposer() {
  const input = document.getElementById('messageInput');
  if (!input || input.disabled) return false;
  setMessagesMobilePane('conversation');
  window.setTimeout(() => {
    input.scrollIntoView({ block: 'nearest' });
    input.focus({ preventScroll: true });
  }, 32);
  return true;
}

function renderConversationConsoleText(text, target = '') {
  const log = document.getElementById('messages-log');
  if (!log) return;
  log.classList.add('messages-log--console');
  currentConsoleConversationText = String(text || '');
  log.innerHTML = '';
  if (target) {
    const meta = document.createElement('div');
    meta.className = 'messages-log-console-meta';
    meta.textContent = `Live pane: ${target}`;
    log.appendChild(meta);
  }
  const transcript = document.createElement('div');
  transcript.className = 'messages-log-console-transcript';
  buildConsoleTranscriptSegments(text).forEach((segment) => {
    const block = document.createElement('div');
    block.className = `messages-log-console-card messages-log-console-card--${segment.type}`;
    const body = document.createElement(segment.type === 'meta' ? 'div' : 'pre');
    body.className = 'messages-log-console-card-body';
    body.innerHTML = segment.type === 'meta'
      ? renderMaskedPlainText(segment.text || '')
      : renderMaskedPreformattedText(segment.text || '');
    block.appendChild(body);
    transcript.appendChild(block);
  });
  log.appendChild(transcript);
  log.scrollTop = log.scrollHeight;
}

function clearConversationConsoleMode() {
  activeConversationConsoleTarget = '';
  activeConversationConsoleSocketPath = '';
  setConsoleChannelMode(false);
  setComposeHint(DEFAULT_COMPOSE_HINT);
  const log = document.getElementById('messages-log');
  if (log) {
    log.classList.remove('messages-log--console');
  }
  currentConsoleConversationText = '';
}

function extractConsoleLabel(channelName) {
  const raw = String(channelName || '').trim();
  if (!raw) return '';
  return raw.replace(/^console\s*[-:]\s*/i, '').replace(/^console\s+/i, '').trim();
}

function scorePaneForLabel(pane, labelKey) {
  if (!labelKey) return 0;
  const sessionKey = normalizeKey(pane?.session_name);
  const targetKey = normalizeKey(pane?.target);
  const titleKey = normalizeKey(pane?.pane_title);
  const pathKey = normalizeKey(pane?.pane_current_path);

  if (sessionKey === labelKey) return 120;
  if (titleKey === labelKey) return 110;
  if (targetKey.startsWith(labelKey)) return 100;
  if (sessionKey.includes(labelKey) || labelKey.includes(sessionKey)) return 90;
  if (targetKey.includes(labelKey)) return 85;
  if (titleKey.includes(labelKey)) return 80;
  if (pathKey.includes(labelKey)) return 60;
  return 0;
}

function resolveConsoleTargetForChannel(channel) {
  if (!channel) return '';
  const connector = getChannelConnector(channel);
  const config = connector?.config && typeof connector.config === 'object'
    ? connector.config
    : {};

  const explicitTarget = String(config.target || '').trim();
  const configuredSocketPath = String(config.socket_path || '').trim();
  if (
    explicitTarget
    && consolePanesCache.some((pane) => String(pane?.target || '') === explicitTarget)
  ) {
    return explicitTarget;
  }
  // Pane list is currently gathered from the default socket; keep explicit target
  // when this connector is pinned to a non-default socket.
  if (explicitTarget && configuredSocketPath) {
    return explicitTarget;
  }

  const configuredSession = String(config.session || '').trim();
  const configuredTty = normalizePaneTty(config.pane_tty || config.tty || '');
  if (configuredTty) {
    const ttyMatch = consolePanesCache.find(
      (pane) => normalizePaneTty(pane?.pane_tty) === configuredTty,
    );
    if (ttyMatch?.target) {
      return String(ttyMatch.target);
    }
  }

  const sessionKey = normalizeKey(configuredSession);
  const label = extractConsoleLabel(channel.name || '');
  const labelKey = normalizeKey(label);
  const explicitTargetKey = normalizeKey(explicitTarget);

  let best = null;
  let bestScore = 0;
  consolePanesCache.forEach((pane) => {
    if (!pane?.target) return;
    let score = 0;
    const paneSessionKey = normalizeKey(pane.session_name);
    if (sessionKey) {
      if (paneSessionKey === sessionKey) {
        score += 160;
      } else if (paneSessionKey.includes(sessionKey) || sessionKey.includes(paneSessionKey)) {
        score += 110;
      }
    }
    const paneTargetKey = normalizeKey(pane.target);
    if (explicitTargetKey) {
      if (paneTargetKey === explicitTargetKey) {
        score += 200;
      } else if (paneTargetKey.startsWith(explicitTargetKey)) {
        score += 140;
      } else if (paneTargetKey.includes(explicitTargetKey)) {
        score += 90;
      }
    }
    score += scorePaneForLabel(pane, labelKey);
    if (pane.pane_active) score += 5;
    if (Number(pane.window_index) === 0) score += 2;
    if (Number(pane.pane_index) === 0) score += 2;
    if (score > bestScore) {
      bestScore = score;
      best = pane;
    }
  });
  if (best?.target && bestScore > 0) {
    return String(best.target);
  }

  if (configuredSession) {
    return `${configuredSession}:0.0`;
  }
  if (explicitTarget) {
    return explicitTarget;
  }
  if (consolePanesCache.length === 1) {
    return String(consolePanesCache[0].target || '');
  }
  return '';
}

function renderChannelsList(channels, filterValue = '') {
  const container = document.querySelector('.channels-container');
  container.innerHTML = '';
  const filtered = channels.filter(ch =>
    ch.name.toLowerCase().includes(filterValue.toLowerCase())
  );
  filtered.forEach(ch => {
    const item = document.createElement('button');
    item.type = 'button';
    item.className = 'list-group-item list-group-item-action';
    const row = document.createElement('div');
    row.className = 'messages-thread-row';
    const name = document.createElement('span');
    name.className = 'messages-thread-name';
    name.textContent = ch.name;
    row.appendChild(name);
    const actions = document.createElement('div');
    actions.className = 'messages-thread-actions';
    const webUrl = getChannelWebUrl(ch);
    if (webUrl) {
      const link = document.createElement('a');
      link.className = 'messages-thread-link';
      link.href = webUrl;
      link.target = '_blank';
      link.rel = 'noreferrer noopener';
      link.title = webUrl;
      link.textContent = '↗';
      link.addEventListener('click', (event) => {
        event.stopPropagation();
      });
      actions.appendChild(link);
    }
    const state = getThreadRuntimeState(ch);
    if (state) {
      const badge = document.createElement('span');
      badge.className = `messages-thread-state messages-thread-state--${state.tone}`;
      badge.textContent = state.label;
      actions.appendChild(badge);
    }
    if (actions.childNodes.length) {
      row.appendChild(actions);
    }
    item.appendChild(row);
    item.dataset.channelId = ch.id;
    item.addEventListener('click', () => selectChannel(ch.id, { focusComposer: true }));
    container.appendChild(item);
  });
  if (!filtered.length) {
    const empty = document.createElement('div');
    empty.className = 'text-muted small';
    empty.textContent = streamsThreadMode
      ? 'No threads match your search.'
      : 'No sources match your search.';
    container.appendChild(empty);
  }
}

function renderChannelSelects(channels, allChannels = channels) {
  const messageSelect = document.getElementById('message-channel-select');
  const messageSelectMobile = document.getElementById('message-channel-select-mobile');
  const filterSelect = document.getElementById('filter-channel');
  messageSelect.innerHTML = '<option value="" disabled selected>Choose a thread...</option>';
  if (messageSelectMobile) {
    messageSelectMobile.innerHTML = '<option value="" disabled selected>Choose a thread...</option>';
  }
  filterSelect.innerHTML = '<option value="" disabled selected>Choose a thread...</option>';
  channels.forEach(ch => {
    const opt1 = document.createElement('option');
    opt1.value = ch.id;
    opt1.textContent = ch.name;
    messageSelect.appendChild(opt1);
    if (messageSelectMobile) {
      const optMobile = opt1.cloneNode(true);
      messageSelectMobile.appendChild(optMobile);
    }
    const opt2 = opt1.cloneNode(true);
    filterSelect.appendChild(opt2);
  });
  if (allChannels !== channels) {
    filterSelect.innerHTML = '<option value="" disabled selected>Choose a source...</option>';
    allChannels.forEach((ch) => {
      const opt = document.createElement('option');
      opt.value = ch.id;
      opt.textContent = ch.name;
      filterSelect.appendChild(opt);
    });
  }
  messageSelect.disabled = channels.length === 0;
  if (messageSelectMobile) {
    messageSelectMobile.disabled = channels.length === 0;
  }
  filterSelect.disabled = allChannels.length === 0;
}

async function loadConnectors() {
  const select = document.getElementById('channel-connector');
  const addButton = document.getElementById('addChannelBtn');
  connectorsById = new Map();
  select.innerHTML = '';
  const resp = await fetch('/api/connectors', { cache: "no-store" });
  if (!resp.ok) {
    select.innerHTML = '<option value="" disabled selected>Unable to load connectors</option>';
    if (addButton) addButton.disabled = true;
    setStatus('channels-status', 'Unable to load connectors. Please refresh or log in again.', 'danger');
    return;
  }
  const connectors = await resp.json();
  connectors.forEach((connector) => {
    const id = Number.parseInt(connector?.id, 10);
    if (Number.isFinite(id)) {
      connectorsById.set(id, connector);
    }
  });
  if (!connectors.length) {
    select.innerHTML = '<option value="" disabled selected>No connectors yet</option>';
    if (addButton) addButton.disabled = true;
    setStatus('channels-status', 'Create a connector before adding sources.', 'warning');
    return;
  }
  // Bulk status fetch avoids N per-connector /status calls (this page is often open in parallel
  // with Home/Connectors, and request storms quickly become painful).
  let statusById = new Map();
  try {
    const statusResp = await fetch('/api/v1/connectors/statuses', { cache: 'default' });
    if (statusResp.ok) {
      const payload = await statusResp.json();
      const items = Array.isArray(payload.items) ? payload.items : [];
      items.forEach((row) => {
        if (!row) return;
        const id = Number.parseInt(row.connector_id, 10);
        if (!Number.isFinite(id)) return;
        statusById.set(id, row.status || 'unknown');
      });
    }
  } catch (err) {
    // ignore status fetch failure
  }

  const enriched = connectors.map((connector) => ({
    ...connector,
    status: statusById.get(connector.id) || 'unknown',
  }));
  const ready = enriched.filter(connector => connector.status === 'up');
  if (!ready.length) {
    select.innerHTML = '<option value="" disabled selected>No configured connectors</option>';
    if (addButton) addButton.disabled = true;
    setStatus('channels-status', 'Configure a connector before adding sources.', 'warning');
    return;
  }
  ready.forEach(connector => {
    const opt = document.createElement('option');
    opt.value = connector.id;
    opt.textContent = `${connector.name} (${connector.connector_type})`;
    select.appendChild(opt);
  });
  if (addButton) addButton.disabled = false;
  loadEditorInbox({ force: true, silent: true }).catch(() => {});
  if (channelsCache.length) {
    const visibleChannels = getVisibleChannels();
    renderChannelsList(visibleChannels, document.getElementById('channelSearch')?.value || '');
    renderChannelSelects(visibleChannels, channelsCache);
  }
}

async function loadChannels() {
  const resp = await fetch('/api/v1/channels/', { cache: "no-store" });
  if (!resp.ok) {
    setStatus('channels-status', 'Unable to load sources.', 'danger');
    return;
  }
  channelsCache = await resp.json();
  if (
    selectedChannelId &&
    !channelsCache.some((channel) => channel.id === selectedChannelId)
  ) {
    selectedChannelId = null;
  }
  const visibleChannels = getVisibleChannels();
  const countEl = document.getElementById('channels-count');
  if (countEl) {
    countEl.textContent = streamsThreadMode
      ? `${visibleChannels.length}/${channelsCache.length}`
      : String(channelsCache.length);
  }
  updateThreadsMobileBadge(visibleChannels.length, channelsCache.length);
  renderChannelsList(visibleChannels, document.getElementById('channelSearch').value);
  renderChannelSelects(visibleChannels, channelsCache);
  const launchChannel = !launchContextApplied ? findLaunchChannel(visibleChannels) : null;
  if (
    selectedChannelId &&
    !visibleChannels.some((channel) => channel.id === selectedChannelId)
  ) {
    selectedChannelId = null;
    updateAgentControls(null);
  }
  if (launchChannel) {
    if (Number(selectedChannelId || 0) !== Number(launchChannel.id)) {
      selectChannel(launchChannel.id, { focusComposer: launchFocusComposer });
    }
    window.setTimeout(() => {
      applyLaunchDraftToComposer();
    }, 30);
  } else if (visibleChannels.length && !selectedChannelId) {
    const storedId = readStoredStreamsChannelId();
    const stored = visibleChannels.find((channel) => channel.id === storedId);
    const normanChannel = visibleChannels.find((channel) =>
      /^console\s*[-:]\s*norman$/i.test(String(channel.name || '').trim())
    );
    selectChannel((stored || normanChannel || visibleChannels[0]).id, { focusComposer: false });
    if (launchDraftMessage) {
      window.setTimeout(() => {
        applyLaunchDraftToComposer();
      }, 30);
    }
  }
  if (!visibleChannels.length) {
    if (isCompactMessagesViewport()) {
      setMessagesMobilePane('channels');
    }
    if (channelsCache.length) {
      setStatus('channels-status', 'No visible threads. Tap "Show Feeds" to browse all sources.', 'info');
    } else {
      setStatus('channels-status', 'No sources yet. Create one on the left.', 'info');
    }
  } else {
    setStatus('channels-status', '');
  }
}

function selectChannel(channelId, options = {}) {
  const { focusComposer = false } = options;
  if (!pendingConsoleResponse || Number(pendingConsoleResponse.channelId) !== Number(channelId)) {
    clearPendingConsoleResponse();
  }
  selectedChannelId = channelId;
  writeStoredStreamsChannelId(channelId);
  const channel = channelsCache.find(ch => ch.id === channelId);
  setActiveChannelName(channel ? channel.name : 'None');
  setActiveDeliveryTarget(channel ? channel.name : 'None', 'muted');
  setActiveWebLink(channel || null);
  const messageSelect = document.getElementById('message-channel-select');
  if (messageSelect) messageSelect.value = String(channelId);
  const messageSelectMobile = document.getElementById('message-channel-select-mobile');
  if (messageSelectMobile) messageSelectMobile.value = String(channelId);
  document.querySelectorAll('.channels-container .list-group-item').forEach(el => {
    el.classList.toggle('active', Number(el.dataset.channelId) === channelId);
  });
  updateAgentControls(channel || null);
  updateRandomSimulator(channel);
  setActiveOperatorBadge(channel || null);
  syncSecretPanelState();
  loadSecretStash(channelId).catch((err) => {
    setSecretStatus(err.message || 'Unable to load secret stash.', 'err');
  });
  if (channel && isConsoleChannel(channel)) {
    refreshTmuxControlSessions({ silent: true });
  }
  loadMessages(channelId, { forceScroll: true, focusComposer });
  updateComposerSecretState();
  if (isCompactMessagesViewport()) {
    setMessagesMobilePane('conversation');
  }
}

async function loadConsoleConversation(channel, options = {}) {
  const { focusComposer = false, allowRecovery = true } = options;
  if (!channel) return;

  if (!consolePanesCache.length) {
    await loadConsolePanes();
  }

  const connector = getChannelConnector(channel);
  const config = connector?.config && typeof connector.config === 'object'
    ? connector.config
    : {};
  const canSendToTmux = connector?.connector_type === 'tmux' && Number.isFinite(Number(channel.connector_id));
  const socketPath = String(config.socket_path || '').trim();

  let target = resolveConsoleTargetForChannel(channel);
  if (!target) {
    await tryAutoResumeConsoleChannel(channel, { reason: 'no_target' });
    await loadConsolePanes();
    target = resolveConsoleTargetForChannel(channel);
  }

  if (!target) {
    clearPendingConsoleResponse();
    clearConversationConsoleMode();
    setComposerEnabled(false, 'No tmux target mapped yet.');
    renderConversationConsoleText('No tmux pane is mapped for this thread yet.');
    setActiveDeliveryTarget(`${channel.name || 'Console'} (unmapped)`, 'warn');
    setStatus(
      'channels-status',
      'No tmux pane mapping found. Start/Continue this session or set a tmux target on the connector.',
      'warning',
    );
    setComposeFeedback('No tmux target is mapped for this thread yet. Tap Continue in Session Controls.', 'warn');
    updateAgentControls(channel);
    return;
  }

  setConversationConsoleTarget(target, socketPath);
  setActiveDeliveryTarget(`${channel.name || 'Console'} -> ${target}`, 'ok');
  updateAgentControls(channel);

  setConsoleChannelMode(true);
  if (canSendToTmux) {
    setComposerEnabled(true, `Send to tmux • ${target}`, focusComposer, 'Send');
    setComposeHint(`Console mode · Send or Enter to ${target}`);
    const hasPendingForChannel = Boolean(
      pendingConsoleResponse
      && Number(pendingConsoleResponse.channelId) === Number(channel.id)
    );
    if (!hasPendingForChannel) {
      setComposeFeedback(`Connected to ${target}. Send or Enter runs command.`, 'ok');
    }
  } else {
    clearPendingConsoleResponse();
    setComposerEnabled(false, `Console thread is read-only • ${target}`, false, 'Send');
    setComposeHint('Console mode · read-only');
    setComposeFeedback(`Read-only thread (${target}).`, 'warn');
  }
  setStatus('channels-status', '');

  const lines = Number.parseInt(
    document.getElementById('messages-console-lines')?.value || '120',
    10,
  ) || 120;

  const seq = ++consoleConversationRequestSeq;
  try {
    const rawText = await fetchTmuxCaptureText(target, lines, socketPath);
    const text = simplifyTmuxCaptureText(rawText);
    if (seq !== consoleConversationRequestSeq || selectedChannelId !== channel.id) return;
    renderConversationConsoleText(text, target);
    const output = document.getElementById('messages-console-output');
    if (output) output.innerHTML = renderMaskedPreformattedText(text);
    updatePendingConsoleResponse(channel, text);
    setConsoleStatus('');
  } catch (err) {
    if (
      allowRecovery
      && isRecoverableTmuxError(err)
      && seq === consoleConversationRequestSeq
      && selectedChannelId === channel.id
    ) {
      await tryAutoResumeConsoleChannel(channel, { force: true, reason: 'capture_error', feedback: false });
      await loadConsolePanes();
      const recoveredTarget = resolveConsoleTargetForChannel(channel);
      if (recoveredTarget && recoveredTarget !== target) {
        setConversationConsoleTarget(recoveredTarget, socketPath);
        try {
          const recoveredRawText = await fetchTmuxCaptureText(
            recoveredTarget,
            lines,
            socketPath,
          );
          const recoveredText = simplifyTmuxCaptureText(recoveredRawText);
          if (seq !== consoleConversationRequestSeq || selectedChannelId !== channel.id) return;
          renderConversationConsoleText(recoveredText, recoveredTarget);
          const output = document.getElementById('messages-console-output');
          if (output) output.innerHTML = renderMaskedPreformattedText(recoveredText);
          setComposeHint(`Console mode · Send or Enter to ${recoveredTarget}`);
          if (canSendToTmux) {
            setComposerEnabled(true, `Send to tmux • ${recoveredTarget}`, focusComposer, 'Send');
          }
          updatePendingConsoleResponse(channel, recoveredText);
          if (!pendingConsoleResponse) {
            setComposeFeedback(`Remapped to ${recoveredTarget}.`, 'muted');
          }
          setStatus(
            'channels-status',
            `Remapped stale tmux target to ${recoveredTarget}.`,
            'info',
          );
          setConsoleStatus('');
          return;
        } catch (recoverErr) {
          err = recoverErr;
        }
      }
    }
    if (seq !== consoleConversationRequestSeq || selectedChannelId !== channel.id) return;
    clearPendingConsoleResponse();
    renderConversationConsoleText(
      `Unable to capture tmux output for ${target}\n\n${err.message || 'Unknown error'}`,
      target,
    );
    setConsoleStatus(err.message || 'Unable to capture pane output.', 'danger');
    setStatus(
      'channels-status',
      err.message || 'Unable to capture tmux output.',
      isRecoverableTmuxError(err) ? 'warning' : 'danger',
    );
  }
}

async function sendConsoleMessage(channel, content) {
  const info = getChannelTmuxSessionInfo(channel);
  if (!connectorsById.size) {
    await loadConnectors().catch(() => {});
  }
  const connectorId = Number(info?.connectorId || 0) || getPreferredTmuxConnectorId(channel);
  if (!connectorId) {
    throw new Error('No tmux connector is configured. Add one in Connectors.');
  }
  let target = String(info?.target || '').trim()
    || resolveConsoleTargetForChannel(channel)
    || '';
  if (!target) {
    throw new Error('No tmux target mapped for this thread.');
  }
  const socketPath = String(info?.socketPath || activeConversationConsoleSocketPath || '').trim();
  setComposeFeedback(`Seen. Sending to ${target}`, 'pending');

  let body = null;
  for (let attempt = 0; attempt < 2; attempt += 1) {
    const payload = {
      connector_id: connectorId,
      text: content,
      target,
      enter_count: TMUX_SEND_ENTER_COUNT,
    };
    if (socketPath) {
      payload.socket_path = socketPath;
    }
    try {
      body = await requestTmuxSend(payload);
      break;
    } catch (err) {
      if (attempt > 0 || !isRecoverableTmuxError(err)) {
        throw err;
      }
      await loadConsolePanes();
      const recoveredTarget = resolveConsoleTargetForChannel(channel);
      if (!recoveredTarget || recoveredTarget === target) {
        throw err;
      }
      target = recoveredTarget;
      setConversationConsoleTarget(target, socketPath);
      setComposeHint(`Console mode · Send or Enter to ${target}`);
      setComposeFeedback(`Remapped. Sending to ${target}`, 'pending');
      setStatus('channels-status', `Remapped stale tmux target to ${target}.`, 'info');
    }
  }
  if (!body) {
    throw new Error('Unable to send command to tmux.');
  }

  const status = String(body.status || '').toLowerCase();
  if (status === 'sent') {
    const liveTarget = String(body.target || target);
    const submitMode = String(body.submit_mode || '').trim().toLowerCase();
    setActiveDeliveryTarget(`${channel.name || 'Console'} -> ${liveTarget}`, 'ok');
    setStatus('channels-status', `Sent to ${liveTarget}.`, 'success');
    if (submitMode === 'tab_enter') {
      setComposeFeedback(`Seen. Sent to ${liveTarget} via Tab+Enter`, 'ok');
    } else if (submitMode) {
      setComposeFeedback(`Seen. Sent to ${liveTarget} (${submitMode})`, 'ok');
    }
    startPendingConsoleResponse(channel, liveTarget, getCurrentConsoleConversationText());
    await loadConsoleConversation(channel);
    setTimeout(() => {
      if (selectedChannelId === channel.id) {
        loadConsoleConversation(channel);
      }
    }, 600);
    return { status: 'sent', target: liveTarget };
  }
  if (status === 'needs_approval') {
    clearPendingConsoleResponse();
    const approvalId = body.approval_id ? ` (approval #${body.approval_id})` : '';
    const reason = body.reason || 'Command requires approval.';
    setStatus('channels-status', `${reason}${approvalId}`, 'warning');
    loadEditorInbox({ force: true, silent: false }).catch(() => {});
    return { status: 'needs_approval', reason };
  }
  if (status === 'blocked') {
    throw createSendError(body.reason || 'Command blocked by safety policy.', 'blocked');
  }

  throw createSendError(body.reason || 'Unexpected tmux send response.', 'tmux_unexpected');
}

async function sendSelectedPaneMessage() {
  const input = document.getElementById('messages-console-input');
  const sendBtn = document.getElementById('messages-console-send');
  if (!input || !sendBtn) return;
  const text = String(input.value || '').trim();
  if (!text) return;
  if (shouldCaptureSensitiveText(text)) {
    if (stageSecretDraft(text)) {
      input.value = '';
      setConsoleStatus('Potential secret moved to Secrets. Use the pointer instead of a raw pane paste.', 'warning');
      updateComposerSecretState();
    }
    return;
  }
  if (!selectedConsoleTarget) {
    setConsoleStatus('Select a pane first.', 'warning');
    return;
  }

  if (!connectorsById.size) {
    await loadConnectors().catch(() => {});
  }
  const connectorId = getPreferredTmuxConnectorId();
  if (!connectorId) {
    setConsoleStatus('No tmux connector available. Add one in Connectors.', 'warning');
    return;
  }

  sendBtn.disabled = true;
  try {
    let sendTarget = selectedConsoleTarget;
    let body = null;
    for (let attempt = 0; attempt < 2; attempt += 1) {
      const payload = {
        connector_id: connectorId,
        text,
        target: sendTarget,
        enter_count: TMUX_SEND_ENTER_COUNT,
      };
      if (activeConversationConsoleSocketPath) {
        payload.socket_path = activeConversationConsoleSocketPath;
      }
      try {
        body = await requestTmuxSend(payload);
        break;
      } catch (err) {
        if (attempt > 0 || !isRecoverableTmuxError(err)) {
          throw err;
        }
        await loadConsolePanes();
        const selectedChannel = getSelectedChannel();
        let recoveredTarget = '';
        if (selectedChannel && isConsoleChannel(selectedChannel)) {
          recoveredTarget = resolveConsoleTargetForChannel(selectedChannel);
        }
        if (!recoveredTarget && consolePanesCache.length) {
          recoveredTarget = String(consolePanesCache[0].target || '');
        }
        if (!recoveredTarget || recoveredTarget === sendTarget) {
          throw err;
        }
        sendTarget = recoveredTarget;
        selectedConsoleTarget = sendTarget;
        if (
          activeConversationConsoleTarget
          && selectedChannel
          && isConsoleChannel(selectedChannel)
        ) {
          setConversationConsoleTarget(sendTarget, activeConversationConsoleSocketPath);
          setComposeHint(`Console mode · Send or Enter to ${sendTarget}`);
          setComposeFeedback(`Remapped to ${sendTarget}.`, 'muted');
        }
        setConsoleStatus(`Remapped stale tmux target to ${sendTarget}.`, 'info');
      }
    }
    if (!body) {
      throw new Error('Unable to send command to tmux.');
    }
    const status = String(body.status || '').toLowerCase();
    if (status === 'sent') {
      input.value = '';
      updateComposerSecretState();
      const liveTarget = String(body.target || sendTarget || selectedConsoleTarget || '');
      selectedConsoleTarget = liveTarget || selectedConsoleTarget;
      setConsoleStatus(`Sent to ${liveTarget || selectedConsoleTarget}.`, 'success');
      await captureSelectedConsolePane();
      const selectedChannel = getSelectedChannel();
      if (
        selectedChannel &&
        isConsoleChannel(selectedChannel) &&
        activeConversationConsoleTarget &&
        selectedConsoleTarget === activeConversationConsoleTarget
      ) {
        await loadConsoleConversation(selectedChannel, { focusComposer: false });
      }
      return;
    }
    if (status === 'needs_approval') {
      const approvalId = body.approval_id ? ` (approval #${body.approval_id})` : '';
      const reason = body.reason || 'Command requires approval.';
      setConsoleStatus(`${reason}${approvalId}`, 'warning');
      setComposeFeedback(`${reason} See Inbox.`, 'warn');
      loadEditorInbox({ force: true, silent: false }).catch(() => {});
      return;
    }
    if (status === 'blocked') {
      const reason = body.reason || 'Command blocked by safety policy.';
      setConsoleStatus(reason, 'warning');
      setComposeFeedback(reason, 'warn');
      return;
    }
    setConsoleStatus(body.reason || 'Unexpected tmux send response.', 'warning');
  } catch (err) {
    setConsoleStatus(err.message || 'Unable to send to pane.', 'danger');
  } finally {
    sendBtn.disabled = false;
  }
}

async function loadMessages(channelId, options = {}) {
  const { forceScroll = false, silent = false, focusComposer = false } = options;
  const channel = channelsCache.find(ch => ch.id === channelId) || null;
  if (!connectorsById.size) {
    await loadConnectors().catch(() => {});
  }
  if (isConsoleChannel(channel)) {
    await loadConsoleConversation(channel, { focusComposer });
    return;
  }

  consoleConversationRequestSeq += 1;
  clearPendingConsoleResponse();
  clearConversationConsoleMode();
  const channelName = String(channel?.name || '').trim();
  const placeholder = channelName ? `Message ${channelName}...` : 'Type your message...';
  const operator = getChannelOperatorState(channel);
  setComposerEnabled(true, placeholder, focusComposer);
  setActiveDeliveryTarget(channelName || 'None', 'muted');
  setComposeFeedback(channelName ? `Typing in ${channelName}` : 'Ready', 'muted');
  setComposeHint(
    operator?.mode === 'take'
      ? 'Manual mode · Norman may watch and draft privately'
      : operator?.mode === 'co_pilot'
        ? 'Shared mode · You and Norman can both write here'
        : DEFAULT_COMPOSE_HINT,
  );
  const log = document.getElementById('messages-log');
  if (!log) return;
  const wasNearBottom = forceScroll || (log.scrollHeight - log.clientHeight - log.scrollTop) < 28;
  const requestSeq = ++messagesRequestSeq;
  try {
    const resp = await fetch(`/api/v1/channels/${channelId}/messages`, { cache: 'no-store' });
    if (!resp.ok) {
      if (!silent) {
        setStatus('channels-status', 'Messages are not available for this thread yet.', 'warning');
      }
      return;
    }
    const messages = await resp.json();
    if (requestSeq !== messagesRequestSeq || selectedChannelId !== channelId) return;
    log.innerHTML = '';
    messages.forEach(msg => {
      const source = String(msg.source || 'system').trim().toLowerCase();
      const roleClass = source === 'user'
        ? 'user'
        : source === 'system'
          ? 'system'
          : 'assistant';

      const row = document.createElement('article');
      row.className = `message ${roleClass}`;

      const text = document.createElement('div');
      text.className = 'message-text';
      text.innerHTML = renderMaskedPlainText(msg.content || msg.text || '');
      row.appendChild(text);

      const meta = document.createElement('div');
      meta.className = 'message-meta';
      const sourceLabel = formatMessageSource(source);
      const timeLabel = formatMessageTime(msg.created_at);
      meta.textContent = timeLabel ? `${sourceLabel} • ${timeLabel}` : sourceLabel;
      row.appendChild(meta);

      log.appendChild(row);
    });
    if (wasNearBottom) {
      log.scrollTop = log.scrollHeight;
    }
    if (!silent) {
      setStatus('channels-status', '');
    }
  } catch (err) {
    if (requestSeq !== messagesRequestSeq || selectedChannelId !== channelId) return;
    if (!silent) {
      setStatus('channels-status', err.message || 'Unable to load messages.', 'warning');
    }
  }
}

function stopMessagesFollow() {
  if (messagesFollowTimer) {
    clearInterval(messagesFollowTimer);
    messagesFollowTimer = null;
  }
  messagesFollowInFlight = false;
}

function startMessagesFollow() {
  stopMessagesFollow();
  messagesFollowTimer = setInterval(async () => {
    if (messagesFollowInFlight) return;
    if (document.hidden) return;
    if (!selectedChannelId) return;
    const channel = getSelectedChannel();
    if (!channel || isConsoleChannel(channel)) return;
    messagesFollowInFlight = true;
    try {
      await loadMessages(selectedChannelId, { forceScroll: false, silent: true });
    } finally {
      messagesFollowInFlight = false;
    }
  }, MESSAGE_FOLLOW_INTERVAL_MS);
}

function updateRandomSimulator(channel) {
  const panel = document.getElementById('random-sim-panel');
  if (!panel) return;
  const isRandom = channel && /random data/i.test(channel.name || '');
  panel.classList.toggle('d-none', !isRandom);
  if (!isRandom) {
    stopRandomSimulator();
    return;
  }
  randomSim.channelId = channel.id;
}

function getRandomSettings() {
  const duration = Number.parseInt(document.getElementById('random-duration').value, 10) || 1;
  const interval = Number.parseInt(document.getElementById('random-interval').value, 10) || 5;
  const jitter = Number.parseInt(document.getElementById('random-jitter').value, 10) || 0;
  const batch = Number.parseInt(document.getElementById('random-batch').value, 10) || 1;
  return { duration, interval, jitter, batch };
}

async function sendRandomMessage(channelId) {
  const payload = {
    content: `Random Data @ ${new Date().toISOString()} | value=${Math.floor(Math.random() * 1000)} | drift=${(Math.random() * 10).toFixed(2)}`
  };
  await fetch(`/api/v1/channels/${channelId}/messages`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
}

async function randomTick() {
  if (!randomSim.timer || !randomSim.channelId) return;
  const status = document.getElementById('random-status');
  const { interval, jitter, batch } = getRandomSettings();
  if (randomSim.stopAt && Date.now() >= randomSim.stopAt) {
    stopRandomSimulator('Completed.');
    return;
  }
  try {
    for (let i = 0; i < batch; i += 1) {
      await sendRandomMessage(randomSim.channelId);
    }
    if (status) status.textContent = `Running… next in ~${interval}s`;
    loadMessages(randomSim.channelId, { forceScroll: true });
  } catch (err) {
    if (status) status.textContent = 'Error sending random data.';
  }
  const jitterMs = jitter ? Math.floor(Math.random() * jitter * 1000) : 0;
  randomSim.timer = setTimeout(randomTick, interval * 1000 + jitterMs);
}

function startRandomSimulator() {
  const { duration } = getRandomSettings();
  if (!randomSim.channelId) return;
  const startBtn = document.getElementById('random-start');
  const stopBtn = document.getElementById('random-stop');
  const status = document.getElementById('random-status');
  if (randomSim.timer) return;
  randomSim.stopAt = Date.now() + duration * 60 * 1000;
  randomSim.timer = setTimeout(randomTick, 10);
  if (startBtn) startBtn.disabled = true;
  if (stopBtn) stopBtn.disabled = false;
  if (status) status.textContent = `Running for ${duration} min…`;
}

function stopRandomSimulator(message = 'Stopped.') {
  if (randomSim.timer) {
    clearTimeout(randomSim.timer);
    randomSim.timer = null;
  }
  randomSim.stopAt = null;
  const startBtn = document.getElementById('random-start');
  const stopBtn = document.getElementById('random-stop');
  const status = document.getElementById('random-status');
  if (startBtn) startBtn.disabled = false;
  if (stopBtn) stopBtn.disabled = true;
  if (status) status.textContent = message;
}

async function postChannelMessage(channelId, content) {
  const payload = JSON.stringify({ content });
  const candidates = [
    `/api/v1/channels/${channelId}/messages`,
    `/api/v1/channels/${channelId}/messages/`,
    `/api/channels/${channelId}/messages`,
  ];
  let missingEndpoint = false;

  for (const url of candidates) {
    const resp = await fetchWithTimeout(
      url,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: payload,
      },
      CHANNEL_SEND_TIMEOUT_MS,
    );
    if (resp.ok) return;

    const body = await resp.json().catch(() => ({}));
    const detail = String(body.detail || body.reason || '').trim();
    if (resp.status === 404) {
      missingEndpoint = true;
      continue;
    }
    throw new Error(detail || 'Unable to send message for this thread.');
  }

  if (missingEndpoint) {
    throw new Error('Messages endpoint is unavailable. Refresh and restart backend.');
  }
  throw new Error('Unable to send message for this thread.');
}

async function sendMessage() {
  const input = document.getElementById('messageInput');
  const sendButton = document.getElementById('sendButton');
  const messageSelect = document.getElementById('message-channel-select');
  const messageSelectMobile = document.getElementById('message-channel-select-mobile');
  const command = parseRouteCommand(input?.value || '');
  let targetChannel = Number(
    selectedChannelId
    || messageSelectMobile?.value
    || messageSelect?.value
  );
  let content = input?.value?.trim() || '';
  if (command) {
    const routedChannel = resolveChannelByRouteTarget(command.target);
    if (!routedChannel) {
      setStatus('channels-status', `Unknown thread: ${command.target}`, 'warning');
      setComposeFeedback(`Unknown thread: ${command.target}`, 'warn');
      return;
    }
    targetChannel = Number(routedChannel.id);
    content = String(command.content || '').trim();
    setComposeFeedback(`Routing to ${routedChannel.name}`, 'pending');
    if (targetChannel && targetChannel !== Number(selectedChannelId || 0)) {
      selectChannel(targetChannel, { focusComposer: false });
    }
  }

  const channel = channelsCache.find(ch => ch.id === targetChannel) || null;
  if (!targetChannel) {
    setStatus('channels-status', 'Pick a thread before sending.', 'warning');
    setComposeFeedback('Pick a thread first.', 'warn');
    return;
  }
  if (!content) return;
  if (input?.disabled) {
    setStatus('channels-status', 'This thread is read-only right now.', 'warning');
    setComposeFeedback('This thread is read-only.', 'warn');
    return;
  }
  if (shouldCaptureSensitiveText(content)) {
    if (stageSecretDraft(content)) {
      if (input) {
        input.value = '';
        autoResizeComposer();
      }
      setComposeFeedback('Potential secret moved to Secrets. Stash it and send the pointer instead.', 'warn');
      updateComposerSecretState();
    }
    return;
  }
  if (sendButton) {
    sendButton.disabled = true;
    sendButton.textContent = 'Sending...';
  }
  setStatus('channels-status', 'Sending…', 'info');
  if (channel?.name) {
    setActiveDeliveryTarget(channel.name, 'muted');
  }
  setComposeFeedback('Seen. Sending', 'pending');
  try {
    if (channel && isConsoleChannel(channel)) {
      const result = await sendConsoleMessage(channel, content);
      if (result?.status === 'sent') {
        input.value = '';
        autoResizeComposer();
        updateComposerSecretState();
        input.focus({ preventScroll: true });
      } else if (result?.status === 'needs_approval') {
        setComposeFeedback(`${result.reason || 'Command needs approval.'} See Inbox.`, 'warn');
      }
      return;
    }

    await postChannelMessage(targetChannel, content);
    input.value = '';
    autoResizeComposer();
    updateComposerSecretState();
    if (selectedChannelId === targetChannel) {
      await loadMessages(targetChannel, { forceScroll: true });
    } else {
      selectChannel(targetChannel, { focusComposer: true });
    }
    input.focus({ preventScroll: true });
    setStatus('channels-status', '');
    if (channel?.name) {
      setActiveDeliveryTarget(channel.name, 'ok');
    }
    setComposeFeedback('Delivered.', 'ok');
  } catch (err) {
    clearPendingConsoleResponse();
    const failure = classifySendFailure(err);
    setStatus(
      'channels-status',
      failure.message || 'Unable to send message for this thread.',
      failure.type,
    );
    if (channel?.name) {
      setActiveDeliveryTarget(
        channel.name,
        failure.type === 'warning' ? 'warn' : 'err',
      );
    }
    setComposeFeedback(
      failure.message || 'Unable to send.',
      failure.tone,
    );
  } finally {
    if (sendButton && !input?.disabled) sendButton.disabled = false;
    syncComposerSendLabel();
  }
}

async function createChannel(data) {
  const resp = await fetch('/api/v1/channels/', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
    cache: "no-store",
  });
  const payload = await resp.json().catch(() => ({}));
  if (!resp.ok) {
    if (resp.status === 429) {
      throw new Error('Rate limited. Please wait a moment and try again.');
    }
    throw new Error(payload.detail || 'Failed to create source');
  }
  return payload;
}

async function ensureSampleConnector() {
  const resp = await fetch('/api/connectors');
  if (!resp.ok) {
    throw new Error('Unable to load connectors');
  }
  const connectors = await resp.json();
  let sample = connectors.find(c => c.connector_type === 'sample');
  if (sample) {
    return sample;
  }
  const created = await fetch('/api/connectors/create', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      name: 'Sample Connector',
      connector_type: 'sample',
      config: {},
    }),
    cache: "no-store",
  });
  if (!created.ok) {
    const error = await created.json();
    throw new Error(error.detail || 'Failed to create sample connector');
  }
  return created.json();
}

async function seedSampleChannels() {
  try {
    const sampleConnector = await ensureSampleConnector();
    const channelResp = await fetch('/api/v1/channels/', { cache: "no-store" });
    const channels = channelResp.ok ? await channelResp.json() : [];
    const samples = [
      {
        name: 'Random Data',
        messages: [
          `Sample values: ${Math.floor(Math.random() * 1000)}, ${Math.floor(Math.random() * 1000)}, ${Math.floor(Math.random() * 1000)}`,
          `Random float: ${(Math.random() * 100).toFixed(4)}`,
        ],
      },
      {
        name: 'Time Signals (NIST)',
        messages: [
          `NIST time (local): ${new Date().toISOString()}`,
          'Reference: https://time.gov (use this for authoritative time)',
        ],
      },
      {
        name: 'System Events',
        messages: [
          'System boot completed.',
          'Background worker started.',
          'No alerts in the last 15 minutes.',
        ],
      },
    ];

    for (const sample of samples) {
      let channel = channels.find(c => c.name === sample.name);
      if (!channel) {
        channel = await createChannel({ name: sample.name, connector_id: sampleConnector.id });
      }
      if (channel?.id) {
        for (const message of sample.messages) {
          await fetch(`/api/v1/channels/${channel.id}/messages`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ content: message }),
          });
        }
      }
    }
    await loadChannels();
    await loadFilters();
    setStatus('channels-status', 'Sample sources created.', 'success');
  } catch (err) {
    setStatus('channels-status', err.message || 'Failed to create sample sources.', 'danger');
  }
}

async function createBot(data) {
  const resp = await fetch('/api/bots/create', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  });
  return resp.json();
}

async function loadBots() {
  const resp = await fetch('/api/bots', { cache: "no-store" });
  if (!resp.ok) {
    setStatus('bots-status', 'Unable to load sessions.', 'danger');
    return;
  }
  const bots = await resp.json();
  updateCount('bots-count', bots.length);
  const list = document.getElementById('bots-list');
  list.innerHTML = '';
  if (!bots.length) {
    setStatus('bots-status', 'No sessions yet. Create one below.', 'info');
    return;
  }
  setStatus('bots-status', '');
  bots.forEach(bot => {
    const row = document.createElement('div');
    row.className = 'list-group-item d-flex justify-content-between align-items-center';
    row.innerHTML = `<div><div class="fw-semibold">${bot.name}</div><div class="small text-muted">${bot.gpt_model || 'model not set'}</div></div>`;
    list.appendChild(row);
  });
}

async function loadFilters() {
  const resp = await fetch('/api/v1/filters/');
  if (!resp.ok) {
    setStatus('filters-status', 'Unable to load filters.', 'danger');
    return;
  }
  const filters = await resp.json();
  updateCount('filters-count', filters.length);
  const list = document.getElementById('filters-list');
  list.innerHTML = '';
  if (!filters.length) {
    setStatus('filters-status', 'No filters yet. Create one below.', 'info');
    return;
  }
  setStatus('filters-status', '');
  filters.forEach(filter => {
    const channelName = channelsCache.find(ch => ch.id === filter.channel_id)?.name || `Source ${filter.channel_id}`;
    const row = document.createElement('div');
    row.className = 'list-group-item';
    row.innerHTML = `<div class="fw-semibold">${channelName}</div><div class="small text-muted">${filter.regex}</div>`;
    list.appendChild(row);
  });
}

async function createFilter(data) {
  const resp = await fetch('/api/v1/filters/', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  });
  return resp.json();
}

function setConsoleStatus(message, type = 'info') {
  const el = document.getElementById('messages-consoles-status');
  if (!el) return;
  if (!message) {
    el.classList.add('d-none');
    el.textContent = '';
    return;
  }
  el.className = `alert alert-${type}`;
  el.textContent = message;
}

function formatConsolePaneLabel(pane) {
  const target = pane?.target || '';
  const title = pane?.pane_title || '';
  const cmd = pane?.pane_current_command || '';
  const path = pane?.pane_current_path || '';
  return [target, title, cmd, path].filter(Boolean).join(' • ');
}

function renderConsolePanes() {
  const select = document.getElementById('messages-console-select');
  const count = document.getElementById('messages-console-count');
  if (!select) return;
  select.innerHTML = '';
  if (count) count.textContent = String(consolePanesCache.length);

  if (!consolePanesCache.length) {
    select.innerHTML = '<option value="" selected disabled>No panes found</option>';
    selectedConsoleTarget = '';
    const output = document.getElementById('messages-console-output');
    if (output) output.innerHTML = renderMaskedPreformattedText('No tmux panes available.');
    return;
  }

  consolePanesCache.forEach((pane) => {
    const option = document.createElement('option');
    option.value = pane.target || '';
    option.textContent = formatConsolePaneLabel(pane);
    select.appendChild(option);
  });

  const targetExists = consolePanesCache.some((pane) => pane.target === selectedConsoleTarget);
  if (!selectedConsoleTarget || !targetExists) {
    if (
      activeConversationConsoleTarget &&
      !consolePanesCache.some((pane) => pane.target === activeConversationConsoleTarget)
    ) {
      const mapped = document.createElement('option');
      mapped.value = activeConversationConsoleTarget;
      mapped.textContent = `${activeConversationConsoleTarget} • mapped channel target`;
      select.appendChild(mapped);
      selectedConsoleTarget = activeConversationConsoleTarget;
    } else {
      selectedConsoleTarget = consolePanesCache[0]?.target || '';
    }
  }
  if (selectedConsoleTarget) {
    select.value = selectedConsoleTarget;
  }
}

async function captureSelectedConsolePane(options = {}) {
  const { allowRecovery = true } = options;
  const output = document.getElementById('messages-console-output');
  const linesEl = document.getElementById('messages-console-lines');
  if (!selectedConsoleTarget || !output) return;
  const lines = Number.parseInt(linesEl?.value || '120', 10) || 120;
  const socketPath = (
    activeConversationConsoleTarget &&
    selectedConsoleTarget === activeConversationConsoleTarget
  )
    ? activeConversationConsoleSocketPath
    : '';
  const seq = ++consoleRequestSeq;
  try {
    const rawText = await fetchTmuxCaptureText(selectedConsoleTarget, lines, socketPath);
    const text = simplifyTmuxCaptureText(rawText);
    if (seq !== consoleRequestSeq) return;
    output.innerHTML = renderMaskedPreformattedText(text);
    const selectedChannel = getSelectedChannel();
    if (
      activeConversationConsoleTarget &&
      selectedConsoleTarget === activeConversationConsoleTarget
    ) {
      renderConversationConsoleText(text, selectedConsoleTarget);
      if (selectedChannel && isConsoleChannel(selectedChannel)) {
        updatePendingConsoleResponse(selectedChannel, text);
      }
    }
    setConsoleStatus('');
  } catch (err) {
    if (allowRecovery && isRecoverableTmuxError(err) && seq === consoleRequestSeq) {
      await loadConsolePanes();
      const selectedChannel = getSelectedChannel();
      let recoveredTarget = '';
      if (selectedChannel && isConsoleChannel(selectedChannel)) {
        recoveredTarget = resolveConsoleTargetForChannel(selectedChannel);
      }
      if (!recoveredTarget && consolePanesCache.length) {
        recoveredTarget = String(consolePanesCache[0].target || '');
      }
      if (recoveredTarget && recoveredTarget !== selectedConsoleTarget) {
        selectedConsoleTarget = recoveredTarget;
        if (
          activeConversationConsoleTarget &&
          selectedChannel &&
          isConsoleChannel(selectedChannel)
        ) {
          setConversationConsoleTarget(recoveredTarget, activeConversationConsoleSocketPath);
        }
        await captureSelectedConsolePane({ allowRecovery: false });
        setConsoleStatus(`Remapped to ${recoveredTarget}.`, 'info');
        return;
      }
    }
    if (seq !== consoleRequestSeq) return;
    clearPendingConsoleResponse();
    output.innerHTML = '';
    if (
      activeConversationConsoleTarget &&
      selectedConsoleTarget === activeConversationConsoleTarget
    ) {
      renderConversationConsoleText(
        `Unable to capture tmux output for ${selectedConsoleTarget}\n\n${err.message || 'Unknown error'}`,
        selectedConsoleTarget,
      );
    }
    setConsoleStatus(err.message || 'Unable to capture pane output.', 'danger');
  }
}

function stopConsoleFollow() {
  if (consoleFollowTimer) {
    clearInterval(consoleFollowTimer);
    consoleFollowTimer = null;
  }
  consoleFollowInFlight = false;
}

function shouldCaptureConsoleFollow() {
  if (document.hidden) return false;
  if (!selectedConsoleTarget) return false;
  const selectedChannel = getSelectedChannel();
  if (
    selectedChannel &&
    isConsoleChannel(selectedChannel) &&
    activeConversationConsoleTarget &&
    selectedConsoleTarget === activeConversationConsoleTarget
  ) {
    return true;
  }
  if (isCompactMessagesViewport()) {
    return activeMobilePane === 'automation';
  }
  return true;
}

function startConsoleFollow() {
  stopConsoleFollow();
  const follow = document.getElementById('messages-console-follow');
  if (!follow?.checked) return;
  consoleFollowTimer = setInterval(async () => {
    if (!shouldCaptureConsoleFollow()) return;
    if (consoleFollowInFlight) return;
    consoleFollowInFlight = true;
    try {
      await captureSelectedConsolePane();
    } finally {
      consoleFollowInFlight = false;
    }
  }, CONSOLE_FOLLOW_INTERVAL_MS);
}

async function loadConsolePanes() {
  try {
    const resp = await fetch('/api/v1/tmux/panes', { cache: 'no-store' });
    if (!resp.ok) {
      throw new Error('Unable to load tmux panes');
    }
    const payload = await resp.json();
    const items = Array.isArray(payload.items) ? payload.items : [];
    consolePanesCache = items
      .filter((pane) => pane && pane.target)
      .sort((a, b) => String(a.target).localeCompare(String(b.target)));
    renderConsolePanes();
    if (selectedConsoleTarget) {
      await captureSelectedConsolePane();
    }
  } catch (err) {
    setConsoleStatus(err.message || 'Unable to load consoles.', 'warning');
    const count = document.getElementById('messages-console-count');
    if (count) count.textContent = '0';
  } finally {
    startConsoleFollow();
  }
}

document.addEventListener('DOMContentLoaded', () => {
  migrateStreamsUiState();
  readLaunchContextFromUrl();
  initSuperTuiPrimeLayer();
  initMessagesMobilePaneSwitcher();
  initStreamsSimpleModeControls();
  initStreamsLayoutControls();
  initStreamsThreadModeControls();
  initStreamsFocusMode();
  initTmuxProfileControls();
  initMessagesViewportTracking();
  setComposeHint(DEFAULT_COMPOSE_HINT);
  initComposerInput();
  setComposerEnabled(false, 'Select a thread first...', false, 'Send');
  syncSecretPanelState();
  renderSecretStashList();
  loadConnectors();
  loadChannels();
  loadBots();
  loadFilters();
  loadEditorInbox({ force: true, silent: false });
  loadConsolePanes();
  loadEstateServices({ silent: true });
  loadLlmStatus({ silent: false });
  refreshTmuxControlSessions({ silent: true });
  startTmuxAutoHuntPolling();
  startMessagesFollow();
  startEditorInboxPolling();
  startLlmStatusPolling();
  refreshTmuxProfiles(readStoredTmuxProfileName()).catch(() => {});
  if (tmuxAutoHuntEnabled) {
    window.setTimeout(() => {
      huntRunningTmuxSessions({ silent: true, refreshAll: true }).catch(() => {});
    }, 250);
  }

  if (isCompactMessagesViewport() && openConsoleInspectorOnMobile) {
    window.setTimeout(() => {
      const inspector = document.getElementById('messages-console-stack');
      if (inspector && activeMobilePane === 'automation') {
        inspector.scrollIntoView({ block: 'start', behavior: 'smooth' });
      }
      openConsoleInspectorOnMobile = false;
    }, 80);
  }

  const composeJumpMobile = document.getElementById('streams-compose-jump-mobile');
  if (composeJumpMobile) {
    composeJumpMobile.addEventListener('click', () => {
      if (!focusMainComposer()) {
        setStatus('channels-status', 'Select a thread first, then tap Type.', 'info');
      }
    });
  }
  const inboxJumpMobile = document.getElementById('messages-inbox-jump-mobile');
  if (inboxJumpMobile) {
    inboxJumpMobile.addEventListener('click', () => {
      jumpToEditorInbox();
    });
  }
  const inboxRefresh = document.getElementById('messages-inbox-refresh');
  if (inboxRefresh) {
    inboxRefresh.addEventListener('click', () => {
      loadEditorInbox({ force: true, silent: false });
    });
  }
  const mobileDrawerBackdrop = document.getElementById('messages-mobile-drawer-backdrop');
  if (mobileDrawerBackdrop) {
    mobileDrawerBackdrop.addEventListener('click', () => {
      setMessagesMobilePane('conversation');
    });
  }

  [
    document.getElementById('streams-profile-save'),
    document.getElementById('streams-profile-save-mobile'),
  ].forEach((button) => {
    if (!button) return;
    button.addEventListener('click', (event) => {
      event.preventDefault();
      saveCurrentTmuxLayout(event);
    });
  });

  [
    document.getElementById('streams-profile-load'),
    document.getElementById('streams-profile-load-mobile'),
  ].forEach((button) => {
    if (!button) return;
    button.addEventListener('click', (event) => {
      event.preventDefault();
      loadSavedTmuxLayout(event);
    });
  });

  const composerContainer = document.querySelector('.messages-page .input-message-container');
  if (composerContainer && typeof window.ResizeObserver === 'function') {
    composerResizeObserver = new ResizeObserver(() => syncComposerOffset());
    composerResizeObserver.observe(composerContainer);
  }
  const secretToggle = document.getElementById('streams-secret-toggle');
  if (secretToggle) {
    secretToggle.addEventListener('click', () => {
      setSecretPanelOpen(!secretPanelOpen);
    });
  }
  const secretStashButton = document.getElementById('streams-secret-stash');
  if (secretStashButton) {
    secretStashButton.addEventListener('click', () => {
      stashSecretDraft({ insertPointer: true });
    });
  }
  const secretStashOnlyButton = document.getElementById('streams-secret-stash-only');
  if (secretStashOnlyButton) {
    secretStashOnlyButton.addEventListener('click', () => {
      stashSecretDraft({ insertPointer: false });
    });
  }
  const secretVisibilityButton = document.getElementById('streams-secret-visibility');
  if (secretVisibilityButton) {
    secretVisibilityButton.addEventListener('click', () => {
      if (secretDraftState.concealed) {
        revealSecretDraft();
      } else {
        concealSecretDraft();
      }
    });
  }
  const secretClearButton = document.getElementById('streams-secret-clear');
  if (secretClearButton) {
    secretClearButton.addEventListener('click', () => {
      clearSecretDraft();
      setSecretStatus('Draft cleared.', 'muted');
      setSecretSummary(getSecretSummaryDefault(), 'muted');
    });
  }
  const secretValueInput = document.getElementById('streams-secret-value');
  if (secretValueInput) {
    secretValueInput.addEventListener('input', () => {
      secretDraftState.value = String(secretValueInput.value || '');
      secretDraftState.concealed = false;
      syncSecretDraftUi({ syncField: false });
    });
    secretValueInput.addEventListener('keydown', (event) => {
      if ((event.metaKey || event.ctrlKey) && event.key === 'Enter') {
        event.preventDefault();
        stashSecretDraft({ insertPointer: true });
      }
    });
  }
  const secretList = document.getElementById('streams-secret-list');
  if (secretList) {
    secretList.addEventListener('click', (event) => {
      const insertButton = event.target.closest('[data-secret-insert]');
      if (insertButton) {
        appendPointerToComposer(insertButton.getAttribute('data-secret-insert') || '');
        setComposeFeedback('Secret pointer inserted into composer.', 'ok');
        return;
      }
      const copyButton = event.target.closest('[data-secret-copy]');
      if (copyButton) {
        copyTextToClipboard(copyButton.getAttribute('data-secret-copy') || '')
          .then(() => {
            setSecretStatus('Pointer copied to clipboard.', 'ok');
            setComposeFeedback('Secret pointer copied.', 'ok');
          })
          .catch((err) => {
            setSecretStatus(err.message || 'Unable to copy pointer.', 'err');
          });
        return;
      }
      const revokeButton = event.target.closest('[data-secret-revoke]');
      if (revokeButton) {
        revokeSecretStashItem(revokeButton.getAttribute('data-secret-revoke') || '');
      }
    });
  }

  document.getElementById('message-channel-select').addEventListener('change', (event) => {
    const value = Number(event.target.value);
    if (value) selectChannel(value, { focusComposer: true });
  });
  const messageChannelSelectMobile = document.getElementById('message-channel-select-mobile');
  if (messageChannelSelectMobile) {
    messageChannelSelectMobile.addEventListener('change', (event) => {
      const value = Number(event.target.value);
      if (value) selectChannel(value, { focusComposer: true });
    });
  }
  const randomStart = document.getElementById('random-start');
  if (randomStart) {
    randomStart.addEventListener('click', startRandomSimulator);
  }
  const randomStop = document.getElementById('random-stop');
  if (randomStop) {
    randomStop.addEventListener('click', () => stopRandomSimulator('Stopped.'));
  }

  const consoleSelect = document.getElementById('messages-console-select');
  if (consoleSelect) {
    consoleSelect.addEventListener('change', (event) => {
      selectedConsoleTarget = String(event.target.value || '');
      if (activeConversationConsoleTarget) {
        activeConversationConsoleTarget = selectedConsoleTarget;
        activeConversationConsoleSocketPath = '';
      }
      captureSelectedConsolePane();
    });
  }
  const consoleRefresh = document.getElementById('messages-console-refresh');
  if (consoleRefresh) {
    consoleRefresh.addEventListener('click', () => {
      loadConsolePanes();
    });
  }
  const consoleSend = document.getElementById('messages-console-send');
  if (consoleSend) {
    consoleSend.addEventListener('click', () => sendSelectedPaneMessage());
  }
  const consoleInput = document.getElementById('messages-console-input');
  if (consoleInput) {
    consoleInput.addEventListener('input', updateComposerSecretState);
    consoleInput.addEventListener('paste', (event) => {
      maybeCaptureSensitivePaste(event, { source: 'direct-pane' });
    });
    consoleInput.addEventListener('keydown', (event) => {
      if (event.key !== 'Enter') return;
      if (event.isComposing) return;
      if (event.shiftKey) return;
      event.preventDefault();
      sendSelectedPaneMessage();
    });
  }
  const consoleLines = document.getElementById('messages-console-lines');
  if (consoleLines) {
    consoleLines.addEventListener('change', () => captureSelectedConsolePane());
  }
  const consoleFollow = document.getElementById('messages-console-follow');
  if (consoleFollow) {
    consoleFollow.addEventListener('change', () => {
      if (consoleFollow.checked) {
        captureSelectedConsolePane();
      }
      startConsoleFollow();
    });
  }

  const jumpCompose = document.getElementById('messages-console-jump-compose');
  if (jumpCompose) {
    jumpCompose.addEventListener('click', () => {
      const focused = focusMainComposer();
      if (!focused) {
        setStatus('channels-status', 'Select a thread first, then type from Stream View.', 'info');
      }
    });
  }

  const agentRefresh = document.getElementById('streams-agent-refresh');
  if (agentRefresh) {
    agentRefresh.addEventListener('click', () => {
      refreshTmuxControlSessions({ silent: false });
    });
  }
  const agentTake = document.getElementById('streams-agent-take');
  if (agentTake) {
    agentTake.addEventListener('click', () => {
      runAgentControlAction('manual');
    });
  }
  const agentCoPilot = document.getElementById('streams-agent-copilot');
  if (agentCoPilot) {
    agentCoPilot.addEventListener('click', () => {
      runAgentControlAction('shared');
    });
  }
  const agentRelease = document.getElementById('streams-agent-release');
  if (agentRelease) {
    agentRelease.addEventListener('click', () => {
      runAgentControlAction('auto');
    });
  }
  const agentLockToggle = document.getElementById('streams-agent-lock-toggle');
  if (agentLockToggle) {
    agentLockToggle.addEventListener('click', () => {
      const nextLocked = String(agentLockToggle.dataset.nextLocked || '1') === '1';
      runAgentControlAction(nextLocked ? 'lock' : 'unlock');
    });
  }
  const agentStartStop = document.getElementById('streams-agent-start-stop');
  if (agentStartStop) {
    agentStartStop.addEventListener('click', () => {
      const action = String(agentStartStop.dataset.action || 'stop').toLowerCase() === 'start'
        ? 'start'
        : 'stop';
      runAgentControlAction(action);
    });
  }
  const agentRestart = document.getElementById('streams-agent-restart');
  if (agentRestart) {
    agentRestart.addEventListener('click', () => {
      runAgentControlAction('restart');
    });
  }
  const agentWebSave = document.getElementById('streams-agent-web-save');
  if (agentWebSave) {
    agentWebSave.addEventListener('click', () => {
      saveActiveSessionWebUrl();
    });
  }
  const agentWebInput = document.getElementById('streams-agent-web-url');
  if (agentWebInput) {
    agentWebInput.addEventListener('keydown', (event) => {
      if (event.key === 'Enter' && !event.shiftKey) {
        event.preventDefault();
        saveActiveSessionWebUrl();
      }
    });
  }
  const agentAuthDevice = document.getElementById('streams-agent-auth-device');
  if (agentAuthDevice) {
    agentAuthDevice.addEventListener('click', () => {
      startActiveSessionDeviceAuth();
    });
  }
  const agentAuthBrowser = document.getElementById('streams-agent-auth-browser');
  if (agentAuthBrowser) {
    agentAuthBrowser.addEventListener('click', () => {
      startActiveSessionBrowserAuth();
    });
  }

  document.getElementById('channelSearch').addEventListener('input', (event) => {
    renderChannelsList(getVisibleChannels(), event.target.value);
  });

  document.getElementById('messages-add-channel-form').addEventListener('submit', async (event) => {
    event.preventDefault();
    const name = document.getElementById('channel-name').value.trim();
    const connectorId = Number(document.getElementById('channel-connector').value);
    if (!name || !connectorId) {
      setStatus('channels-status', 'Source name and connector are required.', 'danger');
      return;
    }
    const channel = await createChannel({ name, connector_id: connectorId });
    if (!channel?.id) {
      setStatus('channels-status', 'Failed to create source.', 'danger');
      return;
    }
    document.getElementById('channel-name').value = '';
    await loadChannels();
    selectChannel(channel.id, { focusComposer: true });
    hideCollapse('messages-add-channel-panel');
    setStatus('channels-status', `Source "${channel.name}" created.`, 'success');
  });

  document.getElementById('messages-add-bot-form').addEventListener('submit', async (event) => {
    event.preventDefault();
    const nameInput = document.getElementById('bot-name');
    const descInput = document.getElementById('bot-description');
    const name = nameInput.value.trim();
    if (!name) {
      setStatus('bots-status', 'Session name is required.', 'danger');
      return;
    }
    const bot = await createBot({ name, description: descInput.value.trim(), gpt_model: 'gpt-5.5' });
    if (!bot?.id) {
      setStatus('bots-status', 'Failed to create session.', 'danger');
      return;
    }
    nameInput.value = '';
    descInput.value = '';
    await loadBots();
    hideCollapse('messages-add-bot-panel');
    if (isCompactMessagesViewport()) {
      setMessagesMobilePane('automation');
    }
    setStatus('bots-status', `Session "${bot.name}" created.`, 'success');
  });

  document.getElementById('messages-add-filter-form').addEventListener('submit', async (event) => {
    event.preventDefault();
    const channelId = Number(document.getElementById('filter-channel').value);
    const regexInput = document.getElementById('filter-regex');
    const descInput = document.getElementById('filter-description');
    const regexValue = regexInput.value.trim();
    if (!channelId || !regexValue) {
      setStatus('filters-status', 'Source and regex are required.', 'danger');
      return;
    }
    try {
      new RegExp(regexValue);
    } catch (err) {
      setStatus('filters-status', 'Invalid regex.', 'danger');
      return;
    }
    const filter = await createFilter({
      channel_id: channelId,
      regex: regexValue,
      description: descInput.value.trim(),
    });
    if (!filter?.id) {
      setStatus('filters-status', 'Failed to create filter.', 'danger');
      return;
    }
    regexInput.value = '';
    descInput.value = '';
    await loadFilters();
    hideCollapse('messages-add-filter-panel');
    if (isCompactMessagesViewport()) {
      setMessagesMobilePane('automation');
    }
    setStatus('filters-status', 'Filter created.', 'success');
  });

  window.addEventListener('beforeunload', () => {
    document.body.classList.remove('streams-fullscreen-ui');
    document.body.classList.remove('messages-drawer-open');
    if (messagesViewportTrackingCleanup) {
      messagesViewportTrackingCleanup();
      messagesViewportTrackingCleanup = null;
    }
    if (composerResizeObserver) {
      composerResizeObserver.disconnect();
      composerResizeObserver = null;
    }
    stopMessagesFollow();
    stopEditorInboxPolling();
    stopTmuxAutoHuntPolling();
    stopConsoleFollow();
    stopRandomSimulator();
  });

  document.addEventListener('visibilitychange', () => {
    if (document.hidden) return;
    if (tmuxAutoHuntEnabled) {
      huntRunningTmuxSessions({ silent: true }).catch(() => {});
    }
    loadEditorInbox({ silent: true });
    if (!selectedChannelId) return;
    const channel = getSelectedChannel();
    if (!channel) return;
    if (isConsoleChannel(channel)) {
      captureSelectedConsolePane();
      return;
    }
    loadMessages(selectedChannelId, { forceScroll: false, silent: true });
  });

  const sampleBtn = document.getElementById('add-sample-channels');
  if (sampleBtn) {
    sampleBtn.addEventListener('click', seedSampleChannels);
  }
});
