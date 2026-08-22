(() => {
  const root = document.getElementById('norman-bridge');
  if (!root) return;

  const API = root.dataset.apiPrefix || '/api/v1';
  const requestedAgent = new URLSearchParams(window.location.search).get('agent') || '';
  const FALLBACK_GROUP = {
    id: 'general',
    slug: 'general',
    label: 'General',
    mark: 'G',
    kind: 'workspace',
    policy: 'Default workspace',
    domains: [],
  };
  const FALLBACK_NORMAN = {
    slug: 'norman',
    display_name: 'Norman',
    class_name: 'coordinator',
    domain_name: '',
    domain_slug: '',
    principal_id: FALLBACK_GROUP.id,
    principal_slug: FALLBACK_GROUP.slug,
    console_url: '/bot/norman/',
    directory_source: 'built-in',
  };
  const PROFILE_PALETTES = {
    tide: {
      bg: '#23343d', soft: '#2a3e48', surface: '#263a44', surface2: '#31505d',
      surface3: '#3b6271', border: '#4c7282', borderStrong: '#6591a3',
      text: '#e0edf3', muted: '#a6bcc7', bodyStart: '#22323a', bodyMid: '#29404a',
      bodyEnd: '#304853',
    },
    dusk: {
      bg: '#2a3240', soft: '#313a4a', surface: '#2d3645', surface2: '#384355',
      surface3: '#445266', border: '#4d5a70', borderStrong: '#65748d',
      text: '#e4ebf2', muted: '#a8b3c2', bodyStart: '#29313e', bodyMid: '#303846',
      bodyEnd: '#353f4d',
    },
    blueprint: {
      bg: '#151b4b', soft: '#182052', surface: '#151c4a', surface2: '#1b2458',
      surface3: '#243067', border: '#2f467a', borderStrong: '#3674a4',
      text: '#e8eeff', muted: '#95a7cf', bodyStart: '#12173f', bodyMid: '#151b4b',
      bodyEnd: '#182052',
    },
    ember: {
      bg: '#342b2b', soft: '#3d3232', surface: '#392e2e', surface2: '#473939',
      surface3: '#584646', border: '#6a5350', borderStrong: '#876763',
      text: '#f0e5de', muted: '#b9a69d', bodyStart: '#322928', bodyMid: '#3a302f',
      bodyEnd: '#433735',
    },
    slate: {
      bg: '#303642', soft: '#373e4b', surface: '#343b48', surface2: '#3f4755',
      surface3: '#4a5566', border: '#556174', borderStrong: '#6e7e96',
      text: '#e5ecf4', muted: '#adb8c7', bodyStart: '#2f3541', bodyMid: '#373e4a',
      bodyEnd: '#3d4552',
    },
  };
  const TEXTURE_MOTION_PROFILES = Object.freeze({
    idle: Object.freeze({ speed: 0.10, drift: 7, amplitude: 1.8, frequency: 0.0086, square: 0.26, shear: 0.012, alpha: 0.18, glint: 0.025, transition: 1.35 }),
    ready: Object.freeze({ speed: 0.15, drift: 10, amplitude: 2.3, frequency: 0.0092, square: 0.30, shear: 0.018, alpha: 0.22, glint: 0.035, transition: 1.15 }),
    active: Object.freeze({ speed: 0.24, drift: 15, amplitude: 3.0, frequency: 0.0102, square: 0.36, shear: 0.024, alpha: 0.26, glint: 0.055, transition: 0.95 }),
    working: Object.freeze({ speed: 0.46, drift: 26, amplitude: 4.9, frequency: 0.0124, square: 0.52, shear: 0.046, alpha: 0.33, glint: 0.12, transition: 0.82 }),
    blocked: Object.freeze({ speed: 0.22, drift: 8, amplitude: 2.6, frequency: 0.0128, square: 0.64, shear: -0.042, alpha: 0.20, glint: 0.026, transition: 1.05 }),
    degraded: Object.freeze({ speed: 0.24, drift: 10, amplitude: 3.0, frequency: 0.0112, square: 0.56, shear: -0.038, alpha: 0.19, glint: 0.020, transition: 1.1 }),
    crashed: Object.freeze({ speed: 0.50, drift: 12, amplitude: 5.2, frequency: 0.0162, square: 0.74, shear: -0.09, alpha: 0.23, glint: 0.052, transition: 0.65 }),
  });
  const BRIDGE_SETTINGS_KEY = 'norman-bridge-settings-v2';
  const LOCAL_CONVERSATIONS_KEY = 'norman-bridge-conversations-v1';
  const AUTH_RESUME_KEY = 'norman-bridge-auth-resume-v1';
  const STYLE_VARIANT_OVERRIDES = {
    norman: 'anchor',
    housebot: 'anchor',
    infra: 'anchor',
    autocamera: 'grove',
    theseus: 'alloy',
    'control-plane': 'alloy',
    cloudagent: 'grove',
    dohio: 'grove',
    networking: 'signal',
    uplink: 'signal',
    earlybird: 'grove',
    scout: 'quiet',
    'leadership-kpis': 'editorial',
    'gold-book': 'editorial',
    'platinum-standard': 'alloy',
    panelbot: 'signal',
    'market-sizing': 'anchor',
    parkergale: 'editorial',
    pefb: 'editorial',
  };
  const IDENTITY_GLYPHS = Object.freeze({
    norman: 'compass',
    housebot: 'home',
    eyebat: 'eye',
    castle: 'castle',
    'diamond-roc': 'gem',
    'phone-ops': 'phone',
    uscache: 'archive',
    usbhome: 'usb',
    autocamera: 'camera',
    theseus: 'microscope',
    maps: 'map',
    earlybird: 'sunrise',
    infra: 'server',
    'control-plane': 'grid',
    'market-sizing': 'chart',
    'tmi-dashboards': 'chart',
    'gold-book': 'book',
    keystone: 'key',
    'leadership-kpis': 'chart',
    panelbot: 'panel',
    mls: 'map-pin',
    'platinum-standard': 'gem',
    netops: 'network',
    uplink: 'radio-tower',
    cloudagent: 'cloud',
    dohio: 'database',
    'null-agent': 'circle-off',
    scout: 'compass',
    pefb: 'file-text',
    artmonster: 'palette',
  });
  const INTERACTION_TONES = {
    press: { frequency: 148, ratio: 1.16, duration: 0.082, peak: 0.0046, master: 0.52, wave: 'triangle', filter: 560 },
    focus: { frequency: 196, ratio: 1.51, duration: 0.18, peak: 0.009, master: 0.62, wave: 'sine', filter: 820 },
    type: { frequency: 154, ratio: 1.34, duration: 0.048, peak: 0.003, master: 0.46, wave: 'triangle', filter: 620 },
    click: { frequency: 156, ratio: 1.62, duration: 0.12, peak: 0.008, master: 0.62, wave: 'sine', filter: 640 },
    tick: { frequency: 138, ratio: 1.28, duration: 0.064, peak: 0.0048, master: 0.5, wave: 'triangle', filter: 520 },
    send: { frequency: 202, ratio: 1.34, duration: 0.24, peak: 0.011, master: 0.72, wave: 'sine', filter: 860 },
    accepted: { frequency: 226, ratio: 1.5, duration: 0.34, peak: 0.013, master: 0.78, wave: 'sine', filter: 960 },
    queued: { frequency: 174, ratio: 1.32, duration: 0.28, peak: 0.010, master: 0.7, wave: 'triangle', filter: 760 },
    blocked: { frequency: 166, ratio: 0.78, duration: 0.18, peak: 0.0078, master: 0.62, wave: 'triangle', filter: 560 },
    error: { frequency: 184, ratio: 0.72, duration: 0.3, peak: 0.010, master: 0.72, wave: 'sine', filter: 620 },
    approve: { frequency: 207, ratio: 2.03, duration: 0.34, peak: 0.013, master: 0.76, wave: 'sine', filter: 940 },
    chime: { frequency: 176, ratio: 1.414, duration: 0.34, peak: 0.012, master: 0.72, wave: 'sine', filter: 860 },
  };
  const SIGNAL_TONES = new Set(['send', 'accepted', 'queued', 'blocked', 'error', 'approve', 'chime']);
  const state = {
    groups: [FALLBACK_GROUP],
    group: FALLBACK_GROUP.id,
    domain: '',
    view: 'general',
    selectedJobId: '',
    selectedAgent: requestedAgent,
    selectedConversationId: '',
    selectedRecipients: requestedAgent ? [requestedAgent] : [],
    conversations: [],
    stationHistory: {},
    stationHistoryLoading: '',
    stationHistoryErrors: {},
    jobActivities: {},
    jobs: [],
    agents: [{ ...FALLBACK_NORMAN }],
    approvals: [],
    heartbeats: [],
    worker: {},
    routeSummary: {},
    textureCatalog: [],
    activity: null,
    workstream: null,
    eventSource: null,
    eventSourceJobId: '',
    lastEventSequence: 0,
    decisionInFlight: '',
    search: '',
    loading: false,
    bootstrapped: false,
    boot: {
      completed: 0,
      total: 0,
      phase: 'Opening the estate',
      detail: 'Preparing a working session',
      dismissTimer: 0,
    },
    authRequired: root.dataset.authenticated !== 'true',
    pollTimer: 0,
    composerFrame: 0,
    menuPanel: 'overview',
    requestedAgentApplied: false,
    preferences: {
      feedbackSounds: 'signals',
      completionBell: 'auto',
    },
    audioContext: null,
    lastToneAt: 0,
    lastTypingToneAt: 0,
    lastCompletionAt: 0,
    lastTerminalState: '',
    composeHintDefault: '',
    prompt: {
      phase: 'idle',
      jobId: '',
      objective: '',
      error: '',
      resetTimer: 0,
    },
    texture: {
      frame: 0,
      phase: 0,
      lastTime: 0,
      impulse: 0,
      pulseTimer: 0,
      lines: [],
      focusX: 0.58,
      focusY: 0.46,
      targetX: 0.58,
      targetY: 0.46,
      inputEnergy: 0,
      flowX: 0,
      flowY: 0,
      renderProfile: null,
      disturbances: [],
      pointerX: 0,
      pointerY: 0,
      pointerAt: 0,
      keySequence: 0,
      reactiveTimer: 0,
      visualLevel: 0,
      lastVisualSync: 0,
    },
  };

  const el = (id) => document.getElementById(id);
  const nodes = {
    groupList: el('cockpit-group-list'),
    groupTitle: el('cockpit-group-title'),
    workspaceButton: el('cockpit-workspace-button'),
    workspaceMark: el('cockpit-workspace-mark'),
    domains: el('cockpit-domains'),
    workstreams: el('cockpit-workstreams'),
    agents: el('cockpit-agents'),
    rooms: el('cockpit-rooms'),
    agentCount: el('cockpit-agent-count'),
    feed: el('cockpit-feed'),
    roomTitle: el('cockpit-room-title'),
    roomSubtitle: el('cockpit-room-subtitle'),
    runtimeStatus: el('cockpit-runtime-status'),
    composer: el('cockpit-composer'),
    message: el('cockpit-message'),
    send: el('cockpit-send'),
    composeHint: el('cockpit-compose-hint'),
    resumePrompts: el('cockpit-resume-prompts'),
    recipientRow: el('cockpit-recipient-row'),
    selectedRecipients: el('cockpit-selected-recipients'),
    attentionCount: el('cockpit-attention-count'),
    navAttentionCount: el('cockpit-nav-attention-count'),
    inspector: el('cockpit-inspector'),
    inspectorAvatar: el('cockpit-inspector-avatar'),
    inspectorGroup: el('cockpit-inspector-group'),
    inspectorPolicy: el('cockpit-inspector-policy'),
    jobDetails: el('cockpit-job-details'),
    participants: el('cockpit-participants'),
    crewSection: el('cockpit-crew-section'),
    crewList: el('cockpit-crew-list'),
    openJob: el('cockpit-open-job'),
    cancelJob: el('cockpit-cancel-job'),
    nav: el('cockpit-nav'),
    backdrop: el('cockpit-mobile-backdrop'),
    search: el('cockpit-search'),
    warningStrip: el('cockpit-warning-strip'),
    warningTitle: el('cockpit-warning-title'),
    warningDetail: el('cockpit-warning-detail'),
    warningAction: el('cockpit-warning-action'),
    routeMeter: el('cockpit-route-meter'),
    queueMeter: el('cockpit-queue-meter'),
    tokenMeter: el('cockpit-token-meter'),
    agentMeter: el('cockpit-agent-meter'),
    warningMeter: el('cockpit-warning-meter'),
    menu: el('cockpit-menu'),
    menuButton: el('cockpit-menu-button'),
    menuCount: el('cockpit-menu-count'),
    menuBackdrop: el('cockpit-menu-backdrop'),
    menuPanel: el('cockpit-menu-panel'),
    menuTransport: el('cockpit-menu-transport'),
    textureCanvas: el('cockpit-thread-field'),
    bootInterstitial: el('bridge-boot-interstitial'),
    bootTitle: el('bridge-boot-title'),
    bootDetail: el('bridge-boot-detail'),
    bootProgress: el('bridge-boot-progress'),
    soundToggle: el('cockpit-sound-toggle'),
    soundTest: el('cockpit-sound-test'),
    roomDialog: el('bridge-room-dialog'),
    roomForm: el('bridge-room-form'),
    roomName: el('bridge-room-name'),
    roomSearch: el('bridge-room-search'),
    roomSelection: el('bridge-room-selection'),
    roomMembers: el('bridge-room-members'),
    roomError: el('bridge-room-error'),
    roomCreate: el('bridge-room-create'),
  };
  let activeCartouche = null;
  let cartoucheReleaseTimer = 0;

  function escapeHtml(value) {
    return String(value ?? '')
      .replaceAll('&', '&amp;')
      .replaceAll('<', '&lt;')
      .replaceAll('>', '&gt;')
      .replaceAll('"', '&quot;')
      .replaceAll("'", '&#39;');
  }

  function iconHtml(name, className = 'cockpit-icon') {
    return `<svg class="${escapeHtml(className)}" aria-hidden="true"><use href="#bridge-icon-${escapeHtml(name)}"></use></svg>`;
  }

  function identityGlyphFor(slug, texture = textureForSlug(slug)) {
    const normalized = slugify(slug || texture?.slug);
    if (IDENTITY_GLYPHS[normalized]) return IDENTITY_GLYPHS[normalized];
    const pattern = String(texture?.pattern || '').toLowerCase();
    if (/camera|aperture/.test(pattern)) return 'camera';
    if (/book|memo|ledger/.test(pattern)) return 'book';
    if (/map|contour|parcel/.test(pattern)) return 'map';
    if (/cloud/.test(pattern)) return 'cloud';
    if (/network|packet|beam|radio/.test(pattern)) return 'network';
    if (/grid|panel|dashboard|scorecard/.test(pattern)) return 'grid';
    return 'activity';
  }

  function safeLinkHref(value) {
    const href = String(value || '').trim();
    if (!href) return '';
    if (/^(https?:|mailto:)/i.test(href)) return href;
    if (/^(\/|#)/.test(href)) return href;
    return '';
  }

  function renderMessageContent(value) {
    const text = String(value || '');
    const parser = window.marked?.marked || window.marked?.parse || window.marked;
    if (typeof parser !== 'function') return escapeHtml(text);
    const mentions = [];
    const mentionPattern = /(^|[\s([{])@([a-z0-9][a-z0-9_-]{1,48})\b/gi;
    const prepared = text.replace(mentionPattern, (match, prefix, slug) => {
      const agent = state.agents.find((item) => slugify(item.slug) === slugify(slug));
      if (!agent && slugify(slug) !== 'norman') return match;
      const token = `BRIDGEENTITYTOKEN${mentions.length}END`;
      mentions.push(entityCartoucheHtml(agent?.display_name || 'Norman', {
        slug: agent?.slug || 'norman',
        kind: 'bot',
        decorator: '@',
        mention: true,
      }));
      return `${prefix}${token}`;
    });
    const Renderer = window.marked?.Renderer;
    const renderer = Renderer ? new Renderer() : null;
    if (renderer) {
      renderer.html = (html) => escapeHtml(html);
      renderer.link = (href, title, content) => {
        const safeHref = safeLinkHref(href);
        if (!safeHref) return content;
        const titleAttribute = title ? ` title="${escapeHtml(title)}"` : '';
        const external = /^https?:/i.test(safeHref);
        return `<a href="${escapeHtml(safeHref)}"${titleAttribute}${external ? ' target="_blank" rel="noopener noreferrer"' : ''}>${content}</a>`;
      };
      renderer.image = (href, title, alt) => `<span class="cockpit-inline-media">[image: ${escapeHtml(alt || title || 'attachment')}]</span>`;
    }
    let rendered;
    try {
      rendered = parser(prepared, {
        renderer,
        gfm: true,
        breaks: false,
        headerIds: false,
        mangle: false,
      });
    } catch {
      return escapeHtml(text);
    }
    mentions.forEach((cartouche, index) => {
      rendered = rendered.replaceAll(`BRIDGEENTITYTOKEN${index}END`, cartouche);
    });
    return rendered;
  }

  function slugify(value) {
    return String(value || '')
      .trim()
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, '-')
      .replace(/^-+|-+$/g, '');
  }

  function truncate(value, limit = 58) {
    const text = String(value || '').replace(/\s+/g, ' ').trim();
    return text.length > limit ? `${text.slice(0, limit - 3)}...` : text;
  }

  function displaySlug(value) {
    return String(value || '')
      .split(/[-_]+/)
      .filter(Boolean)
      .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
      .join(' ');
  }

  function formatTime(value) {
    if (!value) return '';
    const numericEpoch = (
      (typeof value === 'number' && value < 1000000000000)
      || (typeof value === 'string' && /^\d{10}$/.test(value))
    );
    const normalized = numericEpoch ? Number(value) * 1000 : value;
    const parsed = new Date(normalized);
    if (Number.isNaN(parsed.getTime())) return '';
    const now = new Date();
    if (parsed.toDateString() === now.toDateString()) {
      return parsed.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });
    }
    return parsed.toLocaleDateString([], { month: 'short', day: 'numeric' });
  }

  function compactNumber(value) {
    const number = Number(value || 0);
    if (!Number.isFinite(number)) return '--';
    if (number >= 1000000) return `${(number / 1000000).toFixed(number >= 10000000 ? 0 : 1)}m`;
    if (number >= 1000) return `${(number / 1000).toFixed(number >= 10000 ? 0 : 1)}k`;
    return String(Math.round(number));
  }

  class BridgeRequestError extends Error {
    constructor(message, status, payload = null) {
      super(message);
      this.name = 'BridgeRequestError';
      this.status = status;
      this.payload = payload;
    }
  }

  async function fetchJson(url, options = {}) {
    const { timeoutMs = 15000, ...fetchOptions } = options;
    const timeoutSignal = typeof AbortSignal !== 'undefined' && typeof AbortSignal.timeout === 'function'
      ? AbortSignal.timeout(timeoutMs)
      : undefined;
    const response = await fetch(url, {
      cache: 'no-store',
      credentials: 'same-origin',
      headers: { Accept: 'application/json', ...(fetchOptions.headers || {}) },
      ...fetchOptions,
      signal: fetchOptions.signal || timeoutSignal,
    });
    if (!response.ok) {
      const raw = await response.text().catch(() => '');
      let payload = null;
      try {
        payload = raw ? JSON.parse(raw) : null;
      } catch (_error) {
        payload = null;
      }
      const detail = payload?.detail || payload?.message || raw;
      const message = response.status === 401
        ? 'Log in to sync and run this conversation.'
        : response.status === 403
          ? 'This account cannot perform that action.'
          : detail || `Request failed (${response.status}).`;
      throw new BridgeRequestError(message, response.status, payload);
    }
    return response.json();
  }

  function postJson(url, payload, options = {}) {
    return fetchJson(url, {
      ...options,
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
      body: JSON.stringify(payload || {}),
    });
  }

  function localConversationId(kind, principal, identity) {
    const suffix = kind === 'direct'
      ? `${slugify(principal)}-${slugify(identity)}`
      : `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
    return `local-${kind}-${suffix}`;
  }

  function normalizeLocalConversation(item) {
    if (!item || !['direct', 'room'].includes(item.kind) || !item.conversation_id) return null;
    return {
      ...item,
      principal_slug: slugify(item.principal_slug) || FALLBACK_GROUP.slug,
      domain_slug: slugify(item.domain_slug),
      direct_agent_slug: slugify(item.direct_agent_slug),
      member_slugs: [...new Set((item.member_slugs || []).map(slugify).filter(Boolean))],
      _local_only: true,
    };
  }

  function loadLocalConversations() {
    try {
      const stored = JSON.parse(window.localStorage.getItem(LOCAL_CONVERSATIONS_KEY) || '[]');
      if (!Array.isArray(stored)) return [];
      return stored.map(normalizeLocalConversation).filter(Boolean);
    } catch (_error) {
      return [];
    }
  }

  function saveLocalConversations() {
    try {
      const local = state.conversations
        .filter((item) => item._local_only)
        .map((item) => ({
          conversation_id: item.conversation_id,
          kind: item.kind,
          title: item.title,
          principal_slug: item.principal_slug,
          domain_slug: item.domain_slug || '',
          direct_agent_slug: item.direct_agent_slug || '',
          member_slugs: item.member_slugs || [],
          created_at: item.created_at,
          updated_at: item.updated_at,
        }));
      window.localStorage.setItem(LOCAL_CONVERSATIONS_KEY, JSON.stringify(local));
    } catch (_error) {
      // Private browsing and locked-down webviews can reject local storage.
    }
  }

  function conversationIdentity(item) {
    if (item.kind === 'direct') {
      return `direct:${slugify(item.principal_slug)}:${slugify(item.direct_agent_slug)}`;
    }
    return `room:${item.conversation_id}`;
  }

  function mergeConversations(remote = [], local = []) {
    const merged = new Map();
    local.map(normalizeLocalConversation).filter(Boolean).forEach((item) => {
      merged.set(conversationIdentity(item), item);
    });
    remote.forEach((item) => {
      merged.set(conversationIdentity(item), { ...item, _local_only: false });
    });
    state.conversations = [...merged.values()].sort((left, right) => (
      new Date(right.updated_at || right.created_at || 0)
      - new Date(left.updated_at || left.created_at || 0)
    ));
    saveLocalConversations();
    return state.conversations;
  }

  function makeLocalConversation({
    kind,
    title,
    principalSlug,
    domainSlug = '',
    directAgentSlug = '',
    memberSlugs = [],
  }) {
    const now = new Date().toISOString();
    return normalizeLocalConversation({
      conversation_id: localConversationId(kind, principalSlug, directAgentSlug || title),
      kind,
      title,
      principal_slug: principalSlug || FALLBACK_GROUP.slug,
      domain_slug: domainSlug,
      direct_agent_slug: directAgentSlug,
      member_slugs: memberSlugs,
      created_at: now,
      updated_at: now,
    });
  }

  function persistConversationLocally(conversation) {
    const identity = conversationIdentity(conversation);
    const index = state.conversations.findIndex((item) => conversationIdentity(item) === identity);
    if (index >= 0) state.conversations.splice(index, 1, conversation);
    else state.conversations.unshift(conversation);
    saveLocalConversations();
    return conversation;
  }

  function replaceConversation(previous, next) {
    const index = state.conversations.findIndex(
      (item) => item.conversation_id === previous.conversation_id,
    );
    if (index >= 0) state.conversations.splice(index, 1, { ...next, _local_only: false });
    else state.conversations.unshift({ ...next, _local_only: false });
    if (state.selectedConversationId === previous.conversation_id) {
      state.selectedConversationId = next.conversation_id;
    }
    saveLocalConversations();
    renderAll();
  }

  function persistenceUnavailable(error) {
    return error instanceof BridgeRequestError
      && [401, 403, 404, 409, 503].includes(error.status);
  }

  function currentGroup() {
    return state.groups.find((group) => group.id === state.group) || state.groups[0] || FALLBACK_GROUP;
  }

  function currentDomain() {
    return currentGroup().domains.find((domain) => domain.slug === state.domain) || null;
  }

  function jobMetadata(job) {
    return job?.metadata || job?.metadata_json || {};
  }

  function jobContract(job) {
    return job?.contract || job?.contract_json || {};
  }

  function jobObjective(job) {
    return String(job?.objective || jobContract(job).objective || '').trim();
  }

  function eventPayload(event) {
    const payload = event?.payload ?? event?.payload_json ?? {};
    if (typeof payload !== 'string') return payload || {};
    try {
      return JSON.parse(payload);
    } catch (_error) {
      return {};
    }
  }

  function jobEvents(job) {
    return state.jobActivities[job?.job_id]?.events || [];
  }

  function selectedConversation() {
    return state.conversations.find(
      (item) => item.conversation_id === state.selectedConversationId,
    ) || null;
  }

  function beginSignIn() {
    try {
      window.sessionStorage.setItem(AUTH_RESUME_KEY, JSON.stringify({
        draft: nodes.message.value,
        group: state.group,
        domain: state.domain,
        conversationId: state.selectedConversationId,
        selectedAgent: state.selectedAgent,
        recipients: state.selectedRecipients,
      }));
    } catch (_error) {
      // Session storage can be unavailable in locked-down webviews.
    }
    const returnTo = `${window.location.pathname}${window.location.search}`;
    window.location.assign(`/login.html?next=${encodeURIComponent(returnTo)}`);
  }

  function restoreAfterSignIn() {
    if (state.authRequired) return;
    let resume = null;
    try {
      resume = JSON.parse(window.sessionStorage.getItem(AUTH_RESUME_KEY) || 'null');
      window.sessionStorage.removeItem(AUTH_RESUME_KEY);
    } catch (_error) {
      resume = null;
    }
    if (!resume) return;
    if (state.groups.some((item) => item.id === resume.group)) state.group = resume.group;
    state.domain = slugify(resume.domain);
    const conversation = state.conversations.find(
      (item) => item.conversation_id === resume.conversationId,
    );
    if (conversation) {
      state.selectedConversationId = conversation.conversation_id;
      state.selectedAgent = conversation.direct_agent_slug || '';
      state.selectedRecipients = [...(conversation.member_slugs || [])];
      state.view = conversation.kind === 'direct' ? 'agent' : 'room';
    } else if (resume.selectedAgent) {
      state.selectedAgent = slugify(resume.selectedAgent);
      state.selectedRecipients = (resume.recipients || []).map(slugify).filter(Boolean);
      state.view = 'agent';
    }
    nodes.message.value = String(resume.draft || '');
    resizeComposer({ immediate: true });
  }

  function conversationJob(job, conversation) {
    const metadata = jobMetadata(job);
    if (metadata.bridge_conversation_id) {
      return metadata.bridge_conversation_id === conversation?.conversation_id;
    }
    if (conversation?.kind !== 'direct') return false;
    const recipients = metadata.recipients || [];
    return [metadata.agent, metadata.target_agent, ...recipients]
      .map(slugify)
      .includes(slugify(conversation.direct_agent_slug));
  }

  function latestConversationJob(conversation) {
    return state.jobs.find((job) => conversationJob(job, conversation)) || null;
  }

  function isBridgeJob(job) {
    const metadata = jobMetadata(job);
    return metadata.source === 'norman_bridge' || Boolean(metadata.bridge_conversation_id);
  }

  function isPendingJob(job) {
    return ['queued', 'pending', 'accepted', 'created', 'waiting'].includes(
      String(job?.status || '').toLowerCase(),
    );
  }

  function isStalePendingJob(job, staleAfterMs = 30 * 60 * 1000) {
    if (!isPendingJob(job)) return false;
    const observedAt = Date.parse(job?.updated_at || job?.created_at || '');
    return Number.isFinite(observedAt) && Date.now() - observedAt > staleAfterMs;
  }

  function recentBridgeRuntimeJobs() {
    return state.jobs.filter((job) => (
      isBridgeJob(job)
      && (!isPendingJob(job) || !isStalePendingJob(job) || job.job_id === state.prompt.jobId)
    ));
  }

  function normalizeGroups(estate) {
    const principals = (estate?.principals || []).filter((item) => item.is_active !== false);
    if (!principals.length) return [FALLBACK_GROUP];
    return principals.map((principal) => ({
      id: slugify(principal.slug || principal.display_name),
      slug: principal.slug || slugify(principal.display_name),
      label: principal.display_name || principal.slug || 'Workspace',
      mark: String(principal.display_name || principal.slug || 'W').slice(0, 1).toUpperCase(),
      kind: principal.kind || 'principal',
      policy: `${principal.kind || 'Principal'} boundary`,
      domains: (principal.domains || []).map((domain) => ({
        ...domain,
        slug: slugify(domain.slug || domain.display_name),
        display_name: domain.display_name || domain.slug || 'Lane',
      })),
    }));
  }

  function normalizeAgents(estate) {
    const merged = new Map();
    for (const principal of estate?.principals || []) {
      const principalId = slugify(principal.slug || principal.display_name);
      const services = principal.services || [];
      for (const bot of principal.bots || []) {
        const service = services.find((item) => (
          slugify(item.bot_name) === slugify(bot.display_name)
          || slugify(item.slug) === slugify(bot.slug)
        ));
        const agent = {
          ...bot,
          principal_id: principalId,
          principal_slug: principal.slug,
          domain_slug: slugify(bot.domain_name),
          console_url: service?.console_url_tailnet || service?.console_url || '',
        };
        merged.set(slugify(agent.slug || agent.display_name), agent);
      }
      for (const service of services.filter((item) => item.console_url || item.console_url_tailnet)) {
        const key = slugify(service.bot_name || service.slug || service.display_name);
        if (merged.has(key)) continue;
        merged.set(key, {
          slug: service.slug,
          display_name: service.bot_name || service.display_name,
          class_name: service.kind || 'service',
          domain_name: service.domain_name || '',
          domain_slug: slugify(service.domain_name),
          principal_id: principalId,
          principal_slug: principal.slug,
          console_url: service.console_url_tailnet || service.console_url || '',
        });
      }
    }
    for (const heartbeat of state.heartbeats) {
      const key = slugify(heartbeat.agent);
      if (merged.has(key)) continue;
      merged.set(key, {
        slug: key,
        display_name: heartbeat.agent,
        class_name: heartbeat.profile || 'console',
        domain_name: heartbeat.host || '',
        domain_slug: '',
        principal_id: state.groups[0]?.id || FALLBACK_GROUP.id,
        principal_slug: state.groups[0]?.slug || FALLBACK_GROUP.slug,
        console_url: heartbeat.href || '',
      });
    }
    if (!merged.has('norman')) {
      const group = state.groups[0] || FALLBACK_GROUP;
      merged.set('norman', {
        ...FALLBACK_NORMAN,
        principal_id: group.id,
        principal_slug: group.slug,
      });
    }
    return [...merged.values()].sort((a, b) => (
      String(a.display_name).localeCompare(String(b.display_name))
    ));
  }

  function mergeCatalogAgents(agents) {
    const merged = new Map(
      (agents || []).map((agent) => [slugify(agent.slug || agent.display_name), agent]),
    );
    const group = state.groups[0] || FALLBACK_GROUP;
    for (const identity of state.textureCatalog || []) {
      const slug = slugify(identity.slug);
      if (!slug || merged.has(slug)) continue;
      const identityGroup = state.groups.find(
        (candidate) => slugify(candidate.slug) === slugify(identity.group),
      ) || group;
      merged.set(slug, {
        slug,
        display_name: displaySlug(identity.slug),
        class_name: 'tui station',
        domain_name: displaySlug(identity.group || ''),
        domain_slug: '',
        principal_id: identityGroup.id,
        principal_slug: identityGroup.slug,
        console_url: '',
        directory_source: 'identity-catalog',
      });
    }
    if (!merged.has('norman')) {
      merged.set('norman', {
        ...FALLBACK_NORMAN,
        principal_id: group.id,
        principal_slug: group.slug,
      });
    }
    return [...merged.values()].sort((a, b) => {
      if (slugify(a.slug) === 'norman') return -1;
      if (slugify(b.slug) === 'norman') return 1;
      return String(a.display_name).localeCompare(String(b.display_name));
    });
  }

  function provisionalAgents() {
    const group = state.groups[0] || FALLBACK_GROUP;
    return Object.keys(IDENTITY_GLYPHS).map((slug) => ({
      slug,
      display_name: displaySlug(slug),
      class_name: slug === 'norman' ? 'coordinator' : 'tui station',
      domain_name: '',
      domain_slug: '',
      principal_id: group.id,
      principal_slug: group.slug,
      console_url: slug === 'norman' ? '/bot/norman/' : '',
      directory_source: 'embedded-identity',
    })).sort((a, b) => {
      if (a.slug === 'norman') return -1;
      if (b.slug === 'norman') return 1;
      return a.display_name.localeCompare(b.display_name);
    });
  }

  function jobGroup(job) {
    const metadata = jobMetadata(job);
    const explicit = slugify(metadata.principal || metadata.realm || metadata.group);
    if (state.groups.some((group) => group.id === explicit || slugify(group.slug) === explicit)) {
      return state.groups.find((group) => group.id === explicit || slugify(group.slug) === explicit).id;
    }
    const recipients = metadata.recipients || [];
    const target = slugify(metadata.agent || metadata.target_agent || recipients[0]);
    const agent = state.agents.find((item) => slugify(item.slug) === target);
    return agent?.principal_id || state.groups[0]?.id || FALLBACK_GROUP.id;
  }

  function jobDomain(job) {
    const metadata = jobMetadata(job);
    return slugify(metadata.domain || metadata.lane || metadata.room);
  }

  function heartbeatFor(agent) {
    const keys = new Set([slugify(agent.slug), slugify(agent.display_name)]);
    return state.heartbeats.find((item) => keys.has(slugify(item.agent)));
  }

  function filteredJobs() {
    return state.jobs.filter((job) => {
      const conversation = selectedConversation();
      if (conversation && !conversationJob(job, conversation)) return false;
      if (jobGroup(job) !== state.group) return false;
      if (state.domain && jobDomain(job) && jobDomain(job) !== state.domain) return false;
      if (state.selectedAgent) {
        const metadata = jobMetadata(job);
        const recipients = metadata.recipients || [];
        const values = [metadata.agent, metadata.target_agent, ...recipients].map(slugify);
        if (!values.includes(slugify(state.selectedAgent))) return false;
      }
      if (!state.search) return true;
      return `${jobObjective(job)} ${job.status} ${job.job_id}`.toLowerCase().includes(state.search);
    });
  }

  function filteredAgents() {
    return state.agents.filter((agent) => {
      if (agent.principal_id !== state.group) return false;
      if (state.domain && agent.domain_slug && agent.domain_slug !== state.domain) return false;
      if (!state.search) return true;
      return `${agent.display_name} ${agent.class_name} ${agent.domain_name}`
        .toLowerCase()
        .includes(state.search);
    });
  }

  function attentionItems() {
    const blocked = state.jobs.filter((job) => (
      ['blocked', 'failed', 'waiting_approval', 'error'].includes(String(job.status).toLowerCase())
    ));
    return [
      ...state.approvals.map((item) => ({
        id: `approval-${item.id}`,
        type: 'command_approval',
        approval: item,
        title: item.command_text || 'Approval requested',
        detail: item.reason || item.command_class || 'Command approval',
        group: slugify(item.principal || item.realm) || state.groups[0]?.id,
      })),
      ...blocked.map((job) => ({
        id: job.job_id,
        type: job.status === 'waiting_approval' ? 'runtime_approval' : 'job',
        title: truncate(jobObjective(job), 82),
        detail: `${job.status}: ${job.last_error || job.job_id}`,
        group: jobGroup(job),
        job,
        job_id: job.job_id,
      })),
    ];
  }

  function profileForTexture(texture) {
    const group = slugify(texture?.group || currentGroup().slug);
    if (group === 'norman' || slugify(texture?.slug) === 'norman') return 'tide';
    if (group === 'work') return 'blueprint';
    if (group === 'personal') return 'dusk';
    if (['shared', 'infrastructure', 'infra'].includes(group)) return 'ember';
    if (group === 'private') return 'slate';
    return 'tide';
  }

  function fontRoles(fontDescription = '') {
    const name = String(fontDescription).toLowerCase();
    const sans = '"IBM Plex Sans", "Segoe UI Variable Text", "Segoe UI", sans-serif';
    const condensed = '"IBM Plex Sans Condensed", "Arial Narrow", "Segoe UI", sans-serif';
    const mono = '"IBM Plex Mono", "JetBrains Mono", "SFMono-Regular", Consolas, monospace';
    const serif = '"IBM Plex Serif", "Iowan Old Style", Georgia, serif';
    if (name.includes('poppins') && (name.includes('mono') || name.includes('jetbrains'))) {
      return {
        ui: '"Poppins", "IBM Plex Sans", sans-serif',
        brand: '"Poppins", "IBM Plex Sans Condensed", sans-serif',
        reading: '"Poppins", "IBM Plex Sans", sans-serif',
        label: mono,
        mono,
      };
    }
    if ((name.includes('serif') || name.includes('georgia')) && name.includes('mono')) {
      return { ui: sans, brand: serif, reading: serif, label: mono, mono };
    }
    if (name.includes('mono') || name.includes('jetbrains')) {
      return { ui: mono, brand: mono, reading: mono, label: mono, mono };
    }
    if (name.includes('serif') || name.includes('georgia') || name.includes('editorial')) {
      return {
        ui: name.includes('poppins') ? '"Poppins", "IBM Plex Sans", sans-serif' : sans,
        brand: serif,
        reading: serif,
        label: condensed,
        mono,
      };
    }
    if (name.includes('condensed') || name.includes('bahnschrift')) {
      return { ui: sans, brand: condensed, reading: sans, label: condensed, mono };
    }
    if (name.includes('poppins')) {
      return {
        ui: '"Poppins", "IBM Plex Sans", sans-serif',
        brand: name.includes('display') ? '"Poppins", "IBM Plex Sans Condensed", sans-serif' : '"Poppins", "IBM Plex Sans", sans-serif',
        reading: name.includes('georgia') ? serif : '"Poppins", "IBM Plex Sans", sans-serif',
        label: condensed,
        mono,
      };
    }
    return { ui: sans, brand: condensed, reading: sans, label: condensed, mono };
  }

  function identityFontRoles(slug, texture = textureForSlug(slug)) {
    const normalized = slugify(slug || texture?.slug);
    const group = slugify(texture?.group);
    const sans = '"IBM Plex Sans", "Segoe UI Variable Text", "Segoe UI", Helvetica, Arial, sans-serif';
    const condensed = '"IBM Plex Sans Condensed", "Bahnschrift", "Segoe UI Variable Text", "Segoe UI", Helvetica, Arial, sans-serif';
    const mono = '"IBM Plex Mono", "SFMono-Regular", Menlo, Consolas, monospace';
    const serif = '"Iowan Old Style", "Palatino Linotype", "Book Antiqua", Georgia, serif';
    const poppins = '"Poppins", "IBM Plex Sans", "Segoe UI Variable Text", "Segoe UI", Helvetica, Arial, sans-serif';
    if (normalized === 'null-agent') {
      return { ui: sans, body: sans, brand: mono, reading: sans, label: mono, wide: condensed, mono };
    }
    if (normalized === 'gold-book') {
      return { ui: sans, body: sans, brand: serif, reading: serif, label: condensed, wide: condensed, mono };
    }
    if (group === 'work' || ['parkergale', 'pefb'].includes(normalized)) {
      return { ui: poppins, body: poppins, brand: poppins, reading: poppins, label: poppins, wide: poppins, mono };
    }
    const inferred = fontRoles(texture?.font);
    return {
      ...inferred,
      body: inferred.ui,
      wide: inferred.label,
    };
  }

  function styleVariantFor(slug, texture = textureForSlug(slug)) {
    const normalized = slugify(slug || texture?.slug);
    if (STYLE_VARIANT_OVERRIDES[normalized]) return STYLE_VARIANT_OVERRIDES[normalized];
    const pattern = String(texture?.pattern || '').toLowerCase();
    if (/book|memo|editor|ledger/.test(pattern)) return 'editorial';
    if (/scan|signal|pixel|pin|grid/.test(pattern)) return 'signal';
    if (/stone|metal|alloy|platinum|facet/.test(pattern)) return 'alloy';
    if (/canopy|grove|field|aperture/.test(pattern)) return 'grove';
    return 'anchor';
  }

  function identityContract(slug = '') {
    const texture = textureForSlug(slug) || textureForSelection();
    const resolvedSlug = slugify(slug || texture?.slug || 'norman');
    const agent = state.agents.find((item) => slugify(item.slug) === resolvedSlug);
    const label = agent?.display_name || displaySlug(resolvedSlug || 'norman');
    const group = slugify(texture?.group || agent?.principal_slug || currentGroup().slug || 'agents');
    const mark = String(texture?.mark || label.slice(0, 2) || 'N').slice(0, 3).toUpperCase();
    return {
      slug: resolvedSlug,
      label,
      group,
      mark,
      decorator: 'TUI',
      kind: 'tui',
      styleVariant: styleVariantFor(resolvedSlug, texture),
      fonts: identityFontRoles(resolvedSlug, texture),
      texture,
    };
  }

  function entityCartoucheHtml(label, options = {}) {
    const identity = identityContract(options.slug || label);
    const kind = options.kind || identity.kind || 'name';
    const group = options.group || identity.group || 'agents';
    const mark = String(options.mark || identity.mark || label.slice(0, 2) || 'N').slice(0, 3).toUpperCase();
    const decorator = options.decorator || ({
      host: 'NET',
      service: 'SVC',
      tui: 'TUI',
      bot: '◈',
      person: '◦',
      location: '⌂',
    }[kind] || '·');
    const glyph = options.glyph === false || identity.slug === 'artmonster'
      ? ''
      : `<span class="entity-cartouche__glyph">${iconHtml(identityGlyphFor(identity.slug, identity.texture))}</span>`;
    return `<span class="entity-cartouche" data-kind="${escapeHtml(kind)}" data-tone="${escapeHtml(options.tone || kind)}"
      data-group="${escapeHtml(group)}" data-entity-key="${escapeHtml(slugify(options.slug || label))}"
      data-mark="${escapeHtml(mark)}" data-decorator="${escapeHtml(decorator)}"
      ${options.mention ? 'data-mention="true"' : ''} ${options.compact === false ? '' : 'data-compact="true"'}
      style="${escapeHtml(identityStyle(identity.slug))}">${glyph}<span class="entity-cartouche__label">${escapeHtml(label)}</span></span>`;
  }

  function patternDetail(texture) {
    const pattern = String(texture?.pattern || '').toLowerCase();
    let factors = [0.48, 0.24, 0.11, 0.38, 0.08];
    if (/scan|pixel|pin|grid/.test(pattern)) factors = [0.56, 0.28, 0.18, 0.40, 0.14];
    else if (/weave|mesh|lattice|plaid/.test(pattern)) factors = [0.54, 0.34, 0.13, 0.36, 0.10];
    else if (/stone|book|platinum|memo/.test(pattern)) factors = [0.44, 0.30, 0.08, 0.52, 0.14];
    else if (/aperture|contour|field|sweep/.test(pattern)) factors = [0.50, 0.22, 0.14, 0.34, 0.10];
    const alpha = Number(texture?.texture_alpha || 0.4);
    return factors.map((factor) => Math.max(0, Math.min(0.4, alpha * factor)));
  }

  function textureForSelection() {
    if (state.selectedAgent) {
      const direct = state.textureCatalog.find((item) => slugify(item.slug) === slugify(state.selectedAgent));
      if (direct) return direct;
    }
    const selected = state.agents.find((agent) => slugify(agent.slug) === slugify(state.selectedAgent));
    if (selected) {
      const match = state.textureCatalog.find((item) => slugify(item.slug) === slugify(selected.slug));
      if (match) return match;
    }
    const selectedJob = state.activity?.job
      || state.jobs.find((job) => job.job_id === state.selectedJobId);
    const recipient = (jobMetadata(selectedJob).recipients || [])[0]
      || jobMetadata(selectedJob).agent
      || jobMetadata(selectedJob).target_agent;
    if (recipient) {
      const match = state.textureCatalog.find((item) => slugify(item.slug) === slugify(recipient));
      if (match) return match;
    }
    const group = currentGroup();
    return state.textureCatalog.find((item) => slugify(item.group) === slugify(group.slug))
      || state.textureCatalog.find((item) => slugify(item.slug) === 'norman')
      || null;
  }

  function textureForSlug(slug) {
    const normalized = slugify(slug);
    return state.textureCatalog.find((item) => slugify(item.slug) === normalized) || null;
  }

  function identityStyle(slug) {
    const texture = textureForSlug(slug) || textureForSelection();
    const colors = texture?.colors || ['#5fd2c4', '#76a8ff', '#d8b25b'];
    const fonts = identityFontRoles(slug, texture);
    const glow = texture?.glow || [50, 12];
    const motionSeed = [...String(slug || texture?.slug || 'norman')]
      .reduce((total, character) => total + character.charCodeAt(0), 0);
    return [
      `--message-accent:${colors[0]}`,
      `--message-accent-2:${colors[1] || colors[0]}`,
      `--message-accent-3:${colors[2] || colors[1] || colors[0]}`,
      `--message-font:${fonts.reading}`,
      `--message-label-font:${fonts.brand}`,
      `--message-ui-font:${fonts.ui}`,
      `--message-wide-font:${fonts.wide}`,
      `--message-mono-font:${fonts.mono}`,
      `--identity-angle:${Number(texture?.angle ?? 96)}deg`,
      `--identity-cross-angle:${Number(texture?.cross ?? 6)}deg`,
      `--identity-grain:${Math.max(10, Number(texture?.grain || 24))}px`,
      `--identity-cross-grain:${Math.max(14, Number(texture?.cross_grain || 44))}px`,
      `--identity-glow-x:${Number(glow[0] ?? 50)}%`,
      `--identity-glow-y:${Number(glow[1] ?? 12)}%`,
      `--identity-alpha:${Number(texture?.texture_alpha || 0.4)}`,
      `--identity-drift:${12 + (motionSeed % 11)}s`,
      `--identity-delay:-${motionSeed % 13}s`,
    ].join(';');
  }

  function directoryGroup(agent) {
    const identity = identityContract(agent.slug);
    const configuredBoundary = state.groups.length > 1 || currentGroup().id !== FALLBACK_GROUP.id;
    const raw = configuredBoundary
      ? agent.domain_name || agent.domain_slug || identity.group
      : identity.group || agent.domain_name || 'other';
    let key = slugify(raw) || 'other';
    const labels = {
      norman: 'Coordinator',
      personal: 'Personal',
      work: 'Work',
      shared: 'Infrastructure',
      infrastructure: 'Infrastructure',
      infra: 'Infrastructure',
      private: 'Private',
      other: 'Other',
    };
    if (!configuredBoundary && !labels[key]) key = 'other';
    return {
      key,
      label: labels[key] || displaySlug(raw),
      rank: {
        norman: 0,
        personal: 10,
        work: 20,
        shared: 30,
        infrastructure: 30,
        infra: 30,
        private: 40,
        other: 90,
      }[key] ?? 50,
    };
  }

  function groupedAgents(agents) {
    const groups = new Map();
    for (const agent of agents) {
      const group = directoryGroup(agent);
      if (!groups.has(group.key)) groups.set(group.key, { ...group, agents: [] });
      groups.get(group.key).agents.push(agent);
    }
    return [...groups.values()]
      .map((group) => ({
        ...group,
        agents: group.agents.sort((a, b) => {
          const aOnline = heartbeatFor(a) ? 0 : 1;
          const bOnline = heartbeatFor(b) ? 0 : 1;
          return aOnline - bOnline || String(a.display_name).localeCompare(String(b.display_name));
        }),
      }))
      .sort((a, b) => a.rank - b.rank || a.label.localeCompare(b.label));
  }

  function botIdentityTileHtml(agent, { mini = false, hero = false } = {}) {
    const identity = identityContract(agent.slug);
    const motion = textureMotionSignature(identity.texture);
    const presence = heartbeatFor(agent) ? 'online' : 'known';
    return `<span class="bridge-simple-cartouche${mini ? ' bridge-simple-cartouche--mini' : ''}${hero ? ' bridge-simple-cartouche--hero' : ''}"
      data-group="${escapeHtml(identity.group)}"
      data-entity-key="${escapeHtml(identity.slug)}"
      data-variant="${escapeHtml(identity.styleVariant)}"
      data-pattern="${escapeHtml(slugify(identity.texture?.pattern || 'identity-weave'))}"
      data-motion="${escapeHtml(motion.family)}"
      data-presence="${presence}"
      aria-hidden="true" style="${escapeHtml(identityStyle(agent.slug))}">
      <span class="bridge-simple-cartouche__mark">${escapeHtml(identity.mark || String(agent.display_name).slice(0, 2).toUpperCase())}</span>
      <span class="bridge-simple-cartouche__glyph">${iconHtml(identityGlyphFor(identity.slug, identity.texture))}</span>
    </span>`;
  }

  function exciteCartouche(tile, energy = 0.45, x = 50, y = 50, hold = 620) {
    if (!tile || window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
    if (activeCartouche && activeCartouche !== tile) {
      delete activeCartouche.dataset.reactive;
      activeCartouche.style.removeProperty('--cartouche-energy');
    }
    activeCartouche = tile;
    tile.style.setProperty('--cartouche-x', `${textureClamp(x, 4, 96).toFixed(1)}%`);
    tile.style.setProperty('--cartouche-y', `${textureClamp(y, 4, 96).toFixed(1)}%`);
    tile.style.setProperty('--cartouche-energy', textureClamp(energy, 0, 1).toFixed(3));
    tile.dataset.reactive = 'true';
    window.clearTimeout(cartoucheReleaseTimer);
    cartoucheReleaseTimer = window.setTimeout(() => {
      if (activeCartouche === tile) activeCartouche = null;
      delete tile.dataset.reactive;
      tile.style.setProperty('--cartouche-energy', '0');
    }, hold);
  }

  function activeIdentityTile() {
    if (nodes.roomDialog?.open) {
      return nodes.roomMembers.querySelector('input:checked')?.closest('.bridge-room-member')
        ?.querySelector('.bridge-simple-cartouche')
        || nodes.roomMembers.querySelector('.bridge-room-member:not([hidden]) .bridge-simple-cartouche');
    }
    const slug = state.selectedAgent || 'norman';
    return nodes.agents.querySelector(`[data-agent="${CSS.escape(slug)}"] .bridge-simple-cartouche`);
  }

  function roomIdentityStackHtml(memberSlugs) {
    const members = (memberSlugs || []).map((slug) => (
      state.agents.find((agent) => slugify(agent.slug) === slugify(slug))
    )).filter(Boolean).slice(0, 3);
    if (!members.length) {
      return `<span class="bridge-simple-cartouche bridge-simple-cartouche--room" aria-hidden="true">${iconHtml('users')}</span>`;
    }
    return `<span class="bridge-room-stack" aria-hidden="true">
      ${members.map((agent) => botIdentityTileHtml(agent, { mini: true })).join('')}
    </span>`;
  }

  function responseIdentity(job) {
    const metadata = jobMetadata(job);
    const recipient = (metadata.recipients || [])[0] || metadata.agent || metadata.target_agent;
    const agent = state.agents.find((item) => slugify(item.slug) === slugify(recipient));
    return {
      author: agent?.display_name || (recipient ? recipient.replaceAll('-', ' ') : 'Norman'),
      slug: agent?.slug || recipient || 'norman',
    };
  }

  function applyTextureIdentity() {
    const texture = textureForSelection();
    const colors = texture?.colors || ['#5fd2c4', '#76a8ff', '#d8b25b'];
    const profileName = profileForTexture(texture);
    const profile = PROFILE_PALETTES[profileName];
    const identity = identityContract(texture?.slug || state.selectedAgent || 'norman');
    const motion = textureMotionSignature(texture);
    const fonts = identity.fonts;
    const [lineOpacity, crossOpacity, dotOpacity, railOpacity, bandOpacity] = patternDetail(texture);
    const glow = texture?.glow || [24, 9];
    root.style.setProperty('--agent-accent', colors[0] || '#5fd2c4');
    root.style.setProperty('--agent-accent-2', colors[1] || colors[0] || '#76a8ff');
    root.style.setProperty('--agent-accent-3', colors[2] || colors[1] || '#d8b25b');
    root.style.setProperty('--texture-angle', `${Number(texture?.angle || 96)}deg`);
    root.style.setProperty('--texture-cross-angle', `${Number(texture?.cross || 6)}deg`);
    root.style.setProperty('--texture-spacing', `${Number(texture?.grain || 24)}px`);
    root.style.setProperty('--texture-cross-spacing', `${Number(texture?.cross_grain || 48)}px`);
    root.style.setProperty('--texture-glow-x', `${Number(glow[0] || 50)}%`);
    root.style.setProperty('--texture-glow-y', `${Number(glow[1] || 12)}%`);
    root.style.setProperty('--texture-alpha', String(Number(texture?.texture_alpha || 0.4)));
    root.style.setProperty('--identity-line-opacity', String(lineOpacity));
    root.style.setProperty('--identity-cross-opacity', String(crossOpacity));
    root.style.setProperty('--identity-dot-opacity', String(dotOpacity));
    root.style.setProperty('--identity-rail-opacity', String(railOpacity));
    root.style.setProperty('--identity-band-opacity', String(bandOpacity));
    root.style.setProperty('--font-ui', fonts.ui);
    root.style.setProperty('--font-body', fonts.body);
    root.style.setProperty('--font-ui-wide', fonts.wide);
    root.style.setProperty('--font-brand', fonts.brand);
    root.style.setProperty('--font-reading', fonts.reading);
    root.style.setProperty('--font-label', fonts.label);
    root.style.setProperty('--font-mono', fonts.mono);
    root.style.setProperty('--profile-bg', profile.bg);
    root.style.setProperty('--profile-soft', profile.soft);
    root.style.setProperty('--profile-surface', profile.surface);
    root.style.setProperty('--profile-surface-2', profile.surface2);
    root.style.setProperty('--profile-surface-3', profile.surface3);
    root.style.setProperty('--profile-border', profile.border);
    root.style.setProperty('--profile-border-strong', profile.borderStrong);
    root.style.setProperty('--profile-text', profile.text);
    root.style.setProperty('--profile-muted', profile.muted);
    root.style.setProperty('--profile-body-start', profile.bodyStart);
    root.style.setProperty('--profile-body-mid', profile.bodyMid);
    root.style.setProperty('--profile-body-end', profile.bodyEnd);
    root.dataset.identitySlug = slugify(texture?.slug || 'norman');
    root.dataset.identityPattern = slugify(texture?.pattern || 'prime-orbit-weave');
    root.dataset.identityMotion = motion.family;
    root.dataset.identityProfile = profileName;
    root.dataset.identityFont = slugify(texture?.font || 'ibm-plex-sans');
    root.dataset.agentVariant = identity.styleVariant;
    state.texture.lines = [];
  }

  function aggregateState() {
    const phase = state.prompt.phase;
    if (phase === 'failed') return 'degraded';
    if (phase === 'blocked') return 'blocked';
    if (phase === 'running') return 'working';
    if (['submitting', 'queued'].includes(phase)) return 'active';
    if (state.view.includes('attention') && attentionItems().length) return 'blocked';
    if (state.jobs.length || state.agents.length) return 'ready';
    return 'idle';
  }

  function promptPhaseForStatus(status) {
    const value = String(status || '').toLowerCase();
    if (['done', 'completed', 'complete', 'succeeded', 'verified'].includes(value)) return 'complete';
    if (['failed', 'error', 'crashed', 'canceled', 'cancelled'].includes(value)) return 'failed';
    if (['blocked', 'waiting_approval', 'approval_required'].includes(value)) return 'blocked';
    if (['running', 'executing', 'planning', 'started'].includes(value)) return 'running';
    if (['queued', 'pending', 'accepted', 'created', 'waiting'].includes(value)) return 'queued';
    return '';
  }

  function promptBusy() {
    return ['submitting', 'queued', 'running'].includes(state.prompt.phase);
  }

  function resumeTopicPrompts() {
    const conversation = selectedConversation();
    const stationSlug = conversation?.kind === 'direct'
      ? slugify(conversation.direct_agent_slug)
      : '';
    if (!stationSlug) return [];
    const turns = state.stationHistory[stationSlug]?.items || [];
    const seen = new Set();
    return [...turns].reverse().flatMap((turn) => {
      const prompt = String(turn.prompt || '').replace(/\s+/g, ' ').trim();
      const key = prompt.toLowerCase();
      if (!prompt || seen.has(key)) return [];
      seen.add(key);
      return [prompt];
    }).slice(0, 3);
  }

  function renderResumePrompts() {
    const prompts = resumeTopicPrompts();
    const shouldShow = !state.authRequired
      && !promptBusy()
      && !nodes.message.value.trim()
      && prompts.length > 0;
    nodes.resumePrompts.hidden = !shouldShow;
    if (!shouldShow) {
      nodes.resumePrompts.innerHTML = '';
      return;
    }
    nodes.resumePrompts.innerHTML = `<span>Continue</span>${prompts.map((prompt) => `
      <button type="button" class="cockpit-resume-prompt" data-resume-prompt="${escapeHtml(prompt)}"
        title="Continue this topic">${escapeHtml(truncate(prompt, 54))}</button>
    `).join('')}`;
  }

  function draftResumePrompt(prompt) {
    const topic = String(prompt || '').trim();
    if (!topic || nodes.message.value.trim() || promptBusy()) return;
    nodes.message.value = `Continue from our last discussion: ${topic}`;
    resizeComposer({ immediate: true });
    updateComposerState();
    nodes.message.focus();
  }

  function updateComposerState() {
    const phase = state.prompt.phase;
    const hasText = Boolean(nodes.message.value.trim());
    const busy = promptBusy();
    const stationDirect = selectedConversation()?.kind === 'direct';
    const runtimeUnavailable = !stationDirect && state.bootstrapped && state.worker._available === false;
    nodes.message.disabled = state.authRequired;
    nodes.send.disabled = state.authRequired || runtimeUnavailable || !hasText || busy;
    nodes.composer.dataset.promptState = phase;
    nodes.composer.setAttribute('aria-busy', String(busy));
    nodes.send.dataset.promptState = phase;
    const labels = {
      submitting: 'Sending message',
      queued: 'Message queued',
      running: 'Norman is working',
      blocked: 'Prompt needs attention',
      failed: state.prompt.error ? `Prompt failed: ${state.prompt.error}` : 'Prompt failed',
    };
    nodes.composeHint.textContent = state.authRequired
      ? 'Log in to sync and run conversations'
      : runtimeUnavailable ? 'Runtime unavailable; your draft will remain here'
        : labels[phase] || state.composeHintDefault;
    nodes.send.setAttribute(
      'aria-label',
      state.authRequired ? 'Log in before sending' : busy ? labels[phase] : 'Send message',
    );
    nodes.send.title = state.authRequired ? 'Log in before sending' : busy ? labels[phase] : 'Send';
    const glyph = nodes.send.querySelector('span');
    if (glyph) glyph.innerHTML = iconHtml(busy ? 'loader' : 'arrow-up');
    renderResumePrompts();
  }

  function setPromptPhase(phase, patch = {}) {
    const previous = state.prompt.phase;
    window.clearTimeout(state.prompt.resetTimer);
    state.prompt = { ...state.prompt, ...patch, phase, resetTimer: 0 };
    root.dataset.promptState = phase;
    const job = state.jobs.find((item) => item.job_id === state.prompt.jobId);
    const localStatus = {
      queued: 'queued',
      running: 'running',
      blocked: 'blocked',
      failed: 'failed',
      complete: 'completed',
    }[phase];
    if (job && localStatus) job.status = localStatus;
    updateComposerState();
    syncMicrotexture();
    if (phase !== previous) {
      const tone = {
        queued: 'queued',
        blocked: 'blocked',
        failed: 'error',
        complete: 'accepted',
      }[phase];
      if (tone) playInteractionTone(tone, { signal: true });
    }
    if (['complete', 'failed'].includes(phase)) {
      const terminalJobId = state.prompt.jobId;
      if (state.eventSourceJobId === terminalJobId && state.selectedJobId !== terminalJobId) {
        closeEventStream();
      }
      state.prompt.resetTimer = window.setTimeout(() => {
        if (state.prompt.jobId !== terminalJobId || state.prompt.phase !== phase) return;
        state.prompt = {
          phase: 'idle',
          jobId: '',
          objective: '',
          error: '',
          resetTimer: 0,
        };
        root.dataset.promptState = 'idle';
        updateComposerState();
        syncMicrotexture();
      }, phase === 'complete' ? 900 : 2400);
    }
  }

  function reconcilePromptState() {
    if (!state.prompt.jobId) return;
    const job = state.activity?.job?.job_id === state.prompt.jobId
      ? state.activity.job
      : state.jobs.find((item) => item.job_id === state.prompt.jobId);
    if (!job) return;
    const next = promptPhaseForStatus(job.status);
    if (!next) return;
    if (state.prompt.phase === 'running' && next === 'queued') return;
    if (next !== state.prompt.phase) setPromptPhase(next);
  }

  function syncMicrotexture() {
    const next = aggregateState();
    root.dataset.microtextureState = next;
    applyTextureIdentity();
    startTextureField();
  }

  function pulseTexture(kind = 'tick') {
    if (window.matchMedia?.('(prefers-reduced-motion: reduce)')?.matches) return;
    root.dataset.microtexturePulse = kind;
    const weight = { send: 1, error: 1.4, accepted: 0.8, queued: 0.64, blocked: 0.9 }[kind] || 0.45;
    state.texture.impulse = Math.min(2.5, state.texture.impulse + weight);
    const sequence = state.texture.keySequence += 1;
    addTextureInput(
      0.16 + ((sequence * 0.618033988749895) % 0.68),
      kind === 'send' ? 0.88 : 0.22 + ((sequence * 0.381966011250105) % 0.56),
      weight * 0.16,
      kind,
    );
    window.clearTimeout(state.texture.pulseTimer);
    state.texture.pulseTimer = window.setTimeout(() => delete root.dataset.microtexturePulse, 700);
  }

  function loadPreferences() {
    try {
      const stored = JSON.parse(window.localStorage.getItem(BRIDGE_SETTINGS_KEY) || '{}');
      const feedbackSounds = ['signals', 'full', 'off'].includes(stored.feedbackSounds)
        ? stored.feedbackSounds
        : 'signals';
      state.preferences = {
        ...state.preferences,
        ...stored,
        feedbackSounds,
      };
    } catch {
      state.preferences.feedbackSounds = 'signals';
    }
    root.dataset.feedbackSounds = state.preferences.feedbackSounds;
  }

  function savePreferences() {
    try {
      window.localStorage.setItem(BRIDGE_SETTINGS_KEY, JSON.stringify(state.preferences));
    } catch {
      // Private browsing and hardened clients may reject local storage.
    }
  }

  function updateSoundControls() {
    if (!nodes.soundToggle) return;
    const mode = state.preferences.feedbackSounds;
    nodes.soundToggle.textContent = `Sounds: ${mode === 'off' ? 'Off' : mode === 'full' ? 'Full' : 'Signals'}`;
    nodes.soundToggle.setAttribute('aria-pressed', String(mode !== 'off'));
    root.dataset.feedbackSounds = mode;
  }

  function primeAudio() {
    const AudioCtor = window.AudioContext || window.webkitAudioContext;
    if (!AudioCtor) return null;
    if (!state.audioContext || state.audioContext.state === 'closed') {
      state.audioContext = new AudioCtor();
    }
    if (state.audioContext.state === 'suspended') {
      state.audioContext.resume().catch(() => null);
    }
    return state.audioContext;
  }

  function audioAllowed(kind, options = {}) {
    if (state.preferences.feedbackSounds === 'off') return false;
    if (document.hidden || document.visibilityState === 'hidden') return false;
    if (!options.allowUnfocused && typeof document.hasFocus === 'function' && !document.hasFocus()) return false;
    return state.preferences.feedbackSounds === 'full' || SIGNAL_TONES.has(kind) || options.signal;
  }

  function scheduleToneVoice(context, destination, profile, start, ratio = 1, gainScale = 1) {
    const duration = Math.max(0.035, Number(profile.duration || 0.1));
    const frequency = Math.max(90, Number(profile.frequency || 180) * ratio);
    const oscillator = context.createOscillator();
    const gain = context.createGain();
    const filter = context.createBiquadFilter();
    oscillator.type = profile.wave || 'sine';
    oscillator.frequency.setValueAtTime(frequency, start);
    oscillator.frequency.exponentialRampToValueAtTime(Math.max(90, frequency * 0.985), start + duration);
    filter.type = 'bandpass';
    filter.frequency.setValueAtTime(Number(profile.filter || 760), start);
    filter.Q.value = 0.82;
    const peak = Math.max(0.001, Number(profile.peak || 0.008) * gainScale);
    gain.gain.setValueAtTime(0.0001, start);
    gain.gain.linearRampToValueAtTime(peak, start + Math.min(0.02, duration * 0.18));
    gain.gain.exponentialRampToValueAtTime(0.0001, start + duration);
    oscillator.connect(filter);
    filter.connect(gain);
    gain.connect(destination);
    oscillator.start(start);
    oscillator.stop(start + duration + 0.02);
  }

  function playInteractionTone(kind = 'click', options = {}) {
    pulseTexture(kind);
    if (!audioAllowed(kind, options)) return false;
    const now = Date.now();
    const throttle = kind === 'type' ? 110 : 42;
    const previous = kind === 'type' ? state.lastTypingToneAt : state.lastToneAt;
    if (!options.force && now - previous < throttle) return false;
    if (kind === 'type') state.lastTypingToneAt = now;
    else state.lastToneAt = now;
    const context = primeAudio();
    if (!context || context.state !== 'running') return false;
    const profile = INTERACTION_TONES[kind] || INTERACTION_TONES.click;
    const start = context.currentTime + 0.006;
    const master = context.createGain();
    const limiter = context.createDynamicsCompressor();
    master.gain.setValueAtTime(Number(profile.master || 0.6), start);
    limiter.threshold.setValueAtTime(-28, start);
    limiter.ratio.setValueAtTime(8, start);
    master.connect(limiter);
    limiter.connect(context.destination);
    scheduleToneVoice(context, master, profile, start, 1, 1);
    if (profile.ratio) {
      scheduleToneVoice(context, master, profile, start + Math.min(0.035, profile.duration * 0.28), profile.ratio, 0.45);
    }
    return true;
  }

  function completionProfile(slug = '') {
    const identity = identityContract(slug);
    const bases = {
      norman: { frequency: 136, wave: 'sine', filter: 740, ratio: 1.41 },
      personal: { frequency: 164, wave: 'triangle', filter: 860, ratio: 1.62 },
      shared: { frequency: 118, wave: 'triangle', filter: 680, ratio: 1.37 },
      infrastructure: { frequency: 118, wave: 'triangle', filter: 680, ratio: 1.37 },
      work: { frequency: 146, wave: 'sine', filter: 780, ratio: 1.52 },
      agents: { frequency: 154, wave: 'triangle', filter: 760, ratio: 1.46 },
    };
    const base = bases[identity.group] || bases.agents;
    const seed = identity.slug.split('').reduce((total, character) => total + character.charCodeAt(0), 0) || 1;
    const profile = {
      ...base,
      duration: identity.styleVariant === 'quiet' ? 0.54 : 0.72,
      peak: identity.styleVariant === 'quiet' ? 0.005 : 0.008,
      master: identity.styleVariant === 'quiet' ? 0.42 : 0.58,
      frequency: base.frequency + ((seed % 9) - 4) * 4,
    };
    if (identity.slug === 'gold-book') return { ...profile, frequency: 128, wave: 'triangle', filter: 720, ratio: 1.5 };
    if (identity.slug === 'platinum-standard') return { ...profile, frequency: 152, wave: 'sine', filter: 820 };
    return profile;
  }

  function playCompletionBell(slug = '') {
    const now = Date.now();
    if (now - state.lastCompletionAt < 320 || !audioAllowed('chime', { signal: true })) return false;
    state.lastCompletionAt = now;
    pulseTexture('accepted');
    const context = primeAudio();
    if (!context || context.state !== 'running') return false;
    const profile = completionProfile(slug);
    const start = context.currentTime + 0.012;
    const master = context.createGain();
    master.gain.setValueAtTime(profile.master, start);
    master.connect(context.destination);
    scheduleToneVoice(context, master, profile, start, 1, 1);
    scheduleToneVoice(context, master, profile, start + 0.025, profile.ratio || 1.5, 0.3);
    scheduleToneVoice(context, master, profile, start + 0.065, (profile.ratio || 1.5) * 1.55, 0.11);
    return true;
  }

  function cycleSoundMode() {
    const order = ['signals', 'full', 'off'];
    state.preferences.feedbackSounds = order[(order.indexOf(state.preferences.feedbackSounds) + 1) % order.length];
    savePreferences();
    updateSoundControls();
    if (state.preferences.feedbackSounds !== 'off') playInteractionTone('accepted', { force: true, signal: true });
  }

  function textureClamp(value, minimum, maximum) {
    return Math.max(minimum, Math.min(maximum, Number(value || 0)));
  }

  function textureSeed(index, salt = 0) {
    const raw = (index + 1) * 0.618033988749895 + (salt + 1) * 0.144269504088896;
    return raw - Math.floor(raw);
  }

  function textureFluidSquareWave(value, squareWeight) {
    const sine = Math.sin(value);
    const softenedSquare = Math.tanh(sine * 3.4);
    return sine * (1 - squareWeight) + softenedSquare * squareWeight;
  }

  function textureFractalWave(value, squareWeight, phase = 0) {
    const primary = textureFluidSquareWave(value + phase * 0.05, squareWeight);
    const octave = textureFluidSquareWave(value * 1.93 + phase * 0.38, squareWeight * 0.72);
    const filament = textureFluidSquareWave(value * 3.71 - phase * 0.24, squareWeight * 0.52);
    const hairline = textureFluidSquareWave(value * 7.13 + phase * 0.13, squareWeight * 0.34);
    return primary * 0.62 + octave * 0.24 + filament * 0.10 + hairline * 0.04;
  }

  function textureIdentitySeed(value) {
    const text = String(value || 'norman');
    let hash = 2166136261;
    for (let index = 0; index < text.length; index += 1) {
      hash ^= text.charCodeAt(index);
      hash = Math.imul(hash, 16777619);
    }
    return ((hash >>> 0) % 10000) / 10000;
  }

  function textureMotionSignature(texture = textureForSelection()) {
    const pattern = String(texture?.pattern || 'prime-orbit-weave').toLowerCase();
    const slug = slugify(texture?.slug || root.dataset.identitySlug || 'norman');
    const seed = textureIdentitySeed(`${slug}:${pattern}`);
    const angle = Number(texture?.angle ?? 96);
    const crossAngle = Number(texture?.cross ?? 6);
    const grain = Math.max(10, Number(texture?.grain || 24));
    const crossGrain = Math.max(14, Number(texture?.cross_grain || 44));
    let family = 'weave';
    if (/orbit/.test(pattern)) family = 'orbit';
    else if (/plaid/.test(pattern)) family = 'plaid';
    else if (/scan|noise/.test(pattern)) family = 'scan';
    else if (/stone|course/.test(pattern)) family = 'masonry';
    else if (/facet|diamond|platinum|brushed/.test(pattern)) family = 'facet';
    else if (/bar|rail|shelf|lane|scorecard/.test(pattern)) family = 'channels';
    else if (/pin|grid|pixel|panel|parcel/.test(pattern)) family = 'grid';
    else if (/aperture/.test(pattern)) family = 'aperture';
    else if (/microscope|stage/.test(pattern)) family = 'stage';
    else if (/contour|field-map/.test(pattern)) family = 'contour';
    else if (/sunburst|beam/.test(pattern)) family = 'radiant';
    else if (/book|memo|fiber|spreadsheet/.test(pattern)) family = 'editorial';
    else if (/mesh|lattice|weave/.test(pattern)) family = 'mesh';
    else if (/void|static/.test(pattern)) family = 'void';
    else if (/halftone|tooth/.test(pattern)) family = 'halftone';

    const familyProfiles = {
      weave: { tempo: 0.92, amplitude: 0.92, frequency: 0.94, drift: 0.94, square: 0.02, shear: 0.00, wake: 0.88, damping: 0.82, point: 0.10 },
      orbit: { tempo: 0.82, amplitude: 1.14, frequency: 0.76, drift: 0.86, square: -0.06, shear: 0.02, wake: 1.08, damping: 0.92, point: 0.08 },
      plaid: { tempo: 0.72, amplitude: 0.72, frequency: 0.86, drift: 0.62, square: 0.18, shear: -0.01, wake: 0.66, damping: 0.72, point: 0.08 },
      scan: { tempo: 1.34, amplitude: 0.86, frequency: 1.34, drift: 1.42, square: 0.28, shear: -0.02, wake: 1.26, damping: 1.12, point: 0.28 },
      masonry: { tempo: 0.48, amplitude: 0.54, frequency: 0.68, drift: 0.42, square: 0.34, shear: 0.00, wake: 0.48, damping: 0.56, point: 0.04 },
      facet: { tempo: 0.88, amplitude: 0.96, frequency: 1.06, drift: 0.82, square: 0.42, shear: 0.04, wake: 0.84, damping: 0.82, point: 0.12 },
      channels: { tempo: 1.04, amplitude: 0.68, frequency: 1.18, drift: 1.26, square: 0.24, shear: 0.01, wake: 1.06, damping: 0.92, point: 0.10 },
      grid: { tempo: 0.94, amplitude: 0.64, frequency: 1.26, drift: 0.92, square: 0.36, shear: 0.00, wake: 0.92, damping: 0.86, point: 0.32 },
      aperture: { tempo: 0.78, amplitude: 1.18, frequency: 0.82, drift: 0.84, square: -0.08, shear: 0.05, wake: 1.18, damping: 0.96, point: 0.08 },
      stage: { tempo: 0.58, amplitude: 0.48, frequency: 0.92, drift: 0.46, square: 0.18, shear: 0.00, wake: 0.56, damping: 0.66, point: 0.16 },
      contour: { tempo: 0.66, amplitude: 1.08, frequency: 0.72, drift: 0.74, square: -0.10, shear: 0.02, wake: 1.04, damping: 0.90, point: 0.06 },
      radiant: { tempo: 1.02, amplitude: 1.04, frequency: 0.88, drift: 1.16, square: 0.00, shear: 0.06, wake: 1.12, damping: 0.96, point: 0.12 },
      editorial: { tempo: 0.52, amplitude: 0.58, frequency: 0.78, drift: 0.48, square: 0.14, shear: -0.01, wake: 0.58, damping: 0.64, point: 0.06 },
      mesh: { tempo: 0.82, amplitude: 0.88, frequency: 1.02, drift: 0.82, square: 0.10, shear: 0.03, wake: 0.86, damping: 0.82, point: 0.18 },
      void: { tempo: 0.42, amplitude: 0.82, frequency: 1.46, drift: 0.34, square: 0.44, shear: -0.06, wake: 0.72, damping: 1.18, point: 0.36 },
      halftone: { tempo: 0.96, amplitude: 0.82, frequency: 1.28, drift: 0.88, square: 0.22, shear: 0.03, wake: 1.02, damping: 0.92, point: 0.52 },
    };
    const base = familyProfiles[family] || familyProfiles.weave;
    const angleDelta = ((((angle - crossAngle) % 360) + 540) % 360) - 180;
    const density = textureClamp(28 / ((grain + crossGrain) / 2), 0.62, 1.42);
    return {
      ...base,
      family,
      motif: pattern,
      seed,
      direction: Math.cos(angle * Math.PI / 180) >= 0 ? 1 : -1,
      tempo: base.tempo * (0.91 + seed * 0.18),
      amplitude: base.amplitude * (0.92 + seed * 0.16),
      frequency: base.frequency * density * (0.94 + seed * 0.12),
      drift: base.drift * (0.90 + (1 - seed) * 0.20),
      shear: base.shear + angleDelta / 7200,
      phaseOffset: seed * Math.PI * 2,
      segment: Math.max(14, grain * (0.78 + seed * 0.42)),
      crossSegment: Math.max(18, crossGrain * (0.74 + (1 - seed) * 0.36)),
    };
  }

  function interpolatedTextureProfile(target, delta) {
    if (!state.texture.renderProfile) {
      state.texture.renderProfile = { ...target };
      return state.texture.renderProfile;
    }
    const transition = textureClamp(target.transition || 1, 0.45, 1.8);
    const amount = 1 - Math.pow(0.002, Math.max(0.001, delta) / transition);
    Object.keys(target).forEach((key) => {
      const current = Number(state.texture.renderProfile[key]);
      const next = Number(target[key]);
      state.texture.renderProfile[key] = Number.isFinite(current)
        ? current + (next - current) * amount
        : next;
    });
    return state.texture.renderProfile;
  }

  function addTextureInput(x, y, energy, kind = 'input', velocityX = 0, velocityY = 0) {
    if (window.matchMedia?.('(prefers-reduced-motion: reduce)')?.matches) return;
    const cleanX = textureClamp(x, 0.03, 0.97);
    const cleanY = textureClamp(y, 0.03, 0.97);
    const cleanEnergy = textureClamp(energy, 0.008, 0.42);
    state.texture.targetX = cleanX;
    state.texture.targetY = cleanY;
    state.texture.inputEnergy = Math.min(2.2, state.texture.inputEnergy + cleanEnergy);
    state.texture.impulse = Math.min(2.8, state.texture.impulse + cleanEnergy * 1.8);
    state.texture.flowX = textureClamp(state.texture.flowX + velocityX, -1.6, 1.6);
    state.texture.flowY = textureClamp(state.texture.flowY + velocityY, -1.6, 1.6);
    root.dataset.textureReactive = 'true';
    window.clearTimeout(state.texture.reactiveTimer);
    state.texture.reactiveTimer = window.setTimeout(() => {
      delete root.dataset.textureReactive;
    }, kind === 'pointer' ? 900 : 1150);
    if (kind === 'pointer') {
      const pointerWake = state.texture.disturbances.find((item) => item.kind === 'pointer');
      if (pointerWake) {
        pointerWake.x = cleanX;
        pointerWake.y = cleanY;
        pointerWake.energy = Math.min(0.8, pointerWake.energy + cleanEnergy * 0.7);
        pointerWake.velocityX = velocityX;
        pointerWake.velocityY = velocityY;
        pointerWake.age = 0;
      } else {
        state.texture.disturbances.push({
          x: cleanX, y: cleanY, energy: cleanEnergy, velocityX, velocityY, age: 0, kind,
        });
      }
    } else {
      state.texture.disturbances.push({
        x: cleanX, y: cleanY, energy: cleanEnergy, velocityX, velocityY, age: 0, kind,
      });
    }
    if (state.texture.disturbances.length > 9) state.texture.disturbances.shift();
    startTextureField();
  }

  function buildTextureLines(width, height) {
    const lines = [];
    const style = getComputedStyle(root);
    const span = Math.hypot(width, height) * 0.72;
    const families = [
      {
        angle: parseFloat(style.getPropertyValue('--texture-angle')) || 96,
        spacing: parseFloat(style.getPropertyValue('--texture-spacing')) || 24,
        alpha: 0.58,
      },
      {
        angle: parseFloat(style.getPropertyValue('--texture-cross-angle')) || 6,
        spacing: parseFloat(style.getPropertyValue('--texture-cross-spacing')) || 48,
        alpha: 0.30,
      },
    ];
    let threadIndex = 0;
    families.forEach((family, familyIndex) => {
      const spacing = Math.max(12, Math.min(72, family.spacing));
      for (let offset = -span; offset <= span; offset += spacing) {
        lines.push({
          family: familyIndex,
          angle: family.angle * Math.PI / 180,
          offset,
          phase: textureSeed(threadIndex, 1) * Math.PI * 2,
          phase2: textureSeed(threadIndex, 5) * Math.PI * 2,
          alpha: family.alpha * (0.68 + textureSeed(threadIndex, 6) * 0.34),
          harmonic: 0.7 + textureSeed(threadIndex, 4) * 0.8,
          speed: 0.92 + textureSeed(threadIndex, 2) * 0.16,
          amplitude: 0.84 + textureSeed(threadIndex, 3) * 0.26,
          major: threadIndex % 5 === 0,
          glint: textureSeed(threadIndex, 9),
        });
        threadIndex += 1;
      }
    });
    if (lines.length > 240) {
      state.texture.lines = lines.filter((_, index) => index % Math.ceil(lines.length / 240) === 0);
    } else {
      state.texture.lines = lines;
    }
  }

  function drawTextureMotif(context, width, height, motion, colors, profile) {
    const motif = motion.motif;
    const phase = state.texture.phase * motion.direction + motion.phaseOffset;
    const alpha = Math.min(0.24, Number(profile.alpha || 0.22) * 0.72);
    const grain = Math.max(12, motion.segment);
    const cross = Math.max(18, motion.crossSegment);
    context.save();
    context.globalAlpha = alpha;
    context.strokeStyle = colors[1];
    context.fillStyle = colors[0];
    context.lineWidth = 0.65;

    if (/prime-orbit-weave|aperture-sweep|keystone-arch-weave|cloud-mesh/.test(motif)) {
      const originX = state.texture.focusX * width;
      const originY = state.texture.focusY * height;
      const count = /prime-orbit/.test(motif) ? 5 : /cloud/.test(motif) ? 7 : 4;
      for (let index = 0; index < count; index += 1) {
        context.beginPath();
        const radius = 48 + index * (grain * 1.5);
        const offset = /cloud/.test(motif) ? Math.sin(index * 2.3 + phase) * 34 : 0;
        context.ellipse(
          originX + offset,
          originY + Math.cos(index * 1.7 + phase * 0.3) * 16,
          radius * (/keystone/.test(motif) ? 0.72 : 1.4),
          radius * (/aperture/.test(motif) ? 0.42 : 0.62),
          (motion.seed - 0.5) * 0.8,
          /keystone/.test(motif) ? Math.PI : 0,
          Math.PI * 2,
        );
        context.stroke();
      }
    } else if (/stone-course/.test(motif)) {
      for (let y = grain; y < height; y += grain) {
        const row = Math.round(y / grain);
        context.beginPath();
        context.moveTo(0, y);
        context.lineTo(width, y);
        context.stroke();
        for (let x = (row % 2 ? grain : grain * 0.5); x < width; x += grain * 2.2) {
          context.fillRect(x, y - grain, 0.7, grain);
        }
      }
    } else if (/call-bars/.test(motif)) {
      for (let x = grain * 0.5; x < width; x += grain * 1.25) {
        const heightScale = 0.18 + (Math.sin(x * 0.021 - phase * 2.4) + 1) * 0.18;
        context.fillRect(x, height * (0.5 - heightScale), grain * 0.46, height * heightScale * 2);
      }
    } else if (/archive-shelves|rack-rails|scorecard-lines|gilded-book-grain|memo-fiber/.test(motif)) {
      const step = /rack-rails/.test(motif) ? grain : cross * 0.72;
      for (let y = step; y < height; y += step) {
        context.globalAlpha = alpha * (0.55 + ((y / step) % 3) * 0.14);
        context.beginPath();
        context.moveTo(0, y + Math.sin(phase + y * 0.01) * (/memo|book/.test(motif) ? 2 : 0));
        context.lineTo(width, y);
        context.stroke();
      }
    } else if (/circuit-pins|parcel-pinboard/.test(motif)) {
      const yStep = cross * 0.9;
      const xStep = grain * 2;
      for (let y = yStep * 0.5; y < height; y += yStep) {
        context.beginPath();
        context.moveTo(0, y);
        context.lineTo(width, y);
        context.stroke();
        for (let x = xStep * 0.5; x < width; x += xStep) {
          const offset = /parcel/.test(motif) ? Math.sin(x * 0.018 + y * 0.011) * grain * 0.35 : 0;
          context.beginPath();
          context.arc(x, y + offset, /parcel/.test(motif) ? 1.5 : 1.15, 0, Math.PI * 2);
          context.fill();
        }
      }
    } else if (/microscope-stage/.test(motif)) {
      const x = width * (0.42 + Math.sin(phase * 0.18) * 0.03);
      const y = height * (0.48 + Math.cos(phase * 0.16) * 0.03);
      context.strokeRect(x - cross * 2, y - cross, cross * 4, cross * 2);
      context.beginPath();
      context.moveTo(x, y - cross * 2.2);
      context.lineTo(x, y + cross * 2.2);
      context.moveTo(x - cross * 3.2, y);
      context.lineTo(x + cross * 3.2, y);
      context.stroke();
    } else if (/contour-lines|field-map/.test(motif)) {
      for (let row = 0; row < 7; row += 1) {
        context.beginPath();
        for (let x = 0; x <= width; x += 18) {
          const y = height * (0.18 + row * 0.105)
            + Math.sin(x * 0.009 + phase * 0.34 + row) * (8 + row * 1.8)
            + Math.sin(x * 0.0023 - phase * 0.18) * 14;
          if (x === 0) context.moveTo(x, y);
          else context.lineTo(x, y);
        }
        context.stroke();
      }
    } else if (/sunburst|beam-sweep/.test(motif)) {
      const originX = /sunburst/.test(motif) ? width * 0.08 : width * 0.12;
      const originY = /sunburst/.test(motif) ? height * 0.88 : height * 0.56;
      for (let index = 0; index < 11; index += 1) {
        const angle = -1.15 + index * 0.105 + Math.sin(phase * 0.22) * 0.025;
        context.beginPath();
        context.moveTo(originX, originY);
        context.lineTo(originX + Math.cos(angle) * width * 1.2, originY + Math.sin(angle) * width * 1.2);
        context.stroke();
      }
    } else if (/dashboard-pixels|command-grid|panel-rhythm/.test(motif)) {
      const cell = /panel-rhythm/.test(motif) ? grain * 2.4 : grain * 1.8;
      for (let y = cell * 0.5; y < height; y += cell) {
        for (let x = cell * 0.5; x < width; x += cell) {
          const gate = (Math.round(x / cell) * 3 + Math.round(y / cell) * 5 + Math.floor(motion.seed * 11)) % 4;
          if (gate < (/dashboard/.test(motif) ? 2 : 1)) {
            context.fillRect(x, y, /panel/.test(motif) ? cell * 0.62 : 2.2, /panel/.test(motif) ? cell * 0.34 : 2.2);
          }
        }
      }
    } else if (/spreadsheet-slope/.test(motif)) {
      for (let row = 0; row < 8; row += 1) {
        const y = height * (0.16 + row * 0.1);
        context.beginPath();
        context.moveTo(0, y + row * 2);
        context.lineTo(width, y - width * 0.055 + row * 2);
        context.stroke();
      }
    } else if (/brushed-platinum/.test(motif)) {
      for (let y = grain * 0.5; y < height; y += grain * 0.42) {
        const start = ((y * 13 + motion.seed * width) % (width * 0.28)) - width * 0.1;
        context.globalAlpha = alpha * (0.32 + ((y / grain) % 4) * 0.12);
        context.fillRect(start, y, width * (0.42 + motion.seed * 0.28), 0.7);
      }
    } else if (/packet-lanes/.test(motif)) {
      for (let row = 0; row < 6; row += 1) {
        const y = height * (0.2 + row * 0.12);
        for (let packet = 0; packet < 7; packet += 1) {
          const x = ((packet * cross * 2.3 + row * grain + phase * 18) % (width + cross)) - cross;
          context.fillRect(x, y, cross * 0.72, grain * 0.38);
        }
      }
    } else if (/void-static|scan-noise/.test(motif)) {
      const count = /void/.test(motif) ? 38 : 90;
      for (let index = 0; index < count; index += 1) {
        const x = textureSeed(index, 31) * width;
        const y = textureSeed(index, 37) * height;
        const gate = /void/.test(motif)
          ? (index + Math.floor(phase * 0.3)) % 5 === 0
          : true;
        if (gate) context.fillRect(x, y, /scan/.test(motif) ? grain * 0.5 : 1, 0.8);
      }
    } else if (/halftone-tooth/.test(motif)) {
      const spacing = grain * 1.15;
      for (let y = spacing * 0.5; y < height; y += spacing) {
        for (let x = spacing * 0.5; x < width; x += spacing) {
          const radius = 0.65 + (Math.sin(x * 0.04 + y * 0.025 - phase) + 1) * 0.72;
          context.beginPath();
          context.arc(x + (Math.round(y / spacing) % 2) * spacing * 0.45, y, radius, 0, Math.PI * 2);
          context.fill();
        }
      }
    }
    context.restore();
  }

  function drawTextureField(timestamp = 0) {
    const canvas = nodes.textureCanvas;
    const context = canvas?.getContext?.('2d', { alpha: true });
    if (!context) return;
    const rect = root.getBoundingClientRect();
    const dpr = Math.min(2, Math.max(1.5, window.devicePixelRatio || 1));
    const width = Math.max(320, rect.width);
    const height = Math.max(320, rect.height);
    if (canvas.width !== Math.round(width * dpr) || canvas.height !== Math.round(height * dpr)) {
      canvas.width = Math.round(width * dpr);
      canvas.height = Math.round(height * dpr);
      canvas.style.width = `${width}px`;
      canvas.style.height = `${height}px`;
      buildTextureLines(width, height);
    }
    context.imageSmoothingEnabled = true;
    context.imageSmoothingQuality = 'high';
    const last = state.texture.lastTime || timestamp;
    const delta = Math.min(0.05, Math.max(0, (timestamp - last) / 1000));
    state.texture.lastTime = timestamp;
    const stateProfile = TEXTURE_MOTION_PROFILES[root.dataset.microtextureState]
      || TEXTURE_MOTION_PROFILES.ready;
    const motion = textureMotionSignature();
    const targetProfile = {
      ...stateProfile,
      speed: stateProfile.speed * motion.tempo,
      drift: stateProfile.drift * motion.drift,
      amplitude: stateProfile.amplitude * motion.amplitude,
      frequency: stateProfile.frequency * motion.frequency,
      square: textureClamp(stateProfile.square + motion.square, 0, 0.82),
      shear: stateProfile.shear + motion.shear,
      glint: stateProfile.glint * (0.84 + motion.wake * 0.22),
    };
    const profile = interpolatedTextureProfile(targetProfile, delta);
    state.texture.phase += delta * Number(profile.speed || 0.15);
    state.texture.impulse *= Math.pow(0.08, delta || 0.016);
    state.texture.inputEnergy *= Math.pow(0.32, delta || 0.016);
    state.texture.flowX *= Math.pow(0.12, delta || 0.016);
    state.texture.flowY *= Math.pow(0.12, delta || 0.016);
    state.texture.disturbances.forEach((item) => { item.age += delta; });
    state.texture.disturbances = state.texture.disturbances.filter((item) => item.age < 4.8);
    const focusEase = Math.min(1, delta * 3.6);
    state.texture.focusX += (state.texture.targetX - state.texture.focusX) * focusEase;
    state.texture.focusY += (state.texture.targetY - state.texture.focusY) * focusEase;
    const visualTarget = textureClamp(state.texture.inputEnergy / 1.35, 0, 1);
    const visualRate = visualTarget > state.texture.visualLevel ? 10.5 : 2.15;
    const visualEase = 1 - Math.exp(-delta * visualRate);
    state.texture.visualLevel += (visualTarget - state.texture.visualLevel) * visualEase;
    if (timestamp - state.texture.lastVisualSync > 30 || !state.texture.lastVisualSync) {
      root.style.setProperty('--texture-reactive-level', state.texture.visualLevel.toFixed(4));
      root.style.setProperty('--texture-focus-x', `${(state.texture.focusX * 100).toFixed(2)}%`);
      root.style.setProperty('--texture-focus-y', `${(state.texture.focusY * 100).toFixed(2)}%`);
      state.texture.lastVisualSync = timestamp;
    }
    const style = getComputedStyle(root);
    const colors = [
      style.getPropertyValue('--agent-accent').trim() || '#5fd2c4',
      style.getPropertyValue('--agent-accent-2').trim() || '#76a8ff',
    ];
    context.clearRect(0, 0, canvas.width, canvas.height);
    context.save();
    context.scale(dpr, dpr);
    context.lineCap = 'round';
    context.lineJoin = 'round';
    const centerX = width / 2;
    const centerY = height / 2;
    const span = Math.hypot(width, height) * 0.75;
    const pattern = root.dataset.identityPattern || '';
    const stepped = /scan|pixel|pin|grid|bar|shelf|stone|book|memo|platinum/.test(pattern);
    const contour = /contour|aperture|field|sweep|orbit/.test(pattern);
    const editorial = /book|memo|cross|ledger|editorial/.test(pattern);
    const signal = /signal|scan|radio|pulse|wave/.test(pattern);
    const focusX = state.texture.focusX * width;
    const focusY = state.texture.focusY * height;
    const squareWeight = textureClamp(
      Number(profile.square || 0) + (stepped ? 0.16 : editorial ? 0.08 : 0),
      0,
      0.84,
    );
    const baseAmplitude = Number(profile.amplitude || 2.3);
    const baseFrequency = Number(profile.frequency || 0.0092);
    const flowOffset = state.texture.phase * Math.max(0, Number(profile.drift || 0))
      * 18 * motion.direction;
    const interactiveAmplitude = state.texture.inputEnergy
      * (signal ? 1.1 : 0.82) * motion.wake;
    drawTextureMotif(context, width, height, motion, colors, profile);
    context.save();
    context.globalCompositeOperation = 'lighter';
    for (let band = 0; band < 2; band += 1) {
      const bandSeed = textureSeed(band, 21);
      const baseline = height * (0.3 + band * 0.38);
      const bandAmplitude = 10 + baseAmplitude * (1.8 + bandSeed * 0.8);
      context.beginPath();
      for (let x = -80; x <= width + 80; x += 18) {
        const focusEnvelope = Math.exp(-Math.abs(x - focusX) / Math.max(220, width * 0.34));
        const focusLift = (focusY - baseline) * focusEnvelope * state.texture.inputEnergy * 0.055;
        let disturbanceLift = 0;
        for (const disturbance of state.texture.disturbances) {
          const disturbanceX = disturbance.x * width + disturbance.velocityX * disturbance.age * 34;
          const distance = Math.abs(x - disturbanceX);
          const envelope = Math.exp(-distance / (150 + disturbance.age * 70)) * Math.exp(-disturbance.age * 0.68);
          disturbanceLift += Math.sin(distance * 0.017 - disturbance.age * 3.8 + bandSeed * 6)
            * envelope * disturbance.energy * 22;
        }
        const broadPhase = state.texture.phase * motion.direction + motion.phaseOffset;
        let broadShape = Math.sin(x * 0.0046 + broadPhase * (0.72 + band * 0.08) + bandSeed * 7);
        let broadDetail = Math.sin(x * 0.0091 - broadPhase * 0.41 + bandSeed * 13) * 0.28;
        if (motion.family === 'orbit' || motion.family === 'aperture') {
          const radial = Math.hypot(x - focusX, baseline - focusY);
          broadShape = Math.sin(radial * 0.010 - broadPhase * (motion.family === 'aperture' ? 2.2 : 1.3) + band);
          broadDetail = Math.cos((x - focusX) * 0.006 + broadPhase + bandSeed * 9) * 0.34;
        } else if (motion.family === 'masonry') {
          const course = Math.floor((x + (band % 2) * motion.segment * 0.5) / motion.segment);
          broadShape = (course % 2 ? 0.34 : -0.34) + Math.sin(broadPhase + band) * 0.08;
          broadDetail = 0;
        } else if (motion.family === 'facet') {
          broadShape = (2 / Math.PI) * Math.asin(Math.sin(x * 0.0082 + broadPhase + bandSeed * 5));
          broadDetail *= 0.46;
        } else if (motion.family === 'scan' || motion.family === 'channels') {
          const packet = Math.sin(x * 0.026 - broadPhase * (motion.family === 'scan' ? 8 : 4) + bandSeed * 11);
          broadShape = Math.round(packet * 3) / 3;
          broadDetail *= 0.22;
        } else if (motion.family === 'grid' || motion.family === 'stage') {
          broadShape = Math.round(broadShape * (motion.family === 'grid' ? 4 : 2))
            / (motion.family === 'grid' ? 4 : 2);
          broadDetail *= 0.18;
        } else if (motion.family === 'contour') {
          broadShape += Math.sin(x * 0.0023 - broadPhase * 0.24 + band) * 0.62;
        } else if (motion.family === 'radiant') {
          broadShape = Math.sin((x - focusX) * 0.007 + broadPhase * 1.7 + bandSeed * 8);
          broadDetail = Math.sin(Math.abs(x - focusX) * 0.014 - broadPhase * 2.4) * 0.24;
        } else if (motion.family === 'editorial' || motion.family === 'plaid') {
          broadShape *= 0.42;
          broadDetail *= 0.18;
        } else if (motion.family === 'void') {
          broadShape = Math.sin(x * 0.017 + broadPhase * 0.34 + bandSeed * 19)
            * (Math.sin(x * 0.0021 - broadPhase) > 0.58 ? 1 : 0.08);
          broadDetail = 0;
        } else if (motion.family === 'halftone') {
          broadShape = Math.sin(x * 0.011 + broadPhase * 1.2 + bandSeed * 7)
            * (0.64 + Math.sin(x * 0.039 - broadPhase * 2.1) * 0.24);
          broadDetail *= 0.38;
        }
        const y = baseline
          + broadShape * bandAmplitude
          + broadDetail * bandAmplitude
          + focusLift
          + disturbanceLift;
        if (x === -80) context.moveTo(x, y);
        else context.lineTo(x, y);
      }
      context.strokeStyle = colors[band % colors.length];
      context.globalAlpha = 0.006 + Number(profile.alpha || 0.22) * 0.018 + state.texture.inputEnergy * 0.006;
      context.lineWidth = 7 + bandSeed * 8;
      context.stroke();
    }
    context.restore();
    for (let index = 0; index < state.texture.lines.length; index += 1) {
      const line = state.texture.lines[index];
      const directionX = Math.cos(line.angle);
      const directionY = Math.sin(line.angle);
      const normalX = -directionY;
      const normalY = directionX;
      const glintPoints = line.major ? [] : null;
      context.beginPath();
      for (let point = -span; point <= span; point += 16) {
        const local = point + flowOffset * line.speed + line.harmonic * 14;
        const across = line.offset / Math.max(1, span);
        const domainWarp = Math.sin(
          (local / Math.max(1, span) * 1.618033988749895 + across * 0.618033988749895 + state.texture.phase * 0.035)
          * Math.PI * 2 + line.phase,
        ) * 0.52 + Math.sin(
          (local / Math.max(1, span) * 2.414213562373095 - across * 1.272019649514069 + state.texture.phase * 0.057)
          * Math.PI * 2 + line.phase2,
        ) * 0.30;
        const waveInput = local * baseFrequency * line.harmonic
          + state.texture.phase * 2.85 * line.speed
          + line.phase
          + domainWarp * 0.42;
        let shape = textureFractalWave(waveInput, squareWeight, line.phase2);
        shape += Math.sin(waveInput * 0.31 + state.texture.phase * 0.72 + line.phase2) * 0.18;
        if (motion.family === 'orbit') {
          shape += Math.sin(waveInput * 0.48 - state.texture.phase * 1.4 + motion.phaseOffset) * 0.46;
        } else if (motion.family === 'plaid') {
          shape = Math.round(shape * 2.4) / 2.4 * (line.family ? 0.58 : 0.76);
        } else if (motion.family === 'scan') {
          shape = Math.round(shape * 5) / 5;
          shape += textureFluidSquareWave(point * 0.051 - state.texture.phase * 13 + line.phase, 0.58) * 0.24;
        } else if (motion.family === 'masonry') {
          const course = Math.floor((point + (line.major ? motion.segment * 0.5 : 0)) / motion.segment);
          shape = (course % 2 ? 0.32 : -0.32) + shape * 0.12;
        } else if (motion.family === 'facet') {
          shape = (2 / Math.PI) * Math.asin(Math.sin(waveInput + line.phase2)) * 0.84
            + (2 / Math.PI) * Math.asin(Math.sin(waveInput * 0.5 - line.phase)) * 0.18;
        } else if (motion.family === 'channels') {
          shape *= line.family ? 0.18 : 0.48;
          shape += textureFluidSquareWave(point * 0.026 - state.texture.phase * 6 + line.phase, 0.46) * 0.16;
        } else if (motion.family === 'grid') {
          shape = Math.round(shape * 4) / 4 * 0.62;
        } else if (motion.family === 'aperture') {
          shape += Math.sin(waveInput * 0.52 - state.texture.phase * 2.2 + line.phase2) * 0.58;
        } else if (motion.family === 'stage') {
          shape = Math.round(shape * 2) / 2 * 0.28;
        } else if (motion.family === 'contour') {
          shape += Math.sin(point * 0.0032 + line.offset * 0.011 + state.texture.phase * 0.28) * 0.72;
        } else if (motion.family === 'radiant') {
          shape += Math.sin(point * 0.009 - state.texture.phase * 2.4 + motion.phaseOffset) * 0.44;
        } else if (motion.family === 'editorial') {
          shape = shape * 0.34 + Math.sin(point * 0.0024 + line.phase) * 0.16;
        } else if (motion.family === 'mesh') {
          shape += Math.sin(waveInput * 0.71 + line.offset * 0.017 - state.texture.phase) * 0.32;
        } else if (motion.family === 'void') {
          shape *= Math.sin(point * 0.018 + line.phase2) > 0.36 ? 0.72 : 0.06;
        } else if (motion.family === 'halftone') {
          shape = Math.round(shape * 3.5) / 3.5;
          shape += Math.sin(point * 0.061 + line.phase2 - state.texture.phase * 2.8) * 0.12;
        }
        if (contour) shape += Math.sin(point * 0.004 + line.phase * 0.7) * 0.38;
        if (editorial) shape *= line.family ? 0.42 : 0.72;
        if (signal) shape += textureFluidSquareWave(point * 0.042 - state.texture.phase * 9 + line.phase, 0.38) * 0.20;
        const baseX = centerX + directionX * point + normalX * line.offset;
        const baseY = centerY + directionY * point + normalY * line.offset;
        const focusDistance = Math.hypot(baseX - focusX, baseY - focusY);
        const wake = Math.exp(-focusDistance / Math.max(180, Math.min(width, height) * 0.42));
        const travelingWake = Math.sin(
          focusDistance * 0.025 - state.texture.phase * (signal ? 16 : 8) + line.phase,
        ) * wake * interactiveAmplitude;
        let disturbanceWarp = 0;
        for (const disturbance of state.texture.disturbances) {
          const disturbanceX = disturbance.x * width + disturbance.velocityX * disturbance.age * 34;
          const disturbanceY = disturbance.y * height + disturbance.velocityY * disturbance.age * 34;
          const distance = Math.hypot(baseX - disturbanceX, baseY - disturbanceY);
          const radius = 72 + disturbance.age * (disturbance.kind === 'key' ? 56 : 82);
          const envelope = Math.exp(-distance / (radius * (1.18 + motion.wake * 0.32)))
            * Math.exp(-disturbance.age * (0.96 / motion.damping));
          let wave = Math.sin(
            distance * (motion.family === 'contour' ? 0.014 : motion.family === 'scan' ? 0.032 : 0.021)
            - disturbance.age * (3.2 + motion.tempo * 1.4) + line.phase2,
          );
          if (motion.family === 'grid' || motion.family === 'masonry') wave = Math.round(wave * 3) / 3;
          if (motion.family === 'facet') wave = (2 / Math.PI) * Math.asin(Math.sin(wave * Math.PI));
          disturbanceWarp += wave * envelope * disturbance.energy * baseAmplitude * 11.8;
        }
        const shear = Number(profile.shear || 0) * point * (line.family ? -0.34 : 0.34);
        const ambientWarp = (shape + domainWarp * 0.07) * baseAmplitude * line.amplitude;
        const inputBillow = textureFractalWave(
          waveInput * 0.47 + state.texture.flowX * 0.9 - state.texture.flowY * 0.6,
          squareWeight * 0.72,
          line.phase,
        ) * state.texture.inputEnergy * baseAmplitude * 1.08;
        const warp = (ambientWarp + inputBillow + travelingWake + disturbanceWarp) * (line.family ? 0.62 : 1)
          + state.texture.impulse * textureFluidSquareWave(point * 0.03 + line.phase, squareWeight) * 1.45;
        const offset = line.offset + shear + warp;
        const x = centerX + directionX * point + normalX * offset;
        const y = centerY + directionY * point + normalY * offset;
        if (glintPoints) glintPoints.push([x, y]);
        if (point === -span) context.moveTo(x, y);
        else context.lineTo(x, y);
      }
      const familyAlpha = editorial && line.family ? 0.76 : 1;
      const activeLift = Math.min(0.06, state.texture.inputEnergy * 0.025);
      context.globalAlpha = Math.min(
        0.62,
        (Number(profile.alpha || 0.22) + activeLift) * line.alpha * familyAlpha * 2.45,
      );
      context.strokeStyle = colors[line.family % colors.length];
      context.lineWidth = line.family ? 0.72 : (line.major ? 1.12 : 0.82);
      context.stroke();
      if (glintPoints?.length && Number(profile.glint || 0) > 0.015) {
        const travel = state.texture.phase * Math.max(0, Number(profile.drift || 0)) * 0.019 * line.speed + line.glint;
        const center = Math.floor((((travel % 1) + 1) % 1) * (glintPoints.length - 1));
        const radius = Math.max(2, Math.floor(glintPoints.length * 0.035));
        const startIndex = Math.max(0, center - radius);
        const endIndex = Math.min(glintPoints.length - 1, center + radius);
        const startPoint = glintPoints[startIndex];
        const endPoint = glintPoints[endIndex];
        if (startPoint && endPoint && endIndex > startIndex) {
          const gradient = context.createLinearGradient(startPoint[0], startPoint[1], endPoint[0], endPoint[1]);
          gradient.addColorStop(0, 'transparent');
          gradient.addColorStop(0.5, colors[line.family % colors.length]);
          gradient.addColorStop(1, 'transparent');
          context.save();
          context.globalCompositeOperation = 'lighter';
          context.globalAlpha = Number(profile.glint || 0) * (0.56 + state.texture.inputEnergy * 0.08);
          context.strokeStyle = gradient;
          context.lineWidth = line.family ? 0.68 : 1.05;
          context.beginPath();
          for (let pointIndex = startIndex; pointIndex <= endIndex; pointIndex += 1) {
            const glintPoint = glintPoints[pointIndex];
            if (pointIndex === startIndex) context.moveTo(glintPoint[0], glintPoint[1]);
            else context.lineTo(glintPoint[0], glintPoint[1]);
          }
          context.stroke();
          context.restore();
        }
      }
    }
    if (motion.point > 0.12 || /scan|pixel|pin|grid|lattice|weave/.test(pattern)) {
      context.fillStyle = colors[1];
      context.globalAlpha = Number(profile.alpha || 0.22) * motion.point;
      const spacing = Math.max(24, parseFloat(style.getPropertyValue('--texture-cross-spacing')) || 42);
      for (let y = spacing / 2; y < height; y += spacing * 1.5) {
        for (let x = spacing / 2; x < width; x += spacing * 1.5) {
          const column = Math.round(x / spacing);
          const row = Math.round(y / spacing);
          const gate = motion.family === 'void'
            ? (column * 7 + row * 11 + Math.floor(state.texture.phase * 2)) % 13 === 0
            : (column + row + Math.floor(motion.seed * 7)) % 3 === 0;
          if (gate) {
            const size = motion.family === 'halftone'
              ? 0.7 + (Math.sin(column * 1.7 + row * 0.9 + state.texture.phase) + 1) * 0.7
              : motion.family === 'grid' ? 1.2 : 0.9;
            context.fillRect(x - size / 2, y - size / 2, size, size);
          }
        }
      }
    }
    context.restore();
    if (!window.matchMedia?.('(prefers-reduced-motion: reduce)')?.matches && document.visibilityState !== 'hidden') {
      state.texture.frame = window.requestAnimationFrame(drawTextureField);
    } else {
      state.texture.frame = 0;
    }
  }

  function startTextureField() {
    if (state.texture.frame) return;
    state.texture.lastTime = performance.now();
    state.texture.frame = window.requestAnimationFrame(drawTextureField);
  }

  function setWorkspaceMenuOpen(open) {
    const expanded = Boolean(open && state.groups.length > 1);
    nodes.groupList.hidden = !expanded;
    nodes.workspaceButton.setAttribute('aria-expanded', String(expanded));
  }

  function conversationSkeletonHtml(count) {
    return Array.from({ length: count }, (_, index) => `
      <div class="bridge-loading-row bridge-loading-row--conversation" aria-hidden="true"
        style="--skeleton-delay:${index * 70}ms">
        <span class="bridge-loading-row__mark"></span>
        <span class="bridge-loading-row__copy"><i></i><i></i></span>
      </div>
    `).join('');
  }

  function agentSkeletonHtml(count) {
    return `
      <section class="bridge-directory-group bridge-directory-group--loading" aria-label="Loading agents">
        <header class="bridge-directory-group__head"><span>Loading agents</span><small></small></header>
        <div class="bridge-directory-group__items">
          ${Array.from({ length: count }, (_, index) => `
            <div class="bridge-loading-row bridge-loading-row--agent" aria-hidden="true"
              style="--skeleton-delay:${index * 55}ms">
              <span class="bridge-loading-row__mark"></span>
              <span class="bridge-loading-row__copy"><i></i><i></i></span>
              <span class="bridge-loading-row__presence"></span>
            </div>
          `).join('')}
        </div>
      </section>
    `;
  }

  function updateBootInterstitial({ phase, detail, completed, total, complete = false } = {}) {
    if (!nodes.bootInterstitial) return;
    if (phase) state.boot.phase = phase;
    if (detail) state.boot.detail = detail;
    if (Number.isFinite(completed)) state.boot.completed = completed;
    if (Number.isFinite(total)) state.boot.total = total;
    const progress = state.boot.total
      ? Math.min(100, Math.round((state.boot.completed / state.boot.total) * 100))
      : 8;
    nodes.bootTitle.textContent = state.boot.phase;
    nodes.bootDetail.textContent = state.boot.detail;
    nodes.bootProgress.style.setProperty('--bridge-boot-progress', `${complete ? 100 : Math.max(8, progress)}%`);
    nodes.bootInterstitial.classList.toggle('is-complete', complete);
    nodes.bootInterstitial.hidden = false;
    if (complete) {
      window.clearTimeout(state.boot.dismissTimer);
      state.boot.dismissTimer = window.setTimeout(() => {
        nodes.bootInterstitial.hidden = true;
      }, 520);
    }
  }

  function bootUpdateForRequest(completed, total) {
    const phases = [
      ['Opening the estate', 'Establishing the working session'],
      ['Mapping the estate', 'Loading people and workspaces'],
      ['Reading live work', 'Restoring active jobs and approvals'],
      ['Joining conversations', 'Bringing recent threads into view'],
      ['Tuning the Bridge', 'Applying workspace context'],
    ];
    const [phase, detail] = phases[Math.min(phases.length - 1, Math.floor((completed / Math.max(total, 1)) * phases.length))];
    updateBootInterstitial({ phase, detail, completed, total });
  }

  function renderGroups() {
    root.dataset.groupCount = String(state.groups.length);
    nodes.groupList.innerHTML = state.groups.map((group) => `
      <button class="bridge-workspace-option ${group.id === state.group ? 'is-active' : ''}" type="button"
        data-cockpit-group="${escapeHtml(group.id)}" aria-current="${group.id === state.group ? 'true' : 'false'}">
        <span class="bridge-workspace-option__mark">${escapeHtml(group.mark)}</span>
        <span class="bridge-workspace-option__copy">
          <strong>${escapeHtml(group.label)}</strong>
          <small>${escapeHtml(group.policy || 'Estate workspace')}</small>
        </span>
        ${group.id === state.group ? iconHtml('check') : ''}
      </button>
    `).join('');
    document.querySelectorAll('[data-cockpit-view]').forEach((button) => {
      const activeView = state.view === 'global-attention' ? 'attention' : state.view;
      button.classList.toggle('is-active', button.dataset.cockpitView === activeView);
    });
    const group = currentGroup();
    nodes.groupTitle.textContent = group.label;
    nodes.workspaceMark.textContent = group.mark;
    nodes.workspaceButton.disabled = state.groups.length < 2;
    nodes.workspaceButton.title = state.groups.length < 2 ? group.label : 'Switch workspace';
    if (state.groups.length < 2) setWorkspaceMenuOpen(false);
    nodes.message.placeholder = `Message ${currentDomain()?.display_name || group.label}`;
    nodes.inspectorAvatar.textContent = group.mark;
    nodes.inspectorGroup.textContent = group.label;
    nodes.inspectorPolicy.textContent = group.policy;
  }

  function renderDomains() {
    const domains = currentGroup().domains.filter((domain) => {
      if (!state.search) return true;
      return `${domain.display_name} ${domain.kind}`.toLowerCase().includes(state.search);
    });
    if (!domains.length) {
      nodes.domains.innerHTML = '<div class="cockpit-nav-empty">No configured lanes.</div>';
      return;
    }
    nodes.domains.innerHTML = domains.map((domain) => `
      <button class="cockpit-nav-item cockpit-nav-item--compact ${domain.slug === state.domain ? 'is-active' : ''}"
        type="button" data-domain="${escapeHtml(domain.slug)}">
        <span class="cockpit-nav-item__icon">${iconHtml('route')}</span>
        <span><strong>${escapeHtml(domain.display_name)}</strong><small>${escapeHtml(domain.default_policy_mode || domain.kind || 'lane')}</small></span>
      </button>
    `).join('');
  }

  function statusTone(status) {
    const value = String(status || '').toLowerCase();
    if (['done', 'completed', 'online', 'running'].includes(value)) return 'is-online';
    if (['blocked', 'failed', 'waiting_approval', 'error'].includes(value)) return 'is-warning';
    return '';
  }

  function renderWorkstreams() {
    if (state.authRequired) {
      nodes.rooms.innerHTML = '<div class="cockpit-nav-empty">Log in to load your rooms.</div>';
      return;
    }
    if (!state.bootstrapped) {
      nodes.rooms.innerHTML = conversationSkeletonHtml(2);
      return;
    }
    const rooms = state.conversations.filter((conversation) => {
      if (conversation.kind !== 'room') return false;
      if (slugify(conversation.principal_slug) !== slugify(currentGroup().slug)) return false;
      if (!state.search) return true;
      return `${conversation.title} ${(conversation.member_slugs || []).join(' ')}`
        .toLowerCase().includes(state.search);
    });
    if (!rooms.length) {
      nodes.rooms.innerHTML = '<button class="bridge-empty-action" type="button" data-create-room><svg class="cockpit-icon"><use href="#bridge-icon-plus"/></svg><span><strong>Create a room</strong><small>Bring a few bots together</small></span></button>';
      return;
    }
    nodes.rooms.innerHTML = rooms.map((conversation) => {
      const job = latestConversationJob(conversation);
      const members = conversation.member_slugs || [];
      return `
        <button class="bridge-conversation-item ${conversation.conversation_id === state.selectedConversationId ? 'is-active' : ''}"
          type="button" data-conversation-id="${escapeHtml(conversation.conversation_id)}">
          ${roomIdentityStackHtml(members)}
          <span class="bridge-conversation-item__copy">
            <span><strong>${escapeHtml(conversation.title)}</strong><time>${escapeHtml(formatTime(job?.updated_at || conversation.updated_at))}</time></span>
            <small>${escapeHtml(job ? truncate(resultText(job, jobEvents(job)) || jobObjective(job), 48) : `${members.length} bot${members.length === 1 ? '' : 's'}`)}</small>
          </span>
        </button>`;
    }).join('');
  }

  function renderAgents() {
    if (state.authRequired) {
      nodes.agentCount.textContent = '0';
      nodes.agents.innerHTML = '<div class="cockpit-nav-empty">Your bot directory appears after login.</div>';
      return;
    }
    if (!state.bootstrapped) {
      nodes.agentCount.textContent = '';
      nodes.agents.innerHTML = agentSkeletonHtml(7);
      return;
    }
    const agents = filteredAgents();
    nodes.agentCount.textContent = String(agents.length);
    if (!agents.length) {
      nodes.agents.innerHTML = '<div class="cockpit-nav-empty">No agents in this boundary.</div>';
      return;
    }
    nodes.agents.innerHTML = groupedAgents(agents).map((group) => `
      <section class="bridge-directory-group" data-directory-group="${escapeHtml(group.key)}"
        style="${escapeHtml(identityStyle(group.agents[0]?.slug || 'norman'))}">
        <header class="bridge-directory-group__head">
          <span>${escapeHtml(group.label)}</span><small>${group.agents.length}</small>
        </header>
        <div class="bridge-directory-group__items">
          ${group.agents.map((agent) => {
            const heartbeat = heartbeatFor(agent);
            const conversation = state.conversations.find((item) => (
              item.kind === 'direct'
              && slugify(item.direct_agent_slug) === slugify(agent.slug)
              && slugify(item.principal_slug) === slugify(currentGroup().slug)
            ));
            const job = conversation ? latestConversationJob(conversation) : state.jobs.find((item) => {
              const recipients = jobMetadata(item).recipients || [];
              return recipients.map(slugify).includes(slugify(agent.slug));
            });
            return `
              <button class="bridge-conversation-item ${slugify(agent.slug) === slugify(state.selectedAgent) ? 'is-active' : ''}"
                type="button" data-agent="${escapeHtml(agent.slug)}" style="${escapeHtml(identityStyle(agent.slug))}">
                ${botIdentityTileHtml(agent)}
                <span class="bridge-conversation-item__copy">
                  <span><strong>${escapeHtml(agent.display_name)}</strong><time>${escapeHtml(formatTime(job?.updated_at || job?.created_at))}</time></span>
                  <small>${escapeHtml(job ? truncate(resultText(job, jobEvents(job)) || jobObjective(job), 48) : (agent.domain_name || agent.class_name || 'Available'))}</small>
                </span>
                <i class="bridge-presence-dot ${heartbeat ? 'is-online' : ''}" title="${heartbeat ? 'Available' : 'No recent heartbeat'}"></i>
              </button>`;
          }).join('')}
        </div>
      </section>
    `).join('');
  }

  function messageMetaHtml(job) {
    if (!job) return '';
    const route = jobContract(job).route_policy || {};
    const metadata = jobMetadata(job);
    const provider = route.provider || route.preferred_provider || metadata.provider || '';
    const model = route.model || metadata.model || '';
    const status = String(job.status || '').toLowerCase();
    const chips = [];
    if (provider || model) {
      chips.push(`<span class="cockpit-message-chip" data-chip="route"><i></i>${escapeHtml([provider, model].filter(Boolean).join(' / '))}</span>`);
    }
    if (status && !['done', 'complete', 'completed', 'succeeded', 'verified'].includes(status)) {
      chips.push(`<span class="cockpit-message-chip" data-chip="state" data-tone="${escapeHtml(status)}">${escapeHtml(status.replaceAll('_', ' '))}</span>`);
    }
    return chips.join('');
  }

  function attachmentHtml(attachments, slug) {
    const items = Array.isArray(attachments) ? attachments : [];
    if (!items.length) return '';
    return `<div class="cockpit-message-media">${items.map((attachment) => {
      const token = String(attachment.token || '');
      const name = String(attachment.name || 'Attachment');
      const source = `/api/v1/bridge/conversations/agents/${encodeURIComponent(slugify(slug))}/media/${encodeURIComponent(token)}`;
      if (attachment.kind === 'image' || String(attachment.content_type || '').startsWith('image/')) {
        return `<figure class="cockpit-message-media__figure">
          <a href="${source}" target="_blank" rel="noopener" aria-label="Open ${escapeHtml(name)}">
            <img src="${source}" alt="${escapeHtml(name)}" loading="lazy" decoding="async">
          </a>
          <figcaption><span>${iconHtml('palette')}</span>${escapeHtml(name)}</figcaption>
        </figure>`;
      }
      return `<a class="cockpit-message-media__file" href="${source}" target="_blank" rel="noopener">
        <span>${iconHtml('file-text')}</span><strong>${escapeHtml(name)}</strong>
      </a>`;
    }).join('')}</div>`;
  }

  function messageHtml({ author, text, time, operator = false, slug = 'norman', job = null, continuation = false, attachments = [] }) {
    const identity = identityContract(slug);
    const head = operator ? '' : `
      <header class="cockpit-message__head">
        <span class="cockpit-message__role">${entityCartoucheHtml(author || identity.label, {
          slug: identity.slug,
          kind: 'bot',
          group: identity.group,
          decorator: '◈',
        })}</span>
        <span class="cockpit-message__telemetry">${messageMetaHtml(job)}<time>${escapeHtml(formatTime(time))}</time></span>
      </header>`;
    return `
      <article class="cockpit-message ${operator ? 'cockpit-message--operator' : 'cockpit-message--assistant'} ${continuation ? 'is-continuation' : ''}"
        data-agent="${escapeHtml(identity.slug)}" data-variant="${escapeHtml(identity.styleVariant)}" style="${escapeHtml(identityStyle(identity.slug))}">
        ${head}
        <div class="cockpit-message__body">
          ${text ? `<div class="cockpit-message__bubble">${operator ? escapeHtml(text) : renderMessageContent(text)}</div>` : ''}
          ${operator ? '' : attachmentHtml(attachments, identity.slug)}
          ${operator ? `<time class="cockpit-message__operator-time">${escapeHtml(formatTime(time))}</time>` : ''}
        </div>
      </article>`;
  }

  function eventHtml(event) {
    const type = String(event.event_type || '');
    const summary = event.summary || event.detail || type.replaceAll('.', ' ');
    const className = /approval|blocked|failed|error/.test(type)
      ? 'is-error'
      : /completed|verified|checkpoint/.test(type)
        ? 'is-complete'
        : /planner|route|handoff|delegat/.test(type) ? 'is-handoff' : '';
    const icon = /planner|route|handoff|delegat/.test(type)
      ? 'route'
      : /tool|shell/.test(type) ? 'wrench'
        : /approval|blocked|failed|error/.test(type) ? 'alert'
          : /completed|verified|checkpoint/.test(type) ? 'check' : 'activity';
    const label = type
      .replace(/^execution\./, '')
      .replace(/^model\./, '')
      .replace(/^job\./, '')
      .replaceAll('_', ' ')
      .replaceAll('.', ' / ');
    return `<div class="cockpit-event ${className}">
      <span class="cockpit-event__icon">${iconHtml(icon)}</span>
      <span class="cockpit-event__body"><small>${escapeHtml(label || 'runtime')}</small><span class="cockpit-event__summary">${escapeHtml(summary)}</span></span>
      <span class="cockpit-event__time">${escapeHtml(formatTime(event.created_at))}</span>
    </div>`;
  }

  function normalizeBridgeResponse(text) {
    const response = String(text || '').trim();
    const isLegacyStatus = /\b(?:Selected route|Local proof|Local lane availability|route receipts):|\bdeterministic TUI state\b/i.test(response);
    if (!isLegacyStatus) return response;
    return [
      'Bridge status',
      '',
      '- This legacy status reply has been condensed.',
      '- Use the live indicators above for the current route, queue, and agent state.',
    ].join('\n');
  }

  function resultText(job, events = []) {
    const result = job?.result || job?.result_json || {};
    const modelEvent = [...events].reverse().find((event) => (
      /model\.delta/.test(event.event_type || '')
    )) || [...events].reverse().find((event) => (
      /model\.completed/.test(event.event_type || '')
    ));
    const payload = eventPayload(modelEvent);
    const modelText = payload.text
      || payload.output
      || payload.response
      || payload.output_preview
      || (/model\.delta/.test(modelEvent?.event_type || '') ? modelEvent?.detail : '');
    if (String(modelText || '').trim()) return normalizeBridgeResponse(modelText);
    if (String(result.detail || '').trim()) return normalizeBridgeResponse(result.detail);
    const embedded = result.text || result.output || result.response;
    if (String(embedded || '').trim()) return normalizeBridgeResponse(embedded);
    const summary = String(result.summary || '').trim();
    if (summary && !/^(static advisory )?response completed\\.?$|^job completed\\.?$/i.test(summary)) {
      return normalizeBridgeResponse(summary);
    }
    return '';
  }

  function emptyFeed(title, detail, slug = 'norman', mark = '') {
    const texture = textureForSlug(slug);
    const identityMark = mark || texture?.mark || displaySlug(slug).slice(0, 1).toUpperCase();
    const identity = identityContract(slug);
    const agent = state.agents.find((item) => slugify(item.slug) === identity.slug) || {
      slug: identity.slug,
      display_name: identity.label,
      class_name: 'agent',
    };
    nodes.feed.innerHTML = `<div class="cockpit-feed__empty" data-agent="${escapeHtml(identity.slug)}" style="${escapeHtml(identityStyle(identity.slug))}">
      <div class="cockpit-presence" data-state="${escapeHtml(aggregateState())}" data-variant="${escapeHtml(identity.styleVariant)}"
        data-motion="${escapeHtml(textureMotionSignature(identity.texture).family)}">
        ${botIdentityTileHtml(agent, { hero: true })}
        <span class="cockpit-presence__identity">
          ${entityCartoucheHtml(identity.label, {
            slug: identity.slug,
            kind: 'tui',
            mark: identityMark,
            decorator: 'TUI',
            compact: false,
          })}
          <span class="cockpit-presence__status">${iconHtml('radio')}<span>Ready</span></span>
        </span>
      </div>
      <h2>${escapeHtml(title)}</h2>
      <p>${escapeHtml(detail)}</p>
    </div>`;
  }

  function workingMessageHtml(job, identity = responseIdentity(job)) {
    const promptStatus = job?.job_id && job.job_id === state.prompt.jobId ? state.prompt.phase : '';
    const stale = !promptStatus && isStalePendingJob(job);
    const status = stale ? 'interrupted' : String(promptStatus || job?.status || 'queued').toLowerCase();
    const label = ['running', 'executing', 'planning'].includes(status)
      ? 'Working'
      : status === 'submitting' ? 'Sending'
        : status === 'interrupted' ? 'Interrupted'
        : ['blocked', 'waiting_approval'].includes(status) ? 'Needs attention'
          : ['complete', 'completed'].includes(status) ? 'Complete'
            : ['failed', 'error', 'canceled'].includes(status) ? 'Stopped' : 'Queued';
    const icon = ['running', 'executing', 'planning'].includes(status)
      ? 'activity'
      : status === 'submitting' ? 'arrow-up'
        : status === 'interrupted' ? 'alert'
        : ['blocked', 'waiting_approval'].includes(status) ? 'alert'
          : ['complete', 'completed'].includes(status) ? 'check'
            : ['failed', 'error', 'canceled'].includes(status) ? 'close' : 'clock';
    const stage = ['running', 'executing', 'planning'].includes(status)
      ? 2
      : status === 'submitting' ? 1
        : ['blocked', 'waiting_approval', 'failed', 'error', 'canceled', 'interrupted'].includes(status) ? 3
          : 0;
    const stageDetail = ['running', 'executing', 'planning'].includes(status)
      ? 'Working through the request'
      : status === 'submitting'
        ? 'Sending this to the selected station'
        : ['blocked', 'waiting_approval'].includes(status)
          ? 'Waiting for the next decision'
          : status === 'interrupted'
            ? 'This request can be sent again'
            : 'Holding its place in the queue';
    return `<article class="cockpit-working" data-status="${escapeHtml(status)}" data-agent="${escapeHtml(slugify(identity.slug))}"
      style="${escapeHtml(identityStyle(identity.slug))}">
      <div class="cockpit-working__head">
        ${entityCartoucheHtml(identity.author, { slug: identity.slug, kind: 'bot', decorator: '◈' })}
        <span class="cockpit-working__state"><i aria-hidden="true">${iconHtml(icon)}</i>${escapeHtml(label)}</span>
      </div>
      <div class="cockpit-working__detail">${escapeHtml(stale
        ? 'This response did not start. Send it again when the runtime is available.'
        : truncate(jobObjective(job) || 'Preparing a response', 96))}</div>
      <div class="cockpit-working__progress" aria-label="${escapeHtml(stageDetail)}">
        <span class="${stage >= 0 ? 'is-complete' : ''}">Received</span>
        <span class="${stage >= 1 ? 'is-complete' : ''}">Queued</span>
        <span class="${stage >= 2 ? 'is-active' : ''}">Working</span>
        <span class="${stage >= 3 ? 'is-complete' : ''}">Result</span>
      </div>
      <div class="cockpit-working__signal" aria-hidden="true"><i></i><i></i><i></i><i></i><i></i></div>
    </article>`;
  }

  function renderGeneralFeed() {
    const conversation = selectedConversation();
    const jobs = conversation && conversation.kind !== 'direct'
      ? filteredJobs().filter(isBridgeJob).slice(0, 16).reverse()
      : [];
    const stationSlug = conversation?.kind === 'direct'
      ? slugify(conversation.direct_agent_slug)
      : '';
    const stationTurns = stationSlug
      ? (state.stationHistory[stationSlug]?.items || [])
      : [];
    const historyLoading = stationSlug && state.stationHistoryLoading === stationSlug;
    const historyError = stationSlug ? state.stationHistoryErrors[stationSlug] : '';
    const localPrompt = (
      ['submitting', 'queued', 'running'].includes(state.prompt.phase)
      && (!state.prompt.stationSlug || state.prompt.stationSlug === stationSlug)
    )
      ? {
          job_id: state.prompt.jobId || '',
          objective: state.prompt.objective,
          status: state.prompt.phase,
          created_at: new Date(state.prompt.startedAt || Date.now()).toISOString(),
          metadata: { recipients: [...state.selectedRecipients] },
        }
      : null;
    if (!jobs.length && !localPrompt && !stationTurns.length) {
      if (historyLoading) {
        nodes.feed.innerHTML = `<div class="cockpit-feed__empty cockpit-history-state">
          <span class="cockpit-history-state__icon">${iconHtml('archive')}</span>
          <h2>Loading station history</h2>
          <p>Connecting this direct message to ${escapeHtml(displaySlug(stationSlug))}'s canonical thread.</p>
        </div>`;
        return;
      }
      const selected = state.agents.find((agent) => slugify(agent.slug) === slugify(state.selectedAgent));
      const name = selected?.display_name || (state.selectedAgent ? displaySlug(state.selectedAgent) : 'Norman');
      const slug = selected?.slug || state.selectedAgent || 'norman';
      emptyFeed(
        `Talk to ${name}`,
        historyError
          ? 'This station is available, but its prior thread could not be loaded.'
          : conversation
          ? 'This conversation is ready.'
          : `${currentGroup().label} is ready. Choose a room or direct message to begin.`,
        slug,
      );
      return;
    }
    const visibleJobs = localPrompt ? [...jobs, localPrompt] : jobs;
    const historyHtml = stationTurns.map((turn, index) => {
      const time = turn.finished_at || turn.started_at;
      const response = normalizeBridgeResponse(turn.response || turn.error);
      const attachments = turn.attachments || [];
      const hasAssistantOutput = Boolean(response || attachments.length);
      return `<section class="cockpit-turn cockpit-turn--history" data-station-turn="${escapeHtml(turn.turn_id || `${stationSlug}-${index}`)}">
        <div class="cockpit-turn__messages">
          ${messageHtml({ author: 'You', text: turn.prompt, time: turn.started_at || time, operator: true })}
          ${hasAssistantOutput ? messageHtml({
            author: state.stationHistory[stationSlug]?.agent_name || displaySlug(stationSlug),
            slug: stationSlug,
            text: response,
            time,
            job: {
              status: turn.error ? 'failed' : 'complete',
              metadata: { model: turn.model, provider: turn.runtime },
            },
            attachments,
          }) : ''}
        </div>
      </section>`;
    }).join('');
    const bridgeHtml = visibleJobs.map((job) => {
      const response = resultText(job, jobEvents(job));
      const identity = responseIdentity(job);
      const objective = jobObjective(job);
      return `<section class="cockpit-turn" data-job-id="${escapeHtml(job.job_id || '')}">
        <div class="cockpit-turn__messages">
          ${objective ? messageHtml({ author: 'You', text: objective, time: job.created_at, operator: true, job }) : ''}
          ${response
            ? messageHtml({ author: identity.author, slug: identity.slug, text: response, time: job.updated_at, job })
            : workingMessageHtml(job, identity)}
        </div>
      </section>`;
    }).join('');
    nodes.feed.innerHTML = `${historyHtml}${bridgeHtml}`;
    nodes.feed.scrollTop = nodes.feed.scrollHeight;
  }

  async function loadStationHistory(agentSlug, { force = false } = {}) {
    const slug = slugify(agentSlug);
    if (!slug || state.authRequired) return;
    if (!force && state.stationHistory[slug]) return;
    state.stationHistoryLoading = slug;
    delete state.stationHistoryErrors[slug];
    renderFeed();
    try {
      state.stationHistory[slug] = await fetchJson(
        `${API}/bridge/conversations/agents/${encodeURIComponent(slug)}/history?limit=100`,
      );
    } catch (error) {
      state.stationHistoryErrors[slug] = error.message || 'Station history is unavailable';
    } finally {
      if (state.stationHistoryLoading === slug) state.stationHistoryLoading = '';
      if (slugify(selectedConversation()?.direct_agent_slug) === slug) renderFeed();
      updateComposerState();
    }
  }

  async function waitForStationResponse(slug, knownTurnIds) {
    const deadline = Date.now() + 300000;
    while (Date.now() < deadline && state.prompt.stationSlug === slug && promptBusy()) {
      await new Promise((resolve) => window.setTimeout(resolve, 2000));
      try {
        const history = await fetchJson(
          `${API}/bridge/conversations/agents/${encodeURIComponent(slug)}/history?limit=100`,
          { timeoutMs: 10000 },
        );
        state.stationHistory[slug] = history;
        const completed = (history.items || []).find((turn, index) => {
          const id = String(turn.turn_id || `${turn.started_at || ''}:${index}`);
          return !knownTurnIds.has(id) && Boolean(
            turn.response || turn.error || (turn.attachments || []).length
          );
        });
        renderFeed();
        if (completed) {
          setPromptPhase(completed.error ? 'failed' : 'complete', {
            error: completed.error || '',
          });
          renderFeed();
          return;
        }
      } catch {
        // The station may be busy writing its next canonical turn.
      }
    }
    if (promptBusy() && state.prompt.stationSlug === slug) {
      setPromptPhase('failed', {
        error: 'The station is still working. Its response will appear in history when complete.',
      });
      renderFeed();
    }
  }

  function renderJobFeed() {
    const snapshot = state.activity || {};
    const job = snapshot.job || state.jobs.find((item) => item.job_id === state.selectedJobId);
    if (!job) return renderGeneralFeed();
    const events = snapshot.events || [];
    const response = resultText(job, events);
    const identity = responseIdentity(job);
    const eventRows = events
      .filter((event) => !/job\.created/.test(event.event_type || ''))
      .map(eventHtml)
      .join('');
    nodes.feed.innerHTML = `<section class="cockpit-turn cockpit-turn--selected" data-job-id="${escapeHtml(job.job_id || '')}">
      <div class="cockpit-turn__messages">
        ${jobObjective(job) ? messageHtml({ author: 'You', text: jobObjective(job), time: job.created_at, operator: true, job }) : ''}
        ${eventRows ? `<div class="cockpit-event-stack">${eventRows}</div>` : ''}
        ${response
          ? messageHtml({ author: identity.author, slug: identity.slug, text: response, time: job.updated_at, job })
          : workingMessageHtml(job, identity)}
      </div>
    </section>`;
    nodes.feed.scrollTop = nodes.feed.scrollHeight;
  }

  function renderAttention() {
    const items = attentionItems().filter((item) => (
      state.view === 'global-attention' || item.group === state.group
    ));
    if (!items.length) {
      emptyFeed('No items need attention', 'Approvals, blocked jobs, and runtime failures will appear here.', 'norman', '!');
      return;
    }
    nodes.feed.innerHTML = items.map((item) => {
      const group = state.groups.find((candidate) => candidate.id === item.group);
      const groupLabel = group?.label || item.group || 'Estate';
      if (item.type === 'command_approval') {
        const approval = item.approval || {};
        const destructive = String(approval.command_class || '').toLowerCase() === 'destructive';
        const token = destructive ? String(approval.confirm_token || '') : '';
        return `
          <article class="cockpit-approval-card" data-approval-card="${escapeHtml(item.id)}">
            <span class="cockpit-approval-card__mark">!</span>
            <div class="cockpit-approval-card__body">
              <div class="cockpit-approval-card__head">
                <strong>${escapeHtml(item.title)}</strong><span>${escapeHtml(groupLabel)}</span>
              </div>
              <small>${escapeHtml(item.detail)}</small>
              ${approval.command_text ? `<code>${escapeHtml(approval.command_text)}</code>` : ''}
              ${token ? `<label class="cockpit-approval-token"><span>Type <strong>${escapeHtml(token)}</strong> to approve</span><input type="text" autocomplete="off" spellcheck="false" data-approval-token></label>` : ''}
              <div class="cockpit-action-error" data-approval-error hidden></div>
              <div class="cockpit-approval-card__actions">
                <button type="button" data-approval-kind="command" data-approval-id="${escapeHtml(approval.id)}" data-approval-action="reject">Reject</button>
                <button type="button" data-approval-kind="command" data-approval-id="${escapeHtml(approval.id)}" data-approval-action="approve" data-required-token="${escapeHtml(token)}">Approve</button>
              </div>
            </div>
          </article>`;
      }
      if (item.type === 'runtime_approval') {
        return `
          <article class="cockpit-approval-card" data-approval-card="${escapeHtml(item.id)}">
            <span class="cockpit-approval-card__mark">!</span>
            <div class="cockpit-approval-card__body">
              <div class="cockpit-approval-card__head">
                <strong>${escapeHtml(item.title)}</strong><span>${escapeHtml(groupLabel)}</span>
              </div>
              <small>${escapeHtml(item.detail)}</small>
              <label class="cockpit-approval-token"><span>Type <strong>ENABLE LIVE RUNTIME</strong> to approve</span><input type="text" autocomplete="off" spellcheck="false" data-approval-token></label>
              <div class="cockpit-action-error" data-approval-error hidden></div>
              <div class="cockpit-approval-card__actions">
                <button type="button" data-approval-kind="runtime" data-runtime-job-id="${escapeHtml(item.job_id)}" data-approval-action="reject">Reject</button>
                <button type="button" data-approval-kind="runtime" data-runtime-job-id="${escapeHtml(item.job_id)}" data-approval-action="approve" data-required-token="ENABLE LIVE RUNTIME">Approve</button>
              </div>
            </div>
          </article>`;
      }
      return `
        <button class="cockpit-attention-card" type="button" data-job-id="${escapeHtml(item.job_id)}">
          <span class="cockpit-attention-card__mark"></span><span><strong>${escapeHtml(item.title)}</strong><small>${escapeHtml(item.detail)}</small></span>
          <span class="cockpit-status">${escapeHtml(groupLabel)}</span>
        </button>`;
    }).join('');
  }

  function renderFeed() {
    if (state.authRequired) {
      nodes.feed.innerHTML = `<div class="cockpit-feed__empty cockpit-auth-gate">
        <span class="cockpit-auth-gate__mark">${iconHtml('key')}</span>
        <h2>Log in to Norman</h2>
        <p>Log in to load your rooms, agents, and station history.</p>
        <button type="button" class="cockpit-auth-gate__action" data-sign-in>${iconHtml('key')}<span>Log in</span></button>
      </div>`;
      return;
    }
    if (state.view.includes('attention')) renderAttention();
    else if (state.selectedJobId) renderJobFeed();
    else renderGeneralFeed();
  }

  function renderRoom() {
    if (state.authRequired) {
      nodes.roomTitle.innerHTML = entityCartoucheHtml('Norman Bridge', {
        slug: 'norman',
        kind: 'tui',
        mark: 'N',
        decorator: 'LOCKED',
      });
      nodes.roomSubtitle.textContent = 'Secure session required.';
      nodes.message.placeholder = 'Log in to message Norman';
      return;
    }
    const group = currentGroup();
    const domain = currentDomain();
    const conversation = selectedConversation();
    let title = domain ? `${group.label} / ${domain.display_name}` : `${group.label} / General`;
    let subtitle = domain ? `${domain.kind || 'Operational'} lane` : 'Norman coordinates this principal.';
    let mark = domain ? String(domain.display_name).slice(0, 1).toUpperCase() : group.mark;
    if (conversation) {
      const directAgent = conversation.kind === 'direct'
        ? state.agents.find((item) => slugify(item.slug) === slugify(conversation.direct_agent_slug))
        : null;
      title = directAgent?.display_name || conversation.title;
      const memberCount = (conversation.member_slugs || []).length;
      subtitle = conversation.kind === 'room'
        ? `${memberCount} bot${memberCount === 1 ? '' : 's'} in this room`
        : (directAgent?.domain_name || directAgent?.class_name || 'Direct message');
      if (conversation._local_only) subtitle += ' · Saved on this device';
      mark = conversation.kind === 'room'
        ? '#'
        : identityContract(conversation.direct_agent_slug).mark;
    } else if (state.view.includes('attention')) {
      title = state.view === 'global-attention' ? 'Estate / Attention' : `${group.label} / Attention`;
      subtitle = 'Approvals, blockers, and failed work.';
      mark = '!';
    } else if (state.selectedAgent) {
      const agent = state.agents.find((item) => slugify(item.slug) === slugify(state.selectedAgent));
      const texture = textureForSlug(state.selectedAgent);
      title = agent?.display_name || displaySlug(state.selectedAgent);
      subtitle = `${group.label} agent / ${agent?.domain_name || 'general'}`;
      mark = texture?.mark || String(agent?.display_name || state.selectedAgent || '?').slice(0, 1).toUpperCase();
    } else if (state.selectedJobId) {
      const job = state.jobs.find((item) => item.job_id === state.selectedJobId);
      title = truncate(jobObjective(job) || 'Workstream', 68);
      subtitle = `${group.label} workstream / ${job?.status || 'loading'}`;
      mark = '[]';
    }
    const activeSlug = conversation?.direct_agent_slug || state.selectedAgent || responseIdentity(
      state.activity?.job || state.jobs.find((item) => item.job_id === state.selectedJobId),
    ).slug || 'norman';
    const cartoucheKind = state.view.includes('attention') ? 'service' : 'tui';
    nodes.roomTitle.innerHTML = entityCartoucheHtml(title, {
      slug: activeSlug,
      kind: cartoucheKind,
      group: state.view.includes('attention') ? 'shared' : identityContract(activeSlug).group,
      mark,
      decorator: state.view.includes('attention') ? 'OPS' : 'TUI',
    });
    nodes.roomSubtitle.textContent = subtitle;
    nodes.message.placeholder = `Message ${conversation ? title : (state.selectedAgent ? title : (domain?.display_name || group.label))}`;
  }

  function renderRecipients() {
    if (state.authRequired) {
      nodes.recipientRow.hidden = true;
      nodes.selectedRecipients.innerHTML = '';
      state.composeHintDefault = 'Sign in to send';
      updateComposerState();
      return;
    }
    const conversation = selectedConversation();
    nodes.recipientRow.hidden = conversation?.kind !== 'room';
    nodes.selectedRecipients.innerHTML = state.selectedRecipients.map((slug) => {
      const agent = state.agents.find((item) => slugify(item.slug) === slugify(slug));
      const label = agent?.display_name || displaySlug(slug);
      return `<button class="cockpit-recipient" type="button" data-remove-recipient="${escapeHtml(slug)}"
        aria-label="Remove ${escapeHtml(label)}">${entityCartoucheHtml(label, {
          slug,
          kind: 'bot',
          decorator: '×',
        })}</button>`;
    }).join('');
    const names = state.selectedRecipients.map((slug) => (
      state.agents.find((item) => slugify(item.slug) === slugify(slug))?.display_name || slug
    ));
    state.composeHintDefault = '';
    updateComposerState();
  }

  function renderInspector() {
    const job = state.activity?.job
      || state.jobs.find((item) => item.job_id === state.selectedJobId);
    if (!job) {
      nodes.jobDetails.innerHTML = '<div class="cockpit-detail-empty">Select a workstream to inspect its route, state, and artifacts.</div>';
      nodes.openJob.disabled = true;
      nodes.cancelJob.disabled = true;
    } else {
      const route = jobContract(job).route_policy || {};
      const checkpointCount = (job.checkpoint_capsules || []).length;
      const artifactCount = (job.artifacts || state.workstream?.artifacts || []).length;
      nodes.jobDetails.innerHTML = [
        ['Status', job.status || 'unknown'],
        ['Job', job.job_id],
        ['Workstream', job.workstream_id || 'standalone'],
        ['Parent', job.parent_job_id || 'none'],
        ['Principal', currentGroup().label],
        ['Lane', jobDomain(job) || 'general'],
        ['Provider', route.provider || route.preferred_provider || 'policy'],
        ['Model', route.model || 'policy selected'],
        ['Checkpoints', String(checkpointCount)],
        ['Artifacts', String(artifactCount)],
        ['Updated', formatTime(job.updated_at || job.created_at)],
      ].map(([label, value]) => `<div class="cockpit-detail"><span>${escapeHtml(label)}</span><strong title="${escapeHtml(value)}">${escapeHtml(value)}</strong></div>`).join('');
      nodes.openJob.disabled = false;
      nodes.cancelJob.disabled = ['done', 'failed', 'canceled'].includes(job.status);
    }
    const recipients = new Set(['norman', ...state.selectedRecipients]);
    for (const recipient of (job ? jobMetadata(job).recipients || [] : [])) recipients.add(recipient);
    nodes.participants.innerHTML = [...recipients].map((slug) => {
      const name = slug === 'norman'
        ? 'Norman'
        : state.agents.find((item) => slugify(item.slug) === slugify(slug))?.display_name || slug;
      return `<span class="cockpit-participant">${entityCartoucheHtml(name, {
        slug,
        kind: 'bot',
        decorator: '◈',
      })}</span>`;
    }).join('');
    renderCrew();
  }

  function renderCrew() {
    const tasks = state.workstream?.subtasks || [];
    nodes.crewSection.hidden = tasks.length === 0;
    if (!tasks.length) {
      nodes.crewList.innerHTML = '';
      return;
    }
    nodes.crewList.innerHTML = tasks.map((task) => {
      const metadata = jobMetadata(task);
      const recipient = metadata.agent || metadata.target_agent || (metadata.recipients || [])[0] || 'Norman';
      const status = String(task.status || 'queued').toLowerCase();
      const tone = ['done', 'completed', 'running'].includes(status)
        ? 'ok'
        : ['blocked', 'failed', 'waiting_approval', 'error'].includes(status) ? 'warn' : 'neutral';
      return `
        <button class="cockpit-crew-item" type="button" data-job-id="${escapeHtml(task.job_id)}">
          <span class="cockpit-crew-item__state" data-tone="${tone}"></span>
          <span><strong>${escapeHtml(truncate(task.objective || 'Subtask', 48))}</strong><small>${escapeHtml(recipient)}</small></span>
          <span>${escapeHtml(status)}</span>
        </button>`;
    }).join('');
  }

  function meterParts(node, label, value, detail, tone = 'neutral', fill = null) {
    node.dataset.tone = tone;
    node.querySelector('strong').textContent = value;
    node.querySelector('small').textContent = label;
    node.title = `${label}: ${value}${detail ? `. ${detail}` : ''}`;
    node.setAttribute('aria-label', node.title);
    if (fill !== null) node.style.setProperty('--meter-fill', `${Math.max(0, Math.min(100, fill))}%`);
  }

  function renderRuntime() {
    const status = String(state.worker.status || '').toLowerCase();
    const authRequired = state.authRequired;
    const available = !authRequired && state.worker._available !== false;
    const runtimeLabel = nodes.runtimeStatus.querySelector('.cockpit-transport__label');
    const runtimeIcon = nodes.runtimeStatus.querySelector('.cockpit-transport__icon');
    runtimeLabel.textContent = available ? 'Linked' : authRequired ? 'Login required' : 'Runtime unavailable';
    runtimeIcon.innerHTML = iconHtml(available ? 'radio' : authRequired ? 'key' : 'alert');
    nodes.runtimeStatus.dataset.tone = available ? 'ok' : 'warn';
    nodes.menuTransport.textContent = runtimeLabel.textContent;

    const runtimeJobs = recentBridgeRuntimeJobs();
    const running = runtimeJobs.filter((job) => ['running', 'executing', 'planning'].includes(job.status)).length;
    const queued = runtimeJobs.filter((job) => ['queued', 'pending', 'accepted'].includes(job.status)).length;
    const blocked = runtimeJobs.filter((job) => ['blocked', 'waiting_approval'].includes(job.status)).length;
    const queueValue = blocked ? `${blocked} blocked` : running ? `${running} active` : queued ? `${queued} queued` : 'Clear';
    meterParts(nodes.queueMeter, 'Queue', queueValue, `${queued} queued / ${running} running / ${blocked} blocked`, blocked ? 'warn' : running ? 'active' : 'ok');

    const usage = state.routeSummary.usage_ledger || state.worker.usage_ledger || {};
    const total = Number(usage.total_tokens || 0);
    const offline = Number(usage.offline_tokens || 0);
    const cloud = Number(usage.cloud_llm_tokens || 0);
    const localPct = Number(usage.local_llm_percent || usage.offline_percent || 0);
    meterParts(
      nodes.tokenMeter,
      'Tokens',
      total ? compactNumber(total) : '--',
      total ? `${compactNumber(offline)} local / ${compactNumber(cloud)} cloud` : 'Ledger empty',
      total ? (localPct >= 80 ? 'ok' : localPct >= 60 ? 'watch' : 'warn') : 'neutral',
      total ? localPct : 0,
    );

    const route = state.routeSummary.route || {};
    const latest = state.routeSummary.latest || usage.latest || {};
    const routeTotal = Number(route.total || 0);
    const routeValue = latest.provider || (routeTotal ? `${Number(route.local_percent || 0)}% local` : 'Policy');
    const routeDetail = latest.model || (routeTotal ? `${route.allowed || 0} allowed / ${route.blocked || 0} blocked` : 'No evidence');
    meterParts(nodes.routeMeter, 'Route', routeValue, routeDetail, Number(route.blocked || 0) ? 'warn' : routeTotal ? 'ok' : 'neutral');

    const known = filteredAgents().length;
    const live = filteredAgents().filter(heartbeatFor).length;
    meterParts(
      nodes.agentMeter,
      'Agents',
      live ? `${live} live` : `${known} known`,
      `${live} recent heartbeat${live === 1 ? '' : 's'} / ${known} known`,
      live ? 'ok' : 'neutral',
    );

    const warnings = attentionItems();
    meterParts(nodes.warningMeter, 'Alerts', warnings.length ? String(warnings.length) : 'Clear', warnings.length ? 'Approval or runtime hold' : 'No holds', warnings.length ? 'warn' : 'ok');
    nodes.menuCount.textContent = String(warnings.length);
    nodes.menuCount.classList.toggle('d-none', warnings.length === 0);

    nodes.warningStrip.hidden = available && warnings.length === 0;
    if (!nodes.warningStrip.hidden) {
      nodes.warningTitle.textContent = !available
        ? authRequired
          ? 'Log in to connect Norman'
          : 'Runtime is unavailable'
        : `${warnings.length} item${warnings.length === 1 ? '' : 's'} need attention`;
      nodes.warningDetail.textContent = !available
        ? authRequired
          ? 'Device-saved chats remain available, but syncing and agent runs require an authenticated session.'
          : 'Known agents and saved chats remain visible, but new jobs cannot execute until the runtime reconnects.'
        : 'Review approvals, blocked work, and failed runs.';
      nodes.warningAction.textContent = authRequired ? 'Log in' : 'Review';
      nodes.warningAction.dataset.authAction = authRequired ? 'sign-in' : '';
    }
    void status;
  }

  function renderAttentionCounts() {
    const count = attentionItems().length;
    for (const target of [nodes.attentionCount, nodes.navAttentionCount]) {
      target.textContent = String(count);
      target.classList.toggle('d-none', count === 0);
    }
  }

  function menuRows(panel) {
    const usage = state.routeSummary.usage_ledger || state.worker.usage_ledger || {};
    const route = state.routeSummary.route || {};
    const warnings = attentionItems();
    const rows = {
      overview: [
        ['Boundary', currentGroup().label],
        ['Lane', currentDomain()?.display_name || 'General'],
        ['Identity', textureForSelection()?.pattern || 'Norman'],
        ['Typeface', textureForSelection()?.font || 'IBM Plex Sans'],
        ['Sounds', state.preferences.feedbackSounds],
        ['Runtime', nodes.runtimeStatus.textContent],
        ['Workstreams', String(filteredJobs().length)],
      ],
      route: [
        ['Route decisions', String(route.total || 0)],
        ['Allowed', String(route.allowed || 0)],
        ['Blocked', String(route.blocked || 0)],
        ['Local share', route.total ? `${route.local_percent || 0}%` : 'Unavailable'],
      ],
      queues: [
        ['Runnable', String(state.worker.runnable_count || 0)],
        ['Running', String(state.jobs.filter((job) => job.status === 'running').length)],
        ['Waiting approval', String(state.jobs.filter((job) => job.status === 'waiting_approval').length)],
        ['Failed', String(state.jobs.filter((job) => job.status === 'failed').length)],
      ],
      usage: [
        ['Tracked tokens', usage.total_tokens ? compactNumber(usage.total_tokens) : 'Unavailable'],
        ['Local/offline', usage.offline_tokens ? compactNumber(usage.offline_tokens) : '--'],
        ['Cloud LLM', usage.cloud_llm_tokens ? compactNumber(usage.cloud_llm_tokens) : '--'],
        ['Local LLM share', usage.total_tokens ? `${usage.local_llm_percent || 0}%` : '--'],
      ],
      agents: [
        ['Known in boundary', String(filteredAgents().length)],
        ['Recent heartbeats', String(filteredAgents().filter(heartbeatFor).length)],
        ['Estate total', String(state.agents.length)],
        ['Selected', state.selectedAgent || 'None'],
      ],
      warnings: warnings.length
        ? warnings.slice(0, 8).map((item) => [truncate(item.title, 34), truncate(item.detail, 46)])
        : [['Status', 'No approvals or blocked work']],
    };
    return rows[panel] || rows.overview;
  }

  function renderMenuPanel() {
    nodes.menuPanel.innerHTML = menuRows(state.menuPanel).map(([label, value]) => (
      `<div class="cockpit-menu__row"><span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong></div>`
    )).join('');
  }

  function renderAll() {
    renderGroups();
    renderDomains();
    renderWorkstreams();
    renderAgents();
    renderRoom();
    renderRecipients();
    renderAttentionCounts();
    renderInspector();
    renderRuntime();
    renderMenuPanel();
    renderFeed();
    syncMicrotexture();
  }

  async function loadBootstrap({ quiet = false } = {}) {
    if (state.loading) return;
    state.loading = true;
    state.boot.completed = 0;
    state.boot.total = 0;
    updateBootInterstitial({
      phase: 'Opening the estate',
      detail: 'Preparing a working session',
      completed: 0,
      total: 8,
    });
    const localConversations = loadLocalConversations();
    if (!state.conversations.length && localConversations.length) {
      state.conversations = localConversations;
    }
    if (!quiet) renderRuntime();

    // First paint never depends on the network. The embedded identity map is
    // sufficient to make DMs usable while registry and contact-sheet details
    // reconcile in the background.
    if (!state.authRequired && state.agents.length <= 1) {
      state.agents = provisionalAgents();
    }
    state.bootstrapped = true;
    renderAll();

    const pendingRequests = [
      fetchJson(`${API}/estate/overview`, { timeoutMs: 12000 }),
      fetchJson(`${API}/console-runtime/jobs?limit=200`, { timeoutMs: 8000 }),
      fetchJson(`${API}/approvals/?status=pending&limit=100`, { timeoutMs: 8000 }),
      fetchJson('/api/console-ui/heartbeats', { timeoutMs: 6000 }),
      fetchJson(`${API}/console-runtime/worker/status`, { timeoutMs: 6000 }),
      fetchJson(`${API}/console-runtime/route-summary?limit=1000`, { timeoutMs: 8000 }),
      fetchJson('/static/textures/tui_microtexture_reference.json', { timeoutMs: 25000 }),
      fetchJson(`${API}/bridge/conversations`, { timeoutMs: 8000 }),
    ];

    state.boot.total = pendingRequests.length;
    const requests = await Promise.allSettled(pendingRequests.map((request) => request.finally(() => {
      state.boot.completed += 1;
      bootUpdateForRequest(state.boot.completed, state.boot.total);
    })));
    const [estate, jobs, approvals, heartbeats, worker, routeSummary, textureCatalog, conversations] = requests;
    if (heartbeats.status === 'fulfilled') state.heartbeats = heartbeats.value.items || [];
    if (estate.status === 'fulfilled') {
      state.groups = normalizeGroups(estate.value);
      if (!state.groups.some((group) => group.id === state.group)) state.group = state.groups[0].id;
      state.agents = normalizeAgents(estate.value);
      if (requestedAgent && !state.requestedAgentApplied) {
        const requested = state.agents.find((agent) => slugify(agent.slug) === slugify(requestedAgent));
        if (requested) {
          state.group = requested.principal_id;
          state.domain = requested.domain_slug;
          state.selectedAgent = requested.slug;
          state.selectedRecipients = [requested.slug];
          state.view = 'agent';
        }
        state.requestedAgentApplied = true;
      }
    }
    if (jobs.status === 'fulfilled') state.jobs = jobs.value.items || [];
    if (approvals.status === 'fulfilled') state.approvals = approvals.value || [];
    const workerAuthRequired = (
      worker.status === 'rejected'
      && Number(worker.reason?.status) === 401
    );
    state.worker = worker.status === 'fulfilled'
      ? { ...worker.value, _available: true, _statusDelayed: false }
      : workerAuthRequired
        ? {
            _available: false,
            _authRequired: true,
            error: worker.reason?.message || 'Login required',
          }
        : {
            ...state.worker,
            _available: true,
            _statusDelayed: true,
            status_error: worker.reason?.message || 'Runtime telemetry delayed',
          };
    state.authRequired = state.worker._authRequired === true;
    root.dataset.authenticated = state.authRequired ? 'false' : 'true';
    if (routeSummary.status === 'fulfilled') state.routeSummary = routeSummary.value || {};
    if (textureCatalog.status === 'fulfilled') {
      state.textureCatalog = Array.isArray(textureCatalog.value)
        ? textureCatalog.value
        : textureCatalog.value.items || textureCatalog.value.agents || [];
      if (!state.authRequired) state.agents = mergeCatalogAgents(state.agents);
    }
    if (state.authRequired) {
      state.groups = [FALLBACK_GROUP];
      state.group = FALLBACK_GROUP.id;
      state.domain = '';
      state.jobs = [];
      state.approvals = [];
      state.heartbeats = [];
      state.agents = [{ ...FALLBACK_NORMAN }];
      state.selectedJobId = '';
      state.selectedAgent = '';
      state.selectedRecipients = [];
      state.view = 'general';
    } else {
      restoreAfterSignIn();
    }
    if (conversations.status === 'fulfilled') {
      mergeConversations(conversations.value.items || [], localConversations);
    } else {
      mergeConversations([], [
        ...state.conversations.filter((item) => item._local_only),
        ...localConversations,
      ]);
    }
    state.loading = false;
    updateBootInterstitial({
      phase: 'Bridge ready',
      detail: 'Your workspace is live',
      completed: state.boot.total,
      total: state.boot.total,
      complete: true,
    });
    reconcilePromptState();
    renderAll();
    const conversation = selectedConversation();
    if (conversation) void hydrateConversationActivities(conversation);
  }

  async function hydrateConversationActivities(conversation) {
    if (!conversation || state.authRequired) return;
    const jobs = state.jobs
      .filter((job) => isBridgeJob(job) && conversationJob(job, conversation))
      .slice(0, 16);
    const missing = jobs.filter((job) => (
      job?.job_id
      && !state.jobActivities[job.job_id]
      && !resultText(job)
    ));
    if (!missing.length) return;
    await Promise.allSettled(missing.map(async (job) => {
      state.jobActivities[job.job_id] = await fetchJson(
        `${API}/console-runtime/jobs/${encodeURIComponent(job.job_id)}?limit=80`,
      );
    }));
    if (state.selectedConversationId === conversation.conversation_id) {
      renderAgents();
      renderFeed();
    }
  }

  async function loadSelectedActivity({ quiet = false } = {}) {
    if (!state.selectedJobId) return;
    try {
      state.activity = await fetchJson(`${API}/console-runtime/jobs/${encodeURIComponent(state.selectedJobId)}?limit=300`);
      const job = state.activity.job || {};
      state.lastEventSequence = Math.max(
        0,
        ...(state.activity.events || []).map((event) => Number(event.sequence || 0)),
      );
      state.workstream = job.workstream_id
        ? await fetchJson(`${API}/console-runtime/workstreams/${encodeURIComponent(job.workstream_id)}`).catch(() => null)
        : null;
      reconcilePromptState();
      renderFeed();
      renderInspector();
      renderRoom();
      connectJobEventStream(state.selectedJobId);
    } catch (error) {
      if (!quiet) nodes.feed.innerHTML = `<div class="cockpit-nav-empty">${escapeHtml(error.message)}</div>`;
    }
  }

  function closeEventStream() {
    if (state.eventSource) state.eventSource.close();
    state.eventSource = null;
    state.eventSourceJobId = '';
  }

  function promptPhaseForEvent(type) {
    if (/job\.(completed)|verification\.completed/.test(type)) return 'complete';
    if (/job\.(failed|canceled)|runtime\.error/.test(type)) return 'failed';
    if (/job\.blocked|approval\.(required)|job\.approval_required/.test(type)) return 'blocked';
    if (/job\.started|model\.(started|requested|delta)|tool\.started|shell\.started|execution\.advisory_only/.test(type)) return 'running';
    if (/job\.created/.test(type)) return 'queued';
    return '';
  }

  function handleRuntimeEvent(message) {
    const jobId = state.eventSourceJobId;
    if (!message.data || !jobId) return;
    let event;
    try {
      event = JSON.parse(message.data);
    } catch {
      return;
    }
    const sequence = Number(event.sequence || message.lastEventId || 0);
    if (sequence && sequence <= state.lastEventSequence) return;
    state.lastEventSequence = Math.max(state.lastEventSequence, sequence);
    const type = String(event.event_type || '');
    const phase = promptPhaseForEvent(type);
    const job = state.jobs.find((item) => item.job_id === jobId);
    const localStatus = {
      queued: 'queued',
      running: 'running',
      blocked: 'blocked',
      failed: 'failed',
      complete: 'completed',
    }[phase];
    if (job && localStatus) job.status = localStatus;
    const selected = state.selectedJobId === jobId;
    state.jobActivities[jobId] ||= { job, events: [] };
    state.jobActivities[jobId].job ||= job;
    if (state.jobActivities[jobId].job && localStatus) {
      state.jobActivities[jobId].job.status = localStatus;
    }
    state.jobActivities[jobId].events ||= [];
    state.jobActivities[jobId].events.push(event);
    if (selected) {
      state.activity ||= { job, events: [] };
      state.activity.job ||= job;
      if (state.activity.job && localStatus) state.activity.job.status = localStatus;
      state.activity.events ||= [];
      state.activity.events.push(event);
    }
    if (state.prompt.jobId === jobId && phase) {
      setPromptPhase(phase);
    } else if (!phase) {
      playInteractionTone('tick');
    }
    const identity = responseIdentity(job || state.activity?.job);
    if (phase === 'complete') playCompletionBell(identity.slug);
    if (selected) {
      renderJobFeed();
      renderInspector();
      renderRoom();
    } else {
      renderGeneralFeed();
    }
    if (/job\.(completed|failed|blocked|canceled)|approval\.(approved|rejected)/.test(type)) {
      loadBootstrap({ quiet: true });
      if (selected) loadSelectedActivity({ quiet: true });
    }
  }

  function connectJobEventStream(jobId) {
    closeEventStream();
    if (!jobId || typeof window.EventSource !== 'function') return;
    state.eventSourceJobId = jobId;
    const source = new EventSource(
      `${API}/console-runtime/jobs/${encodeURIComponent(jobId)}/events/stream?after=${state.lastEventSequence}`,
      { withCredentials: true },
    );
    const eventTypes = [
      'job.created', 'job.started', 'job.completed', 'job.failed', 'job.blocked', 'job.canceled',
      'job.checkpointed', 'job.approval_required', 'model.started', 'model.completed',
      'tool.started', 'tool.completed', 'tool.failed', 'shell.started', 'shell.completed',
      'planner.decision', 'route.decided', 'approval.required', 'approval.approved',
      'approval.rejected', 'artifact.created', 'verification.completed', 'runtime.error',
      'execution.advisory_only',
    ];
    eventTypes.forEach((type) => source.addEventListener(type, handleRuntimeEvent));
    source.onerror = () => {
      if (state.eventSource === source && source.readyState === EventSource.CLOSED) closeEventStream();
    };
    state.eventSource = source;
  }

  async function decideApproval(button) {
    const card = button.closest('[data-approval-card]');
    if (!card || state.decisionInFlight) return;
    const action = button.dataset.approvalAction;
    const kind = button.dataset.approvalKind;
    const requiredToken = button.dataset.requiredToken || '';
    const token = card.querySelector('[data-approval-token]')?.value.trim() || '';
    const errorNode = card.querySelector('[data-approval-error]');
    if (action === 'approve' && requiredToken && token !== requiredToken) {
      errorNode.textContent = 'The confirmation phrase does not match.';
      errorNode.hidden = false;
      return;
    }
    state.decisionInFlight = `${kind}:${button.dataset.approvalId || button.dataset.runtimeJobId}`;
    card.querySelectorAll('button').forEach((candidate) => { candidate.disabled = true; });
    if (errorNode) errorNode.hidden = true;
    try {
      const decisionLabel = action === 'approve' ? 'approved' : 'rejected';
      if (kind === 'command') {
        await postJson(
          `${API}/approvals/${encodeURIComponent(button.dataset.approvalId)}/${action}`,
          { confirm_token: token, reason: `${decisionLabel} from Norman Bridge` },
        );
      } else {
        await postJson(
          `${API}/console-runtime/jobs/${encodeURIComponent(button.dataset.runtimeJobId)}/approval`,
          {
            decision: action,
            reason: `${decisionLabel} from Norman Bridge`,
            confirm_live_execution: action === 'approve' ? token : '',
          },
        );
      }
      playInteractionTone(action === 'approve' ? 'approve' : 'accepted', { signal: true, force: true });
      await loadBootstrap({ quiet: true });
      if (state.selectedJobId) await loadSelectedActivity({ quiet: true });
    } catch (error) {
      playInteractionTone('error', { signal: true });
      if (errorNode) {
        errorNode.textContent = error.message;
        errorNode.hidden = false;
      }
      card.querySelectorAll('button').forEach((candidate) => { candidate.disabled = false; });
    } finally {
      state.decisionInFlight = '';
    }
  }

  function closeDrawers() {
    setWorkspaceMenuOpen(false);
    nodes.nav.classList.remove('is-open');
    nodes.inspector.classList.remove('is-open');
    nodes.backdrop.classList.remove('is-open');
    root.classList.remove('is-nav-open');
  }

  function selectGroup(group) {
    if (!state.groups.some((item) => item.id === group)) return;
    state.group = group;
    state.domain = '';
    state.view = 'general';
    state.selectedConversationId = '';
    state.selectedJobId = '';
    state.selectedAgent = '';
    state.selectedRecipients = [];
    state.activity = null;
    state.workstream = null;
    closeEventStream();
    renderAll();
    setWorkspaceMenuOpen(false);
    closeDrawers();
  }

  function selectDomain(domain) {
    state.domain = state.domain === domain ? '' : domain;
    state.view = 'general';
    state.selectedConversationId = '';
    state.selectedJobId = '';
    state.selectedAgent = '';
    state.activity = null;
    state.workstream = null;
    closeEventStream();
    renderAll();
    closeDrawers();
  }

  function selectJob(jobId) {
    closeEventStream();
    state.lastEventSequence = 0;
    const job = state.jobs.find((item) => item.job_id === jobId);
    if (job) {
      state.group = jobGroup(job);
      state.domain = jobDomain(job);
    }
    state.view = 'job';
    state.selectedJobId = jobId;
    state.selectedAgent = '';
    state.activity = null;
    state.workstream = null;
    renderAll();
    loadSelectedActivity();
    closeDrawers();
  }

  function selectAgent(slug) {
    const agent = state.agents.find((item) => slugify(item.slug) === slugify(slug));
    if (!agent) return;
    openDirectConversation(agent);
  }

  async function openDirectConversation(agent) {
    let conversation = state.conversations.find((item) => (
      item.kind === 'direct'
      && slugify(item.direct_agent_slug) === slugify(agent.slug)
      && slugify(item.principal_slug) === slugify(agent.principal_slug)
    ));
    const payload = {
      kind: 'direct',
      title: agent.display_name,
      principal_slug: agent.principal_slug || currentGroup().slug,
      domain_slug: agent.domain_slug || '',
      direct_agent_slug: agent.slug,
      member_slugs: [agent.slug],
    };

    if (conversation) {
      selectConversation(conversation.conversation_id);
      if (!conversation._local_only) return;
    } else {
      conversation = persistConversationLocally(makeLocalConversation({
        kind: 'direct',
        title: agent.display_name,
        principalSlug: payload.principal_slug,
        domainSlug: payload.domain_slug,
        directAgentSlug: agent.slug,
        memberSlugs: [agent.slug],
      }));
      selectConversation(conversation.conversation_id);
    }

    try {
      const remote = await postJson(`${API}/bridge/conversations`, payload);
      replaceConversation(conversation, remote);
    } catch (error) {
      if (!persistenceUnavailable(error)) {
        nodes.composeHint.textContent = 'This conversation is saved locally; server sync is unavailable.';
      }
    }
  }

  function selectConversation(conversationId) {
    const conversation = state.conversations.find((item) => item.conversation_id === conversationId);
    if (!conversation) return;
    const group = state.groups.find((item) => slugify(item.slug) === slugify(conversation.principal_slug));
    if (group) state.group = group.id;
    state.domain = slugify(conversation.domain_slug);
    state.view = conversation.kind === 'direct' ? 'agent' : 'room';
    state.selectedConversationId = conversation.conversation_id;
    state.selectedAgent = conversation.direct_agent_slug || '';
    state.selectedRecipients = [...(conversation.member_slugs || [])];
    state.selectedJobId = '';
    state.activity = null;
    state.workstream = null;
    closeEventStream();
    renderAll();
    if (conversation.kind === 'direct' && conversation.direct_agent_slug) {
      loadStationHistory(conversation.direct_agent_slug);
    }
    void hydrateConversationActivities(conversation);
    closeDrawers();
    nodes.message.focus();
  }

  function renderRoomMemberPicker() {
    const agents = filteredAgents();
    if (!agents.length) {
      nodes.roomMembers.innerHTML = `
        <div class="bridge-room-members__empty">
          ${iconHtml('alert')}
          <strong>No bots are visible in this workspace</strong>
          <span>Refresh the Bridge or check the estate directory.</span>
        </div>`;
      return;
    }
    nodes.roomMembers.innerHTML = `${groupedAgents(agents).map((group) => `
      <section class="bridge-bot-group" data-bot-group="${escapeHtml(group.key)}"
        style="${escapeHtml(identityStyle(group.agents[0]?.slug || 'norman'))}">
        <header><span>${escapeHtml(group.label)}</span><small data-group-count>${group.agents.length}</small></header>
        <div class="bridge-bot-group__grid">
          ${group.agents.map((agent) => {
            const heartbeat = heartbeatFor(agent);
            const source = heartbeat
              ? 'Available now'
              : agent.directory_source === 'identity-catalog' ? 'Known station' : 'Directory bot';
            const searchText = `${agent.display_name} ${agent.slug} ${source} ${agent.domain_name || ''} ${group.label}`;
            return `<label class="bridge-room-member" data-search="${escapeHtml(searchText.toLowerCase())}"
              style="${escapeHtml(identityStyle(agent.slug))}">
              <input type="checkbox" name="member" value="${escapeHtml(agent.slug)}">
              ${botIdentityTileHtml(agent)}
              <span><strong>${escapeHtml(agent.display_name)}</strong><small>${escapeHtml(source)}${agent.domain_name ? ` · ${escapeHtml(agent.domain_name)}` : ''}</small></span>
              <i>${iconHtml('check')}</i>
            </label>`;
          }).join('')}
        </div>
      </section>
    `).join('')}
      <div class="bridge-room-filter-empty" hidden>
        ${iconHtml('search')}<strong>No matching bots</strong><span>Try a name, role, or workspace.</span>
      </div>`;
  }

  function updateRoomSelectionState() {
    const selected = nodes.roomMembers.querySelectorAll('input[name="member"]:checked').length;
    const visible = [...nodes.roomMembers.querySelectorAll('.bridge-room-member')]
      .filter((member) => !member.hidden).length;
    nodes.roomSelection.textContent = `${selected} selected${nodes.roomSearch.value.trim() ? ` · ${visible} shown` : ''}`;
    nodes.roomCreate.disabled = !nodes.roomName.value.trim() || selected === 0;
  }

  function filterRoomMembers() {
    const query = nodes.roomSearch.value.trim().toLowerCase();
    let visibleTotal = 0;
    nodes.roomMembers.querySelectorAll('.bridge-bot-group').forEach((group) => {
      const members = [...group.querySelectorAll('.bridge-room-member')];
      members.forEach((member) => {
        member.hidden = Boolean(query && !member.dataset.search.includes(query));
      });
      const visible = members.filter((member) => !member.hidden).length;
      visibleTotal += visible;
      group.hidden = visible === 0;
      const count = group.querySelector('[data-group-count]');
      if (count) count.textContent = query && visible !== members.length ? `${visible}/${members.length}` : String(members.length);
    });
    const empty = nodes.roomMembers.querySelector('.bridge-room-filter-empty');
    if (empty) empty.hidden = !query || visibleTotal > 0;
    updateRoomSelectionState();
  }

  function openRoomDialog() {
    nodes.roomName.value = '';
    nodes.roomSearch.value = '';
    nodes.roomError.hidden = true;
    renderRoomMemberPicker();
    filterRoomMembers();
    nodes.roomDialog.showModal();
    window.setTimeout(() => nodes.roomName.focus(), 0);
  }

  async function createRoom(event) {
    event.preventDefault();
    const members = [...nodes.roomForm.querySelectorAll('input[name="member"]:checked')]
      .map((input) => input.value);
    const title = nodes.roomName.value.trim();
    if (!title || !members.length) {
      nodes.roomError.textContent = !title ? 'Give the room a name.' : 'Invite at least one bot.';
      nodes.roomError.hidden = false;
      return;
    }
    const payload = {
      kind: 'room',
      title,
      principal_slug: currentGroup().slug,
      domain_slug: state.domain || '',
      member_slugs: members,
    };
    try {
      const conversation = await postJson(`${API}/bridge/conversations`, payload);
      state.conversations.unshift({ ...conversation, _local_only: false });
      nodes.roomDialog.close();
      selectConversation(conversation.conversation_id);
    } catch (error) {
      if (!persistenceUnavailable(error)) {
        nodes.roomError.textContent = error.message;
        nodes.roomError.hidden = false;
        return;
      }
      const conversation = persistConversationLocally(makeLocalConversation({
        kind: 'room',
        title,
        principalSlug: payload.principal_slug,
        domainSlug: payload.domain_slug,
        memberSlugs: members,
      }));
      nodes.roomDialog.close();
      selectConversation(conversation.conversation_id);
    }
  }

  function setAttentionView(global = false) {
    state.view = global ? 'global-attention' : 'attention';
    state.selectedJobId = '';
    state.selectedAgent = '';
    state.activity = null;
    state.workstream = null;
    closeEventStream();
    renderAll();
    closeDrawers();
  }

  function setMenuOpen(open, panel = state.menuPanel) {
    state.menuPanel = panel || 'overview';
    root.classList.toggle('is-menu-open', open);
    nodes.menu.setAttribute('aria-hidden', String(!open));
    nodes.menuButton.setAttribute('aria-expanded', String(open));
    renderMenuPanel();
  }

  function resizeComposer({ immediate = false } = {}) {
    window.cancelAnimationFrame(state.composerFrame);
    const apply = () => {
      state.composerFrame = 0;
      const previousScrollTop = nodes.message.scrollTop;
      nodes.message.style.height = '0px';
      const height = Math.max(44, Math.min(nodes.message.scrollHeight, 140));
      nodes.message.style.height = `${height}px`;
      nodes.message.style.overflowY = nodes.message.scrollHeight > 140 ? 'auto' : 'hidden';
      nodes.message.scrollTop = previousScrollTop;
    };
    if (immediate) apply();
    else state.composerFrame = window.requestAnimationFrame(apply);
  }

  async function submitMessage(event) {
    event.preventDefault();
    const text = nodes.message.value.trim();
    const conversation = selectedConversation();
    const stationSlug = conversation?.kind === 'direct'
      ? slugify(conversation.direct_agent_slug)
      : '';
    if (!text || promptBusy() || (!stationSlug && state.worker._available === false)) {
      updateComposerState();
      return;
    }
    const group = currentGroup();
    const domain = currentDomain();
    const recipients = [...state.selectedRecipients];
    let created = null;
    setPromptPhase('submitting', {
      jobId: '',
      objective: text,
      error: '',
      startedAt: Date.now(),
    });
    nodes.message.value = '';
    resizeComposer({ immediate: true });
    renderFeed();
    playInteractionTone('send', { signal: true, force: true });
    try {
      if (stationSlug) {
        const currentItems = state.stationHistory[stationSlug]?.items || [];
        const knownTurnIds = new Set(currentItems.map((turn, index) => (
          String(turn.turn_id || `${turn.started_at || ''}:${index}`)
        )));
        const submissionId = `bridge-${Date.now()}-${Math.random().toString(16).slice(2)}`;
        const receipt = await postJson(
          `${API}/bridge/conversations/agents/${encodeURIComponent(stationSlug)}/messages`,
          {
            message: text,
            conversation_id: conversation._local_only ? '' : conversation.conversation_id,
            submission_id: submissionId,
          },
          { timeoutMs: 45000 },
        );
        if (!receipt.accepted) throw new Error(receipt.error || 'Station did not accept the prompt');
        setPromptPhase(receipt.queued ? 'queued' : 'running', {
          jobId: `station:${submissionId}`,
          stationSlug,
        });
        renderFeed();
        void waitForStationResponse(stationSlug, knownTurnIds);
        return;
      }
      created = await postJson(`${API}/console-runtime/jobs`, {
        objective: text,
        execution_mode: 'advisory',
        done_when: ['Return a clear conversational response to the operator.'],
        max_runtime_seconds: 300,
        checkpoint_interval_seconds: 300,
        question_budget: 1,
        durable_workstream: false,
        route_policy: {},
        metadata: {
          source: 'norman_bridge',
          principal: group.slug,
          realm: group.slug,
          domain: domain?.slug || '',
          lane: domain?.slug || '',
          room: state.selectedAgent || domain?.slug || 'general',
          recipients,
          interaction: 'conversation',
          bridge_conversation_id: state.selectedConversationId,
          bridge_conversation_kind: selectedConversation()?.kind || 'home',
          bridge_conversation_title: selectedConversation()?.title || '',
        },
      });
      state.jobs.unshift(created);
      state.lastEventSequence = 0;
      setPromptPhase('queued', { jobId: created.job_id });
      renderFeed();
      connectJobEventStream(created.job_id);
      await postJson(
        `${API}/console-runtime/jobs/${encodeURIComponent(created.job_id)}/runs`,
        {
          worker_id: 'norman-bridge',
          execution_mode: 'advisory',
          dry_run: false,
          complete: true,
          continuous: false,
          durable_workstream: false,
          max_steps: 1,
          max_runtime_seconds: 300,
          local_token_budget: 4096,
          cloud_token_budget: 0,
          goal_phase_sequence: ['chat'],
          planner_kind: 'chat',
          max_output_tokens: 1024,
          route_policy: {},
          metadata: {
            source: 'norman_bridge',
            principal: group.slug,
            domain: domain?.slug || '',
            recipients,
            bridge_conversation_id: state.selectedConversationId,
          },
          include_capabilities: false,
          live_execution_approved: false,
        },
        { timeoutMs: 180000 },
      );
      if (state.prompt.jobId === created.job_id && ['submitting', 'queued'].includes(state.prompt.phase)) {
        setPromptPhase('running');
      }
      await loadBootstrap({ quiet: true });
    } catch (error) {
      if (created?.job_id) {
        try {
          await postJson(`${API}/console-runtime/jobs/${encodeURIComponent(created.job_id)}/cancel`, {
            reason: 'Bridge execution did not start; canceled to prevent a stale queued job.',
          });
        } catch {
          // The draft is still restored; polling will reconcile the job if cancellation also failed.
        }
      }
      nodes.message.value = text;
      resizeComposer({ immediate: true });
      setPromptPhase('failed', {
        jobId: created?.job_id || '',
        error: error.message,
      });
      renderFeed();
    } finally {
      updateComposerState();
    }
  }

  async function cancelSelectedJob() {
    if (!state.selectedJobId) return;
    nodes.cancelJob.disabled = true;
    try {
      await postJson(`${API}/console-runtime/jobs/${encodeURIComponent(state.selectedJobId)}/cancel`, {
        reason: 'Canceled from Norman Bridge',
      });
      await loadBootstrap({ quiet: true });
      await loadSelectedActivity({ quiet: true });
    } catch (error) {
      nodes.composeHint.textContent = `Unable to cancel: ${error.message}`;
    }
  }

  function bindEvents() {
    root.addEventListener('pointermove', (event) => {
      if (event.pointerType === 'touch') return;
      const rect = root.getBoundingClientRect();
      const x = textureClamp((event.clientX - rect.left) / rect.width, 0.03, 0.97);
      const y = textureClamp((event.clientY - rect.top) / rect.height, 0.03, 0.97);
      const now = performance.now();
      const elapsed = Math.max(8, now - (state.texture.pointerAt || now - 16));
      const deltaX = state.texture.pointerAt ? x - state.texture.pointerX : 0;
      const deltaY = state.texture.pointerAt ? y - state.texture.pointerY : 0;
      const distance = Math.hypot(deltaX * rect.width, deltaY * rect.height);
      const speed = distance / elapsed;
      const energy = 0.018 + Math.min(0.075, speed * 0.052);
      const interactive = event.target.closest?.('.bridge-conversation-item, .bridge-room-member');
      const tile = interactive?.querySelector?.('.bridge-simple-cartouche');
      if (tile) {
        const tileRect = tile.getBoundingClientRect();
        exciteCartouche(
          tile,
          0.28 + Math.min(0.58, speed * 0.34),
          ((event.clientX - tileRect.left) / Math.max(1, tileRect.width)) * 100,
          ((event.clientY - tileRect.top) / Math.max(1, tileRect.height)) * 100,
          520,
        );
      }
      addTextureInput(
        x,
        y,
        energy,
        'pointer',
        textureClamp(deltaX * 22, -0.32, 0.32),
        textureClamp(deltaY * 22, -0.32, 0.32),
      );
      state.texture.pointerX = x;
      state.texture.pointerY = y;
      state.texture.pointerAt = now;
    }, { passive: true });
    root.addEventListener('pointerleave', () => {
      state.texture.targetX = 0.58;
      state.texture.targetY = state.prompt.phase === 'running' ? 0.62 : 0.46;
      state.texture.pointerAt = 0;
    }, { passive: true });
    root.addEventListener('keydown', (event) => {
      if (['Shift', 'Control', 'Alt', 'Meta', 'CapsLock'].includes(event.key)) return;
      const rect = root.getBoundingClientRect();
      const editable = event.target.closest?.('input, textarea, [contenteditable="true"]');
      const targetRect = editable?.getBoundingClientRect?.();
      const sequence = state.texture.keySequence += 1;
      const spread = ((sequence * 0.618033988749895) % 1) - 0.5;
      const x = targetRect
        ? textureClamp((targetRect.left + targetRect.width * (0.5 + spread * 0.56) - rect.left) / rect.width, 0.05, 0.95)
        : 0.34 + ((sequence * 0.381966011250105) % 0.32);
      const y = targetRect
        ? textureClamp((targetRect.top + targetRect.height * 0.52 - rect.top) / rect.height, 0.06, 0.94)
        : 0.48;
      addTextureInput(x, y, event.repeat ? 0.046 : 0.088, 'key', spread * 0.024, -0.052);
      exciteCartouche(
        activeIdentityTile(),
        event.repeat ? 0.28 : 0.48,
        50 + spread * 58,
        42 + ((sequence * 0.381966011250105) % 24),
        760,
      );
    });
    root.addEventListener('pointerdown', (event) => {
      const control = event.target.closest('button, a, input, textarea, [tabindex]');
      if (!control || control.disabled) return;
      primeAudio();
      const label = String(control.getAttribute('aria-label') || control.title || control.textContent || '').toLowerCase();
      const kind = /approve|confirm/.test(label)
        ? 'approve'
        : /send|queue/.test(label) ? 'press' : 'click';
      playInteractionTone(kind);
      control.classList.add('is-tactile-pressed');
      window.setTimeout(() => control.classList.remove('is-tactile-pressed'), 140);
    }, { passive: true });
    root.addEventListener('click', (event) => {
      const approvalButton = event.target.closest('[data-approval-action]');
      if (approvalButton) {
        decideApproval(approvalButton);
        return;
      }
      const groupButton = event.target.closest('[data-cockpit-group]');
      if (groupButton) {
        selectGroup(groupButton.dataset.cockpitGroup);
        return;
      }
      const viewButton = event.target.closest('[data-cockpit-view]');
      if (viewButton?.dataset.cockpitView === 'attention') {
        setAttentionView(false);
      } else if (viewButton?.dataset.cockpitView === 'general') {
        state.view = 'general';
        state.selectedConversationId = '';
        state.selectedJobId = '';
        state.selectedAgent = '';
        state.activity = null;
        state.workstream = null;
        closeEventStream();
        renderAll();
        closeDrawers();
      }
      const domainButton = event.target.closest('[data-domain]');
      if (domainButton) selectDomain(domainButton.dataset.domain);
      const jobButton = event.target.closest('[data-job-id]');
      if (jobButton?.dataset.jobId) selectJob(jobButton.dataset.jobId);
      const agentButton = event.target.closest('[data-agent]');
      if (agentButton?.dataset.agent) selectAgent(agentButton.dataset.agent);
      const conversationButton = event.target.closest('[data-conversation-id]');
      if (conversationButton?.dataset.conversationId) selectConversation(conversationButton.dataset.conversationId);
      if (event.target.closest('[data-create-room]')) openRoomDialog();
      const recipientButton = event.target.closest('[data-remove-recipient]');
      if (recipientButton) {
        state.selectedRecipients = state.selectedRecipients.filter((item) => item !== recipientButton.dataset.removeRecipient);
        renderRecipients();
        renderInspector();
      }
      const meter = event.target.closest('[data-menu-panel]');
      if (meter) setMenuOpen(true, meter.dataset.menuPanel);
      const signIn = event.target.closest('[data-sign-in], [data-auth-action="sign-in"]');
      if (signIn) beginSignIn();
      else if (event.target.closest('[data-open-attention]')) setAttentionView(true);
      const resumePrompt = event.target.closest('[data-resume-prompt]');
      if (resumePrompt) draftResumePrompt(resumePrompt.dataset.resumePrompt);
    });
    nodes.workspaceButton.addEventListener('click', (event) => {
      event.stopPropagation();
      setWorkspaceMenuOpen(nodes.workspaceButton.getAttribute('aria-expanded') !== 'true');
    });
    document.addEventListener('click', (event) => {
      if (!event.target.closest('.bridge-workspace-switcher')) setWorkspaceMenuOpen(false);
    });
    el('cockpit-refresh').addEventListener('click', () => loadBootstrap());
    el('cockpit-menu-refresh').addEventListener('click', () => loadBootstrap());
    el('cockpit-new-thread').addEventListener('click', openRoomDialog);
    nodes.roomForm.addEventListener('submit', createRoom);
    nodes.roomName.addEventListener('input', updateRoomSelectionState);
    nodes.roomSearch.addEventListener('input', filterRoomMembers);
    nodes.roomMembers.addEventListener('change', (event) => {
      const input = event.target.closest('input[name="member"]');
      if (!input) return;
      const tile = input.closest('.bridge-room-member')?.querySelector('.bridge-simple-cartouche');
      exciteCartouche(tile, input.checked ? 0.92 : 0.42, 58, 42, 880);
      updateRoomSelectionState();
    });
    nodes.roomDialog.querySelectorAll('[data-close-room-dialog]').forEach((button) => {
      button.addEventListener('click', () => nodes.roomDialog.close());
    });
    el('cockpit-add-recipient').addEventListener('click', () => {
      nodes.nav.classList.add('is-open');
      nodes.backdrop.classList.add('is-open');
      root.classList.add('is-nav-open');
    });
    el('cockpit-nav-open').addEventListener('click', () => {
      nodes.nav.classList.add('is-open');
      nodes.backdrop.classList.add('is-open');
      root.classList.add('is-nav-open');
    });
    el('cockpit-nav-close').addEventListener('click', closeDrawers);
    el('cockpit-inspector-toggle').addEventListener('click', () => {
      nodes.inspector.classList.add('is-open');
      nodes.backdrop.classList.add('is-open');
    });
    el('cockpit-inspector-close').addEventListener('click', closeDrawers);
    nodes.backdrop.addEventListener('click', closeDrawers);
    nodes.menuButton.addEventListener('click', () => setMenuOpen(!root.classList.contains('is-menu-open')));
    nodes.menuBackdrop.addEventListener('click', () => setMenuOpen(false));
    nodes.soundToggle?.addEventListener('click', cycleSoundMode);
    nodes.soundTest?.addEventListener('click', () => playCompletionBell(state.selectedAgent || 'norman'));
    nodes.composer.addEventListener('submit', submitMessage);
    nodes.message.addEventListener('input', () => {
      resizeComposer();
      updateComposerState();
      playInteractionTone('type');
    });
    nodes.message.addEventListener('focus', () => playInteractionTone('focus'));
    nodes.message.addEventListener('keydown', (event) => {
      if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) {
        event.preventDefault();
        nodes.composer.requestSubmit();
      }
    });
    nodes.search.addEventListener('input', () => {
      state.search = nodes.search.value.trim().toLowerCase();
      renderDomains();
      renderWorkstreams();
      renderAgents();
    });
    nodes.openJob.addEventListener('click', () => {
      if (state.selectedJobId) window.open(`${API}/console-runtime/jobs/${encodeURIComponent(state.selectedJobId)}`, '_blank', 'noopener');
    });
    nodes.cancelJob.addEventListener('click', cancelSelectedJob);
    document.addEventListener('keydown', (event) => {
      if (event.key === 'Escape') {
        closeDrawers();
        setMenuOpen(false);
        setWorkspaceMenuOpen(false);
      } else if (event.key === '/' && document.activeElement !== nodes.message) {
        event.preventDefault();
        nodes.message.focus();
      } else if (event.key === 'End') {
        nodes.feed.scrollTop = nodes.feed.scrollHeight;
      }
    });
    document.addEventListener('visibilitychange', () => {
      if (document.visibilityState === 'visible') {
        startTextureField();
        const streamJobId = state.prompt.jobId || state.selectedJobId;
        if (streamJobId && !state.eventSource) connectJobEventStream(streamJobId);
      }
    });
    window.addEventListener('resize', () => {
      state.texture.lines = [];
      if (!state.texture.frame) startTextureField();
      syncVisualViewport();
    });
    window.visualViewport?.addEventListener('resize', syncVisualViewport);
    window.visualViewport?.addEventListener('scroll', syncVisualViewport);
    window.addEventListener('beforeunload', closeEventStream);
  }

  let viewportSyncFrame = 0;

  function syncVisualViewport() {
    window.cancelAnimationFrame(viewportSyncFrame);
    viewportSyncFrame = window.requestAnimationFrame(() => {
      const viewport = window.visualViewport;
      const height = Math.max(320, Math.round(viewport?.height || window.innerHeight));
      document.documentElement.style.setProperty('--bridge-visual-height', `${height}px`);
      if (document.activeElement === nodes.message) {
        nodes.feed.scrollTop = nodes.feed.scrollHeight;
      }
    });
  }

  function startPolling() {
    window.clearTimeout(state.pollTimer);
    const scheduleNextPoll = () => {
      const delayMs = 60000 + Math.floor(Math.random() * 30000);
      state.pollTimer = window.setTimeout(async () => {
        if (document.visibilityState === 'visible') {
          await loadBootstrap({ quiet: true });
          if (state.selectedJobId) await loadSelectedActivity({ quiet: true });
        }
        scheduleNextPoll();
      }, delayMs);
    };
    scheduleNextPoll();
  }

  loadPreferences();
  updateSoundControls();
  syncVisualViewport();
  bindEvents();
  resizeComposer({ immediate: true });
  updateComposerState();
  renderAll();
  loadBootstrap();
  startPolling();
})();
