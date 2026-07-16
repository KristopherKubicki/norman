document.addEventListener('DOMContentLoaded', () => {
  const button = document.getElementById('demo-message-btn');
  const status = document.getElementById('demo-message-status');
  const viewLink = document.getElementById('demo-view-link');
  const homeAgentFleetItems = document.getElementById('home-agent-fleet-items');
  const homeAgentFleetCount = document.getElementById('home-agent-fleet-count');
  const homeMobileFleetItems = document.getElementById('home-mobile-fleet-items');
  const homePrimeActions = document.getElementById('home-prime-actions');
  const homePrimeLanes = document.getElementById('home-prime-lanes');
  const homePrimeSummary = document.getElementById('home-prime-summary');
  const homePrimeFocus = document.getElementById('home-prime-focus');
  const homePrimeDispatch = document.getElementById('home-prime-dispatch');
  const homePrimeDispatchStatus = document.getElementById('home-prime-dispatch-status');
  const homePrimeAgentCount = document.getElementById('home-prime-agent-count');
  const homePrimeOpenCount = document.getElementById('home-prime-open-count');
  const homePrimeCriticalCount = document.getElementById('home-prime-critical-count');
  const homePrimeChatCount = document.getElementById('home-prime-chat-count');
  const homePrimeChats = document.getElementById('home-prime-chats');
  const homePrimeChatsStatus = document.getElementById('home-prime-chats-status');
  const homePrimeAuditSummary = document.getElementById('home-prime-audit-summary');
  const homePrimeAudit = document.getElementById('home-prime-audit');
  const homePrimeAuditStatus = document.getElementById('home-prime-audit-status');
  const homePrimeInbox = document.getElementById('home-prime-inbox');
  const homePrimeInboxCount = document.getElementById('home-prime-inbox-count');
  const homePrimeDesk = document.getElementById('home-prime-desk');
  const homePrimeDeskTitle = document.getElementById('home-prime-desk-title');
  const homePrimeDeskMeta = document.getElementById('home-prime-desk-meta');
  const homePrimeDeskDetail = document.getElementById('home-prime-desk-detail');
  const homePrimeDeskPrompt = document.getElementById('home-prime-desk-prompt');
  const homePrimeDeskActions = document.getElementById('home-prime-desk-actions');
  const homePrimeDeskStatus = document.getElementById('home-prime-desk-status');
  const homePrimeChatThread = document.getElementById('home-prime-chat-thread');
  const homePrimeChatLog = document.getElementById('home-prime-chat-log');
  const homePrimeChatForm = document.getElementById('home-prime-chat-form');
  const homePrimeChatInput = document.getElementById('home-prime-chat-input');
  const homePrimeChatLoad = document.getElementById('home-prime-chat-load');
  const homePrimeChatSend = document.getElementById('home-prime-chat-send');
  const homePrimeChatOpen = document.getElementById('home-prime-chat-open');
  const homePrimeOps = document.getElementById('home-prime-ops');
  const homePrimeOpsSummary = document.getElementById('home-prime-ops-summary');
  const homePrimeOpsFilters = document.getElementById('home-prime-ops-filters');
  const homePrimeOpsModes = document.getElementById('home-prime-ops-modes');
  const homePrimeOpsFocus = document.getElementById('home-prime-ops-focus');
  const homePrimeOpsStatus = document.getElementById('home-prime-ops-status');
  const homePrimeOpsRefresh = document.getElementById('home-prime-ops-refresh');
  const homePrimeOpsUnlockAll = document.getElementById('home-prime-ops-unlock-all');
  const homePrimeOpsKillswitch = document.getElementById('home-prime-ops-killswitch');
  const homePrimeCreditsSummary = document.getElementById('home-prime-credits-summary');
  const homePrimeCreditsItems = document.getElementById('home-prime-credits');
  const homePrimeCreditsStatus = document.getElementById('home-prime-credits-status');
  const homePrimeLlmSummary = document.getElementById('home-prime-llm-summary');
  const homePrimeLlmItems = document.getElementById('home-prime-llm-items');
  const homePrimeLlmStatus = document.getElementById('home-prime-llm-status');
  const homePrimeLlmPing = document.getElementById('home-prime-llm-ping');

  let defaultBot = null;
  let selectedPrimeInboxId = null;
  let selectedPrimeChatSession = null;
  let selectedPrimeOpsLane = 'All';
  let selectedPrimeOpsMode = 'waiting';
  let primeNormanChannelId = null;
  let primeNormanChannelName = 'Console - Subprime';
  let primeNormanSuggestedPrompt = '';
  let primeNormanDraftDirty = false;
  let primeNormanSendInFlight = false;
  const adaptiveTimers = new Map();

  async function fetchJson(url) {
    const response = await fetch(url, {
      cache: 'no-store',
      credentials: 'same-origin',
      headers: { Accept: 'application/json' },
    });
    if (!response.ok) {
      throw new Error(`Request failed: ${response.status}`);
    }
    return response.json();
  }

  async function postJson(url, payload) {
    const response = await fetch(url, {
      method: 'POST',
      cache: 'no-store',
      credentials: 'same-origin',
      headers: {
        Accept: 'application/json',
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(payload || {}),
    });
    if (!response.ok) {
      const detail = await response.text().catch(() => '');
      throw new Error(detail || `Request failed: ${response.status}`);
    }
    return response.json();
  }

  function startAdaptiveLoop(name, task, visibleDelayMs, hiddenDelayMs = visibleDelayMs) {
    const clearExisting = adaptiveTimers.get(name);
    if (clearExisting) {
      clearTimeout(clearExisting);
    }
    const run = async () => {
      try {
        await task();
      } finally {
        const nextDelay = document.hidden ? hiddenDelayMs : visibleDelayMs;
        adaptiveTimers.set(name, window.setTimeout(run, nextDelay));
      }
    };
    adaptiveTimers.set(name, window.setTimeout(run, visibleDelayMs));
  }

  async function loadDefaultBot() {
    try {
      const resp = await fetch('/api/bots/default');
      if (!resp.ok) {
        throw new Error('No default bot');
      }
      defaultBot = await resp.json();
      button.disabled = false;
      status.textContent = `Ready to message "${defaultBot.name}".`;
    } catch (err) {
      status.textContent = 'Create a bot first to enable the demo message.';
    }
  }

  if (button && status) {
    button.addEventListener('click', async () => {
      if (!defaultBot) return;
      button.disabled = true;
      status.textContent = 'Sending demo message...';
      if (viewLink) {
        viewLink.classList.add('d-none');
      }
      try {
        const resp = await fetch(`/api/bots/${defaultBot.id}/messages`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ content: 'Hello! What can you do for me?' })
        });
        if (!resp.ok) {
          throw new Error('Message failed');
        }
        status.textContent = 'Demo message sent. Open the Editor to keep working the thread.';
        if (viewLink) {
          viewLink.href = '/editor.html';
          viewLink.classList.remove('d-none');
        }
      } catch (err) {
        status.textContent = 'Unable to send demo message. Please try again.';
      } finally {
        button.disabled = false;
      }
    });

    loadDefaultBot();
  }

  let lastMessageTimestamp = null;
  const flowMap = document.querySelector('.traffic-map');
  const flowSvg = document.querySelector('.traffic-map svg');
  const flowLayout = document.getElementById('flow-layout');
  const tileChannels = document.getElementById('tile-channels');
  const tileBots = document.getElementById('tile-bots');
  const tileFilters = document.getElementById('tile-filters');
  const tileActions = document.getElementById('tile-actions');
  const lineChannels = document.getElementById('flow-line-channels');
  const lineBots = document.getElementById('flow-line-bots');
  const lineActions = document.getElementById('flow-line-actions');
  const checkChannels = document.getElementById('flow-check-channels');
  const checkBots = document.getElementById('flow-check-bots');
  const checkActions = document.getElementById('flow-check-actions');
  const checkChannelsMark = document.getElementById('flow-check-channels-mark');
  const checkBotsMark = document.getElementById('flow-check-bots-mark');
  const checkActionsMark = document.getElementById('flow-check-actions-mark');
  const dripChannels = document.getElementById('flow-drip-channels');
  const dripBots = document.getElementById('flow-drip-bots');
  const dripActions = document.getElementById('flow-drip-actions');
  const flowLines = Array.from(document.querySelectorAll('.flow-line'));
  const metricInflight = document.getElementById('metric-inflight');
  const metricChannelMsgs = document.getElementById('metric-channel-msgs');
  const metricLastSignal = document.getElementById('metric-last-signal');
  const metricProcessing = document.getElementById('metric-processing');
  const metricBotLatency = document.getElementById('metric-bot-latency');
  const metricBotWait = document.getElementById('metric-bot-wait');
  const metricMatched = document.getElementById('metric-matched');
  const metricRouted = document.getElementById('metric-routed');
  const metricFilterDelay = document.getElementById('metric-filter-delay');
  const metricSent = document.getElementById('metric-sent');
  const metricFailed = document.getElementById('metric-failed');
  const metricLastAction = document.getElementById('metric-last-action');
  const infoToggle = document.getElementById('flow-info-toggle');
  const infoPanel = document.getElementById('flow-info-panel');
  const breatheToggle = document.getElementById('flow-breathe-toggle');
  const rotateToggle = document.getElementById('flow-rotate-toggle');
  const flowControls = {
    messages: document.getElementById('flow-open-messages'),
    channels: document.getElementById('flow-open-channels'),
    filters: document.getElementById('flow-open-filters'),
    bots: document.getElementById('flow-open-bots'),
    actions: document.getElementById('flow-open-actions'),
    connectors: document.getElementById('flow-open-connectors'),
  };
  const attentionRail = document.getElementById('attention-rail');
  const attentionRailCount = document.getElementById('attention-rail-count');
  const attentionRailItems = document.getElementById('attention-rail-items');
  const attentionTimeline = document.getElementById('attention-timeline');
  const attentionTimelineCount = document.getElementById('attention-timeline-count');
  const attentionTimelineItems = document.getElementById('attention-timeline-items');
  const attentionToggleHiddenBtn = document.getElementById('attention-toggle-hidden');
  const attentionClearAckedBtn = document.getElementById('attention-clear-acked');
  const ATTENTION_STATE_KEY = 'norman.attention.state.v1';
  let showSuppressedIncidents = false;

  const flowLinks = Array.from(document.querySelectorAll('.flow-link'));
  const assistantChips = Array.from(document.querySelectorAll('.flow-chip'));

  function updateFlowViewportSizing() {
    const card = document.querySelector('.home-flow.card.full-map');
    const map = document.querySelector('.traffic-map.main-map');
    const main = document.querySelector('main.home-shell');
    if (!card || !map) return;
    const compactPhoneMode = window.matchMedia('(max-width: 520px)').matches;
    if (compactPhoneMode) {
      if (main) {
        main.style.removeProperty('height');
      }
      card.style.removeProperty('--flow-card-height');
      map.style.removeProperty('--flow-map-height');
      return;
    }

    const statusBar = document.getElementById('global-status-bar');
    const statusH = statusBar ? statusBar.getBoundingClientRect().height : 0;
    const viewportH = window.visualViewport ? window.visualViewport.height : window.innerHeight;

    if (main) {
      const mainTop = main.getBoundingClientRect().top;
      const mainH = Math.max(320, viewportH - mainTop - statusH - 8);
      main.style.height = `${Math.floor(mainH)}px`;
    }

    const cardTop = card.getBoundingClientRect().top;
    const cardH = Math.max(420, viewportH - cardTop - statusH - 10);
    card.style.setProperty('--flow-card-height', `${Math.floor(cardH)}px`);

    const mapTop = map.getBoundingClientRect().top;
    const mapH = Math.max(320, viewportH - mapTop - statusH - 10);
    map.style.setProperty('--flow-map-height', `${Math.floor(mapH)}px`);
  }

  function clamp(value, min, max) {
    return Math.min(max, Math.max(min, value));
  }

  function lerp(a, b, t) {
    return a + (b - a) * t;
  }

  function cameraPadForAspect(aspect) {
    return aspect < 0.75 ? 14 : 16;
  }

  function tileBox(baseLeft, baseTop, width, height, tx, ty) {
    const l = baseLeft + tx;
    const t = baseTop + ty;
    const r = l + width;
    const b = t + height;
    return {
      l,
      t,
      r,
      b,
      w: width,
      h: height,
      cx: l + width / 2,
      cy: t + height / 2,
    };
  }

  function setTranslate(el, tx, ty) {
    if (!el) return;
    el.setAttribute('transform', `translate(${tx.toFixed(2)} ${ty.toFixed(2)})`);
  }

  function setCheck(el, markEl, cx, cy) {
    if (el) {
      el.setAttribute('cx', cx.toFixed(2));
      el.setAttribute('cy', cy.toFixed(2));
    }
    if (markEl) {
      markEl.setAttribute(
        'd',
        `M${(cx - 5).toFixed(2)} ${(cy).toFixed(2)} L${(cx - 1).toFixed(2)} ${(cy + 4).toFixed(2)} L${(cx + 6).toFixed(2)} ${(cy - 6).toFixed(2)}`
      );
    }
  }

  function setDrip(el, cx, cy) {
    if (!el) return;
    el.setAttribute('cx', cx.toFixed(2));
    el.setAttribute('cy', cy.toFixed(2));
  }

  function pushBox(points, box) {
    points.push(box.l, box.t);
    points.push(box.r, box.t);
    points.push(box.r, box.b);
    points.push(box.l, box.b);
  }

  function boundsFromPoints(points) {
    let minX = Number.POSITIVE_INFINITY;
    let maxX = Number.NEGATIVE_INFINITY;
    let minY = Number.POSITIVE_INFINITY;
    let maxY = Number.NEGATIVE_INFINITY;
    for (let i = 0; i < points.length; i += 2) {
      const x = points[i];
      const y = points[i + 1];
      if (!Number.isFinite(x) || !Number.isFinite(y)) continue;
      minX = Math.min(minX, x);
      maxX = Math.max(maxX, x);
      minY = Math.min(minY, y);
      maxY = Math.max(maxY, y);
    }
    if (!Number.isFinite(minX) || !Number.isFinite(minY)) return null;
    return { minX, minY, maxX, maxY };
  }

  function driftSafeNumber(value) {
    return Number.isFinite(value) ? value : 0;
  }

  function escapeHtml(value) {
    return String(value || '')
      .replaceAll('&', '&amp;')
      .replaceAll('<', '&lt;')
      .replaceAll('>', '&gt;')
      .replaceAll('"', '&quot;')
      .replaceAll("'", '&#39;');
  }

  const FLEET_PRIORITY = {
    'norman-service': 0,
    'norman-home': 1,
    'finance-reader': 1,
    'health-reader': 2,
    parkergale: 3,
    'private-home': 4,
    'toy-box-home': 5,
    artmonster: 6,
    'diamond-roc': 6,
    housebot: 6,
    glimpser: 7,
    dj: 8,
    tv: 9,
    studio: 10,
    castle: 11,
    'phone-ops': 12,
    uscache: 13,
    theseus: 14,
    'work-special-home': 12,
    earlybird: 13,
    infra: 14,
    'control-plane': 15,
    'market-sizing': 16,
    'tmi-dashboards': 17,
    'gold-book': 18,
    'platinum-standard': 19,
    compere: 20,
    'leadership-kpis': 21,
    panelbot: 22,
    scout: 22,
    'networking-home': 30,
    networking: 31,
    netops: 31,
    uplink: 32,
    cloudagent: 33,
    'dohio-topology': 34,
    'switchyard-network-board': 35,
  };

  const LANE_ORDER = ['Norman', 'Private', 'Personal', 'Work', 'Shared'];
  const PRIVATE_SERVICE_SLUGS = new Set(['finance-reader', 'health-reader', 'parkergale', 'private-home']);
  const PERSONAL_SERVICE_SLUGS = new Set(['toy-box-home', 'artmonster', 'diamond-roc', 'housebot', 'glimpser', 'dj', 'tv', 'studio', 'castle', 'phone-ops', 'uscache', 'autocamera', 'theseus']);
  const WORK_SERVICE_SLUGS = new Set(['work-special-home', 'earlybird', 'infra', 'control-plane', 'market-sizing', 'tmi-dashboards', 'gold-book', 'platinum-standard', 'publisher', 'compere', 'leadership-kpis', 'panelbot', 'scout', 'd-ace']);
  const SHARED_SERVICE_SLUGS = new Set(['networking-home', 'networking', 'netops', 'uplink', 'cloudagent', 'dohio-topology', 'switchyard-network-board']);
  const BOT_PROXY_ALIASES = {
    autocamera: 'auto',
    compere: 'keystone',
    'control-plane': 'cp',
    dj: 'yt',
    'gold-book': 'goldbook',
    housebot: 'house',
    'leadership-kpis': 'leadership',
    'market-sizing': 'market',
    parkergale: 'pefb',
    'phone-ops': 'phone',
    'platinum-standard': 'platinum',
    scout: 'scoutbot',
    studio: 'camera-studio',
    'tmi-dashboards': 'tmi',
  };
  const BOT_HOST_SHORTCUTS = {
    autocamera: 'autocamera.home.arpa',
    castle: 'castle.home.arpa',
    cloudagent: 'cloudagent.home.arpa',
    compere: 'keystone.kris.openbrand.com',
    'control-plane': 'cp.kris.openbrand.com',
    dj: 'dj.home.arpa',
    'dohio-topology': 'dohio.home.arpa',
    earlybird: 'earlybird.kris.openbrand.com',
    glimpser: 'eyebat.home.arpa',
    'gold-book': 'goldbook.kris.openbrand.com',
    housebot: 'housebot.home.arpa',
    infra: 'infra.kris.openbrand.com',
    'leadership-kpis': 'kpis.kris.openbrand.com',
    'market-sizing': 'market.kris.openbrand.com',
    mls: 'mls.kris.openbrand.com',
    networking: 'networking.home.arpa',
    panelbot: 'panelbot.kris.openbrand.com',
    parkergale: 'pefb.home.arpa',
    'phone-ops': 'phone.home.arpa',
    'platinum-standard': 'platinum.kris.openbrand.com',
    publisher: 'publisher.kris.openbrand.com',
    scout: 'scout.kris.openbrand.com',
    studio: 'studio.home.arpa',
    'switchyard-network-board': 'dohio.home.arpa/admin',
    theseus: 'theseus.home.arpa',
    'tmi-dashboards': 'dashboards.kris.openbrand.com',
    tv: 'tv.home.arpa',
    uplink: 'uplink.home.arpa',
    usbhome: 'usbhome.home.arpa',
    uscache: 'uscache.home.arpa',
  };
  const FLEET_MARK_ALIASES = {
    norman: 'N',
    artmonster: 'AM',
    autocamera: 'AC',
    castle: 'CS',
    cloudagent: 'CA',
    compere: 'CP',
    'control plane': 'CP',
    dj: 'DJ',
    'diamond roc': 'DR',
    'diamond-roc': 'DR',
    dohio: 'DO',
    'dohio topology': 'DO',
    earlybird: 'EB',
    glimpser: 'GL',
    'gold book': 'GB',
    housebot: 'HB',
    infra: 'IF',
    keystone: 'KS',
    'leadership kpis': 'LK',
    'market sizing': 'MS',
    mls: 'ML',
    networking: 'NW',
    panelbot: 'PB',
    parkergale: 'PE',
    pefb: 'PE',
    'phone ops': 'PH',
    'platinum standard': 'PL',
    publisher: 'PU',
    scout: 'SC',
    shared: 'SH',
    personal: 'PS',
    private: 'PV',
    subprime: 'SP',
    studio: 'ST',
    switchboard: 'SW',
    'switchyard network board': 'SY',
    theseus: 'TH',
    'tmi dashboards': 'TD',
    tv: 'TV',
    uplink: 'UP',
    usbhome: 'UH',
    uscache: 'US',
    work: 'WK',
  };

  function normalizeFleetMarkKey(value) {
    return String(value || '').trim().toLowerCase().replace(/[^a-z0-9]+/g, ' ').trim();
  }

  function fleetMarkForLabel(label, fallback = '•') {
    const clean = normalizeFleetMarkKey(label);
    if (!clean) return fallback;
    if (Object.prototype.hasOwnProperty.call(FLEET_MARK_ALIASES, clean)) {
      return FLEET_MARK_ALIASES[clean];
    }
    const aliasEntry = Object.entries(FLEET_MARK_ALIASES).find(([key]) => clean.includes(key));
    if (aliasEntry) return aliasEntry[1];
    const tokens = String(label || '').match(/[A-Za-z0-9]+/g) || [];
    if (!tokens.length) return fallback;
    if (tokens.length === 1) return tokens[0].replace(/[^A-Za-z0-9]+/g, '').slice(0, 2).toUpperCase() || fallback;
    return `${tokens[0][0]}${tokens[1][0]}`.toUpperCase();
  }

  function fleetMarkForService(service) {
    const candidates = [
      service?.display_name,
      service?.bot_name,
      service?.slug,
      service?.worker_name,
      service?.domain_name,
    ].filter(Boolean);
    for (const candidate of candidates) {
      const mark = fleetMarkForLabel(candidate, '');
      if (mark) return mark;
    }
    return fleetMarkForLabel(service?.display_name || service?.slug || service?.bot_name, '•');
  }

  function laneNameForService(service, principal = null) {
    const slug = String(service?.slug || '').trim().toLowerCase();
    const routeText = [
      service?.web_url,
      service?.web_url_tailnet,
      service?.console_url,
      service?.console_url_tailnet,
      service?.worker_name,
      service?.domain_name,
      service?.bot_name,
      service?.display_name,
      service?.policy_mode,
      service?.policy_profile_name,
      principal?.display_name,
      principal?.slug,
    ].join(' ').toLowerCase();
    if (slug === 'norman-service') return 'Norman';
    if (
      PRIVATE_SERVICE_SLUGS.has(slug)
      || routeText.includes('finance')
      || routeText.includes('health')
      || routeText.includes('parkergale')
      || routeText.includes('pef')
      || routeText.includes('private')
    ) return 'Private';
    if (PERSONAL_SERVICE_SLUGS.has(slug) || routeText.includes('toy-box') || routeText.includes('192.168.2.146')) return 'Personal';
    if (WORK_SERVICE_SLUGS.has(slug) || routeText.includes('work-special') || routeText.includes('192.168.2.147')) return 'Work';
    if (SHARED_SERVICE_SLUGS.has(slug) || routeText.includes('networking.tail94915.ts.net') || routeText.includes('192.168.2.242')) return 'Shared';
    if (String(principal?.slug || '').trim().toLowerCase() === 'openbrand') return 'Work';
    return 'Shared';
  }

  function fleetServiceRank(service) {
    const slug = String(service?.slug || '');
    return Object.prototype.hasOwnProperty.call(FLEET_PRIORITY, slug) ? FLEET_PRIORITY[slug] : 20;
  }

  function fleetGroupsFromPayload(payload) {
    const laneMap = new Map(LANE_ORDER.map((lane) => [lane, {
      slug: lane.toLowerCase(),
      display_name: lane,
      services: [],
      counts: { services: 0 },
    }]));

    (payload?.principals || []).forEach((principal) => {
      (principal.services || []).forEach((service) => {
        if (!hasFleetLinks(service)) return;
        const lane = laneNameForService(service, principal);
        const group = laneMap.get(lane) || laneMap.get('Shared');
        group.services.push({
          ...service,
          principal_name: principal.display_name,
          principal_slug: principal.slug,
        });
      });
    });

    return LANE_ORDER
      .map((lane) => {
        const group = laneMap.get(lane);
        group.services = group.services.sort((a, b) => {
          const aRank = fleetServiceRank(a);
          const bRank = fleetServiceRank(b);
          if (aRank !== bRank) return aRank - bRank;
          return String(a.display_name || a.slug).localeCompare(String(b.display_name || b.slug));
        });
        group.counts.services = group.services.length;
        return group;
      })
      .filter((group) => group.services.length > 0);
  }

  function fleetFlattenedServices(groups) {
    return groups.flatMap((principal) => (
      principal.services.map((service) => ({ ...service, principal_name: principal.display_name }))
    ));
  }

  const PRINCIPAL_DESCRIPTIONS = {
    Norman: 'Front door, estate directory, and orchestration surface.',
    Private: 'Finance, health, and confidential advisors summarized by default and entered deliberately.',
    Personal: 'Toy Box agents, home systems, and personal operators.',
    Work: 'Work-special bots, active projects, and operator-heavy sessions.',
    Shared: 'Networking, cloud, uplink, DOHIO topology, and shared infrastructure control.',
  };

  function principalTone(principal) {
    const name = String(principal?.display_name || '').trim().toLowerCase();
    if (name === 'norman') return 'norman';
    if (name === 'private') return 'private';
    if (name === 'personal') return 'personal';
    if (name === 'work') return 'work';
    return 'shared';
  }

  function isTailnetHostLike(value) {
    const text = String(value || '').trim().toLowerCase();
    if (!text) return false;
    if (text.includes('.ts.net') || text.includes('tailscale')) return true;
    return /\b100\.(6[4-9]|[78]\d|9\d|1[01]\d|12[0-7])\.\d{1,3}\.\d{1,3}\b/.test(text);
  }

  function isLanHostLike(value) {
    const text = String(value || '').trim().toLowerCase();
    if (!text) return false;
    if (text.includes('127.0.0.1') || text.includes('localhost')) return true;
    if (text.includes('.local') || text.endsWith('.lan') || text.endsWith('.arpa')) return true;
    if (/\b10\.\d{1,3}\.\d{1,3}\.\d{1,3}\b/.test(text)) return true;
    if (/\b192\.168\.\d{1,3}\.\d{1,3}\b/.test(text)) return true;
    if (/\b172\.(1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3}\b/.test(text)) return true;
    return false;
  }

  function currentFleetRoutePreference() {
    const host = String(window.location.hostname || '').trim().toLowerCase();
    if (isTailnetHostLike(host)) return 'tailnet';
    return 'lan';
  }

  function resolvePreferredFleetRoute(primaryUrl, tailnetUrl) {
    const primary = String(primaryUrl || '').trim();
    const tailnet = String(tailnetUrl || '').trim();
    const preferTailnet = currentFleetRoutePreference() === 'tailnet';
    if (preferTailnet) {
      if (tailnet) {
        return { primary: tailnet, alternate: primary, mode: 'tailnet' };
      }
      if (primary) {
        return { primary, alternate: '', mode: 'lan' };
      }
      return { primary: '', alternate: '', mode: 'tailnet' };
    }
    if (primary) {
      return { primary, alternate: tailnet, mode: 'lan' };
    }
    if (tailnet) {
      return { primary: tailnet, alternate: '', mode: 'tailnet' };
    }
    return { primary: '', alternate: '', mode: 'lan' };
  }

  function routeModeLabel(prefix, mode, hasAlternate = false) {
    if (!mode) return prefix;
    if (!hasAlternate) {
      if (mode === 'tailnet') return `${prefix} Tailnet`;
      return prefix;
    }
    if (mode === 'tailnet') return `${prefix} Tailnet`;
    return prefix;
  }

  function alternateRouteLabel(prefix, mode) {
    if (mode === 'tailnet') return `${prefix} LAN`;
    return `${prefix} Tailnet`;
  }

  function primaryServiceLink(service, kind = 'console') {
    if (!service) return '';
    if (kind === 'web') {
      return resolvePreferredFleetRoute(service.web_url, service.web_url_tailnet).primary;
    }
    return resolvePreferredFleetRoute(service.console_url, service.console_url_tailnet).primary;
  }

  function proxySlugForService(service) {
    const slug = String(service?.slug || '').trim().toLowerCase();
    if (!slug || slug.endsWith('-home')) return '';
    if ([service?.console_url, service?.console_url_tailnet].every((value) => !String(value || '').trim())) return '';
    return BOT_PROXY_ALIASES[slug] || slug;
  }

  function proxyPathForService(service) {
    const slug = proxySlugForService(service);
    return slug ? `/bot/${slug}/` : '';
  }

  function proxyDisplayForService(service) {
    const vanityHost = BOT_HOST_SHORTCUTS[String(service?.slug || '').trim().toLowerCase()];
    if (vanityHost) return `${vanityHost}/`;
    const slug = proxySlugForService(service);
    return slug ? `norman.home.arpa/bot/${slug}/` : '';
  }

  function findNormanLead(groups) {
    const candidates = fleetFlattenedServices(groups);
    return candidates.find((service) => String(service.slug || '') === 'norman-service')
      || candidates.find((service) => /norman/i.test(String(service.display_name || service.slug || '')))
      || null;
  }

  function buildEditorDraftLink({ thread = 'console - Norman', draft = '', focus = true } = {}) {
    const params = new URLSearchParams();
    params.set('pane', 'conversation');
    params.set('thread', thread);
    params.set('source', 'home-prime');
    if (draft) params.set('draft', draft);
    if (focus) params.set('focus', '1');
    return `/editor.html?${params.toString()}`;
  }

  function normalizePrimeKey(value) {
    return String(value || '')
      .trim()
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, ' ')
      .replace(/\s+/g, ' ')
      .trim();
  }

  function primeNormanThreadHref(draft = '') {
    return buildEditorDraftLink({
      thread: primeNormanChannelName || 'Console - Subprime',
      draft,
      focus: true,
    });
  }

  function findPrimeNormanChannel(channels) {
    if (!Array.isArray(channels)) return null;
    return channels.find((channel) => /^console\s*[-:]\s*subprime$/i.test(String(channel.name || '').trim()))
      || channels.find((channel) => normalizePrimeKey(channel?.name) === 'console subprime')
      || channels.find((channel) => normalizePrimeKey(channel?.name).includes('subprime'))
      || channels.find((channel) => /^console\s*[-:]\s*norman$/i.test(String(channel.name || '').trim()))
      || channels.find((channel) => normalizePrimeKey(channel?.name) === 'console norman')
      || channels.find((channel) => normalizePrimeKey(channel?.name).includes('norman'))
      || null;
  }

  function primeNormanMessagePreview(content) {
    const text = String(content || '').replace(/\r\n/g, '\n').replace(/\r/g, '\n').trim();
    if (!text) return '';
    const compact = text.replace(/\n{3,}/g, '\n\n');
    return compact.length > 420 ? `${compact.slice(0, 417).trimEnd()}…` : compact;
  }

  function renderPrimeNormanMessageHtml(message) {
    const tone = String(message?.source || '').toLowerCase() === 'user' ? 'user' : 'assistant';
    const label = tone === 'user' ? 'You' : 'Norman';
    const createdAt = message?.created_at ? parseTimestampMs(message.created_at) : null;
    const stamp = createdAt ? formatPrimeInboxAge(createdAt) : 'Now';
    const preview = primeNormanMessagePreview(message?.content);
    return `
      <article class="prime-desk__chat-message prime-desk__chat-message--${escapeHtml(tone)}">
        <div class="prime-desk__chat-message-meta">
          <span class="prime-desk__chat-message-source">${escapeHtml(label)}</span>
          <span class="prime-desk__chat-message-time">${escapeHtml(stamp)}</span>
        </div>
        <div class="prime-desk__chat-message-body">${escapeHtml(preview).replace(/\n/g, '<br>')}</div>
      </article>
    `;
  }

  function syncPrimeNormanComposerState() {
    if (!homePrimeChatInput || !homePrimeChatSend || !homePrimeChatLoad) return;
    const hasDraft = Boolean(String(homePrimeChatInput.value || '').trim());
    homePrimeChatSend.disabled = primeNormanSendInFlight || !hasDraft || !primeNormanChannelId;
    homePrimeChatLoad.disabled = primeNormanSendInFlight || !String(primeNormanSuggestedPrompt || '').trim();
    if (homePrimeChatOpen) {
      homePrimeChatOpen.href = primeNormanThreadHref(hasDraft ? String(homePrimeChatInput.value || '').trim() : '');
    }
  }

  function seedPrimeNormanDraft(prompt, { force = false, announce = false } = {}) {
    if (!homePrimeChatInput) return;
    const next = String(prompt || '').trim();
    primeNormanSuggestedPrompt = next;
    if (!next) {
      syncPrimeNormanComposerState();
      return;
    }
    const current = String(homePrimeChatInput.value || '').trim();
    if (!force && primeNormanDraftDirty && current && current !== next) {
      syncPrimeNormanComposerState();
      return;
    }
    homePrimeChatInput.value = next;
    primeNormanDraftDirty = false;
    syncPrimeNormanComposerState();
    if (announce && homePrimeDeskStatus) {
      homePrimeDeskStatus.textContent = 'Brief loaded into Norman chat';
    }
  }

  async function loadPrimeNormanChat({ silent = false } = {}) {
    if (!homePrimeChatLog || !homePrimeChatThread) return;
    if (document.hidden && silent) return;
    try {
      const channels = await fetchJson('/api/v1/channels');
      const normanChannel = findPrimeNormanChannel(channels);
      if (!normanChannel) {
        primeNormanChannelId = null;
        primeNormanChannelName = 'Console - Subprime';
        homePrimeChatThread.textContent = 'Subprime lane unavailable';
        homePrimeChatLog.innerHTML = '<div class="home-prime__placeholder">Prime cannot find the Subprime coordination lane right now.</div>';
        syncPrimeNormanComposerState();
        return;
      }
      primeNormanChannelId = Number(normanChannel.id);
      primeNormanChannelName = String(normanChannel.name || 'Console - Subprime').trim() || 'Console - Subprime';
      homePrimeChatThread.textContent = `${primeNormanChannelName} · coordination lane`;
      if (homePrimeChatOpen) {
        homePrimeChatOpen.href = primeNormanThreadHref(String(homePrimeChatInput?.value || '').trim());
      }
      const messages = await fetchJson(`/api/v1/channels/${primeNormanChannelId}/messages`);
      const recent = Array.isArray(messages) ? messages.slice(-6) : [];
      homePrimeChatLog.innerHTML = recent.length
        ? recent.map((message) => renderPrimeNormanMessageHtml(message)).join('')
        : '<div class="home-prime__placeholder">No Norman thread messages yet. Use the brief below to start the thread from Prime.</div>';
      homePrimeChatLog.scrollTop = homePrimeChatLog.scrollHeight;
      syncPrimeNormanComposerState();
    } catch (err) {
      if (!silent) {
        primeNormanChannelId = null;
        homePrimeChatThread.textContent = 'Subprime lane unavailable';
        homePrimeChatLog.innerHTML = '<div class="home-prime__placeholder">Unable to load the Subprime coordination lane right now.</div>';
        syncPrimeNormanComposerState();
      }
    }
  }

  async function sendPrimeNormanMessage(content) {
    const text = String(content || '').trim();
    if (!text) return;
    if (!primeNormanChannelId) {
      await loadPrimeNormanChat();
      if (!primeNormanChannelId) {
        throw new Error('Subprime is unavailable right now.');
      }
    }
    primeNormanSendInFlight = true;
    syncPrimeNormanComposerState();
    if (homePrimeDeskStatus) {
        homePrimeDeskStatus.textContent = 'Sending to Subprime…';
    }
    try {
      await postJson(`/api/v1/channels/${primeNormanChannelId}/messages`, { content: text });
      if (homePrimeChatInput) {
        homePrimeChatInput.value = '';
      }
      primeNormanDraftDirty = false;
      if (homePrimeDeskStatus) {
        homePrimeDeskStatus.textContent = 'Sent to Subprime';
      }
      await loadPrimeNormanChat();
    } finally {
      primeNormanSendInFlight = false;
      syncPrimeNormanComposerState();
    }
  }

  function renderPrimeActionButtons(groups) {
    if (!homePrimeActions) return;
    const normanLead = findNormanLead(groups);
    const normanChat = primaryServiceLink(normanLead, 'console');
    const actions = [];

    actions.push('<button class="btn btn-primary btn-sm" type="button" data-prime-jump-compose="1">Norman chat</button>');
    actions.push(`<a class="btn btn-outline-secondary btn-sm" href="${escapeHtml(primeNormanThreadHref())}">Editor</a>`);
    if (normanChat) {
      actions.push(`<a class="btn btn-outline-secondary btn-sm" href="${escapeHtml(normanChat)}" target="_blank" rel="noreferrer">Console</a>`);
    }
    actions.push('<a class="btn btn-outline-secondary btn-sm" href="/systems.html#agent-directory">Directory</a>');

    homePrimeActions.innerHTML = actions.join('');
  }

  function renderPrimeLaneCard(principal) {
    const tone = principalTone(principal);
    const lead = principal.services.find((service) => primaryServiceLink(service, 'console') || primaryServiceLink(service, 'web'))
      || principal.services[0];
    const chatUrl = primaryServiceLink(lead, 'console');
    const appUrl = primaryServiceLink(lead, 'web');
    const leadName = lead ? (lead.display_name || lead.slug) : 'No lead assigned';
    const routeState = principal.services.filter((service) => primaryServiceLink(service, 'console')).length;

    return `
      <article class="prime-lane prime-lane--${escapeHtml(tone)}">
        <div class="prime-lane__header">
          <div>
            <div class="prime-lane__title">${escapeHtml(principal.display_name)}</div>
            <div class="prime-lane__copy">${escapeHtml(PRINCIPAL_DESCRIPTIONS[principal.display_name] || 'Published bots and operator routes for this lane.')}</div>
          </div>
          <span class="status-chip ok">${principal.services.length} live</span>
        </div>
        <div class="prime-lane__lead">Lead: <strong>${escapeHtml(leadName)}</strong></div>
        <div class="prime-lane__meta">${routeState} chat route${routeState === 1 ? '' : 's'} ready</div>
        <div class="prime-lane__actions">
          ${chatUrl ? `<a class="btn btn-primary btn-sm" href="${escapeHtml(chatUrl)}" target="_blank" rel="noreferrer">Console</a>` : ''}
          ${appUrl ? `<a class="btn btn-outline-secondary btn-sm" href="${escapeHtml(appUrl)}" target="_blank" rel="noreferrer">App</a>` : ''}
          <a class="btn btn-outline-secondary btn-sm" href="/systems.html#agent-directory">Directory</a>
        </div>
      </article>
    `;
  }

  function dispatchPromptForPrincipal(principal) {
    const lane = String(principal.display_name || 'Shared').trim();
    const leadNames = principal.services.slice(0, 2)
      .map((service) => service.display_name || service.slug)
      .filter(Boolean);
    const targets = leadNames.length ? leadNames.join(' and ') : `${lane} bots`;
    return `Norman, coordinate with ${targets} on the ${lane} lane. Summarize what matters, what changed, and what I should do next.`;
  }

  function renderDispatchCards(groups) {
    if (!homePrimeDispatch) return;
    const normanLead = findNormanLead(groups);
    const normanChat = primaryServiceLink(normanLead, 'console');
    const recipes = groups.slice(0, 4).map((principal) => ({
      title: `${principal.display_name} lane brief`,
      copy: PRINCIPAL_DESCRIPTIONS[principal.display_name] || 'Coordinate this lane and summarize the current state.',
      prompt: dispatchPromptForPrincipal(principal),
      tone: principalTone(principal),
    }));

    if (!recipes.length) {
      homePrimeDispatch.innerHTML = '<div class="home-prime__placeholder">No published lane recipes yet.</div>';
      if (homePrimeDispatchStatus) {
        homePrimeDispatchStatus.textContent = 'No recipes';
      }
      return;
    }

    homePrimeDispatch.innerHTML = recipes.map((recipe) => `
      <article class="dispatch-card dispatch-card--${escapeHtml(recipe.tone)}">
        <div class="dispatch-card__header">
          <div>
            <div class="dispatch-card__title">${escapeHtml(recipe.title)}</div>
            <div class="dispatch-card__copy">${escapeHtml(recipe.copy)}</div>
          </div>
        </div>
        <div class="dispatch-card__prompt">${escapeHtml(recipe.prompt)}</div>
        <div class="dispatch-card__actions">
          <button type="button" class="btn btn-primary btn-sm" data-prime-compose-draft="${escapeHtml(recipe.prompt)}">Use here</button>
          <a class="btn btn-outline-secondary btn-sm" href="${escapeHtml(primeNormanThreadHref(recipe.prompt))}">Editor</a>
          <button type="button" class="btn btn-outline-secondary btn-sm dispatch-copy-btn" data-dispatch-prompt="${escapeHtml(recipe.prompt)}">Copy brief</button>
          ${normanChat ? `<a class="btn btn-outline-secondary btn-sm" href="${escapeHtml(normanChat)}" target="_blank" rel="noreferrer">Console</a>` : ''}
        </div>
      </article>
    `).join('');

    if (homePrimeDispatchStatus) {
      homePrimeDispatchStatus.textContent = `${recipes.length} recipes ready`;
    }
  }

  function renderPrimeSummary(items, groups) {
    if (!homePrimeSummary) return;
    const activeItems = items || [];
    const opsPayload = window.__normanOpsPayload || null;
    const dangerCount = activeItems.filter((item) => String(item.level || '').toLowerCase() === 'danger').length;
    const warnCount = activeItems.filter((item) => String(item.level || '').toLowerCase() === 'warn').length;
    const setupCount = activeItems.filter((item) => String(item.id || '').startsWith('connector-missing:')).length;
    const routingCount = activeItems.filter((item) => String(item.id || '').startsWith('routing-')).length;
    const topItem = activeItems[0] || null;
    const topLane = topItem ? inferInboxLane(topItem) : null;
    const laneLead = topLane ? recommendedLaneLead(groups, topLane) : null;
    const leadName = laneLead ? (laneLead.display_name || laneLead.slug) : 'Norman';
    const summaryCards = [
      {
        label: 'Top focus',
        value: topItem ? topItem.title : 'Inbox is quiet',
        copy: topItem ? topItem.detail : 'No urgent items are active.',
        tone: topItem ? String(topItem.level || 'idle').toLowerCase() : 'ok',
      },
      {
        label: 'Setup',
        value: setupCount ? `${setupCount} connector gap${setupCount === 1 ? '' : 's'}` : 'Setup clean',
        copy: setupCount ? 'Connector setup still needs work.' : 'Required connector fields are in place.',
        tone: setupCount ? 'warn' : 'ok',
      },
      {
        label: 'Routing',
        value: routingCount ? `${routingCount} routing issue${routingCount === 1 ? '' : 's'}` : 'Routing clear',
        copy: routingCount ? 'Failed routes need attention.' : 'No active routing backlog.',
        tone: routingCount ? 'danger' : 'ok',
      },
      {
        label: 'Workers',
        value: opsPayload
          ? opsPayload.needs_turn
            ? `${opsPayload.needs_turn} need another turn`
            : opsPayload.working
              ? `${opsPayload.working} working`
              : 'Quiet'
          : leadName,
        copy: opsPayload
          ? opsPayload.needs_turn
            ? 'Workers are waiting for the next prompt.'
            : opsPayload.working
              ? 'Workers are still running.'
              : 'Worker state is steady.'
          : topLane
            ? `${topLane} lane is the best place to start.`
            : 'Norman is ready for the next brief.',
        tone: opsPayload
          ? opsPayload.needs_turn
            ? 'warn'
            : opsPayload.locked
              ? 'danger'
              : 'ok'
          : topLane ? principalTone({ display_name: topLane }) : 'norman',
      },
    ];

    homePrimeSummary.innerHTML = summaryCards.map((card) => `
      <article class="prime-summary-card prime-summary-card--${escapeHtml(card.tone)}">
        <div class="prime-summary-card__label">${escapeHtml(card.label)}</div>
        <div class="prime-summary-card__value">${escapeHtml(card.value)}</div>
        <div class="prime-summary-card__copy">${escapeHtml(card.copy)}</div>
      </article>
    `).join('');

    if (homePrimeFocus) {
      if (topItem) {
        homePrimeFocus.textContent = `${dangerCount ? `${dangerCount} critical` : `${warnCount} active`} · ${topItem.title}`;
      } else if (opsPayload?.needs_turn) {
        homePrimeFocus.textContent = `${opsPayload.needs_turn} worker${opsPayload.needs_turn === 1 ? '' : 's'} ready for another turn`;
      } else if (opsPayload?.working) {
        homePrimeFocus.textContent = `${opsPayload.working} worker${opsPayload.working === 1 ? '' : 's'} still working`;
      } else {
        homePrimeFocus.textContent = `Tasks clear · ${groups.length} lane${groups.length === 1 ? '' : 's'} ready`;
      }
    }
    if (homePrimeOpenCount) {
      homePrimeOpenCount.textContent = String(activeItems.length || 0);
    }
    if (homePrimeCriticalCount) {
      homePrimeCriticalCount.textContent = String(dangerCount || 0);
    }
  }

  function renderHomePrime(groups) {
    if (homePrimeLanes) {
      homePrimeLanes.innerHTML = groups.length
        ? groups.map((principal) => renderPrimeLaneCard(principal)).join('')
        : '<div class="home-prime__placeholder">No live lanes published yet.</div>';
    }
    renderPrimeActionButtons(groups);
    renderDispatchCards(groups);
    renderPrimeSummary(attentionItemsRef.current || [], groups);
  }

  function normalizeFleetLookupUrl(url) {
    const value = String(url || '').trim();
    if (!value) return '';
    try {
      const parsed = new URL(value, window.location.origin);
      return `${parsed.origin}${parsed.pathname}`.replace(/\/+$/, '');
    } catch (err) {
      return value.replace(/\?.*$/, '').replace(/\/+$/, '');
    }
  }

  function buildFleetRouteIndex(groups) {
    const index = new Map();
    groups.forEach((principal) => {
      (principal.services || []).forEach((service) => {
        [
          service.console_url,
          service.console_url_tailnet,
          service.web_url,
          service.web_url_tailnet,
        ].forEach((value) => {
          const key = normalizeFleetLookupUrl(value);
          if (!key) return;
          index.set(key, {
            principalName: principal.display_name,
            serviceName: service.display_name || service.slug || '',
            serviceSlug: service.slug || '',
            consoleUrl: primaryServiceLink(service, 'console'),
            appUrl: primaryServiceLink(service, 'web'),
            proxyPath: proxyPathForService(service),
          });
        });
      });
    });
    return index;
  }

  function operatorModeLabel(mode) {
    const clean = String(mode || 'observe').trim().toLowerCase();
    if (clean === 'take') return 'Manual';
    if (clean === 'co_pilot') return 'Shared';
    return 'Auto';
  }

  function opsPriority(state) {
    const priorities = {
      needs_turn: 0,
      working: 1,
      manual: 2,
      shared: 3,
      locked: 4,
      stopped: 5,
      ready: 6,
      live: 7,
    };
    return Object.prototype.hasOwnProperty.call(priorities, state) ? priorities[state] : 20;
  }

  function opsTone(state) {
    if (state === 'needs_turn') return 'warn';
    if (state === 'working') return 'ok';
    if (state === 'locked' || state === 'stopped') return 'danger';
    if (state === 'manual' || state === 'shared') return 'shared';
    return 'idle';
  }

  function opsActionSummary(item) {
    const parts = [];
    if (item.operator_mode) parts.push(operatorModeLabel(item.operator_mode));
    if (item.running) parts.push('tmux live');
    else parts.push('tmux stopped');
    if (item.status_available && item.last_action_at) {
      parts.push(formatPrimeInboxAge(item.last_action_at * 1000));
    } else if (item.status_available && item.last_finished_at) {
      parts.push(formatPrimeInboxAge(item.last_finished_at * 1000));
    }
    return parts.join(' · ');
  }

  function opsPrimePrompt(item) {
    const name = item.display_name || item.connector_name || item.session_name;
    const latest = item.response_preview || item.status_message || item.state_detail || 'No recent reply is recorded.';
    return `Norman, take point on ${name}.\n\nCurrent state: ${item.state_label}\nMode: ${operatorModeLabel(item.operator_mode)}\nDetail: ${item.state_detail || item.status_message || 'No extra detail'}\nLatest output: ${latest}\n\nDecide whether ${name} needs another turn, what that turn should be, and whether Norman should keep coordinating it or hand it to another bot.`;
  }

  function opsFlowPrompt(lane, item = null) {
    if (item) {
      const name = item.display_name || item.connector_name || item.session_name;
      return `Norman, keep ${name} moving.\n\n${opsPrimePrompt(item)}\n\nWrite the next turn, decide whether to keep it in Norman or hand it to another bot, and call out any kill-switch or unwind step if the flow should stop instead.`;
    }
    return `Norman, set up the next ${lane} flow.\n\nLook across the current ${lane} bots, identify the best active thread to continue or the most useful new thread to open, and give me the shortest clear next prompt to send.`;
  }

  function laneOptionsForOps(items) {
    const counts = new Map([['All', 0]]);
    items.forEach((item) => {
      const lane = item.lane || 'Shared';
      counts.set('All', (counts.get('All') || 0) + 1);
      counts.set(lane, (counts.get(lane) || 0) + 1);
    });
    return ['All', 'Norman', 'Private', 'Personal', 'Work', 'Shared']
      .filter((lane) => (counts.get(lane) || 0) > 0 || lane === 'All')
      .map((lane) => ({ lane, count: counts.get(lane) || 0 }));
  }

  function opsItemsForLane(items, lane) {
    if (!lane || lane === 'All') return items;
    return items.filter((item) => item.lane === lane);
  }

  function opsItemsForMode(items, mode) {
    const clean = String(mode || 'all').toLowerCase();
    if (clean === 'waiting') return items.filter((item) => item.state === 'needs_turn');
    if (clean === 'working') return items.filter((item) => item.state === 'working');
    if (clean === 'unwind') return items.filter((item) => ['locked', 'manual', 'shared', 'stopped'].includes(String(item.state || '')));
    return items;
  }

  function opsModeOptions(items) {
    const counts = {
      waiting: items.filter((item) => item.state === 'needs_turn').length,
      working: items.filter((item) => item.state === 'working').length,
      unwind: items.filter((item) => ['locked', 'manual', 'shared', 'stopped'].includes(String(item.state || ''))).length,
      all: items.length,
    };
    return [
      { mode: 'waiting', label: 'Needs turn', count: counts.waiting },
      { mode: 'working', label: 'Working', count: counts.working },
      { mode: 'unwind', label: 'Needs unwind', count: counts.unwind },
      { mode: 'all', label: 'All', count: counts.all },
    ].filter((entry) => entry.count > 0 || entry.mode === 'all');
  }

  function visibleOpsItems(payload) {
    const managedItems = (payload?.items || []).filter((item) => item.managed);
    const actionable = managedItems.filter((item) => opsPriority(item.state) <= 5);
    const quiet = managedItems.filter((item) => opsPriority(item.state) > 5);
    return actionable.concat(quiet.slice(0, Math.max(0, 4 - actionable.length))).slice(0, 8);
  }

  function renderPrimeOpsSummary(payload) {
    if (!homePrimeOpsSummary) return;
    const cards = [
      { label: 'Needs turn', value: payload?.needs_turn || 0, tone: payload?.needs_turn ? 'warn' : 'idle' },
      { label: 'Working', value: payload?.working || 0, tone: payload?.working ? 'ok' : 'idle' },
      { label: 'Locked', value: payload?.locked || 0, tone: payload?.locked ? 'danger' : 'idle' },
      { label: 'Stopped', value: payload?.stopped || 0, tone: payload?.stopped ? 'shared' : 'idle' },
    ];
    homePrimeOpsSummary.innerHTML = cards.map((card) => `
      <article class="prime-ops-summary-card prime-ops-summary-card--${escapeHtml(card.tone)}">
        <div class="prime-ops-summary-card__value">${escapeHtml(String(card.value))}</div>
        <div class="prime-ops-summary-card__label">${escapeHtml(card.label)}</div>
      </article>
    `).join('');
  }

  function renderPrimeOps(payload, groups) {
    if (!homePrimeOps || !homePrimeOpsSummary) return;
    if (!payload || !Array.isArray(payload.items)) {
      homePrimeOps.innerHTML = '<div class="home-prime__placeholder">Worker state is unavailable right now.</div>';
      renderPrimeChats(null);
      if (homePrimeOpsFilters) {
        homePrimeOpsFilters.innerHTML = '<div class="home-prime__placeholder">Lane focus unavailable.</div>';
      }
      if (homePrimeOpsModes) {
        homePrimeOpsModes.innerHTML = '<div class="home-prime__placeholder">Ops views unavailable.</div>';
      }
      if (homePrimeOpsFocus) {
        homePrimeOpsFocus.innerHTML = '<div class="home-prime__placeholder">No live worker focus is available right now.</div>';
      }
      renderPrimeOpsSummary(null);
      if (homePrimeOpsStatus) homePrimeOpsStatus.textContent = 'Unavailable';
      return;
    }

    const routeIndex = buildFleetRouteIndex(groups);
    const normalizedItems = (payload.items || []).filter((item) => item.managed).map((item) => {
      const routeMeta = routeIndex.get(normalizeFleetLookupUrl(item.web_url)) || null;
      return {
        ...item,
        lane: routeMeta?.principalName || (item.session_name === 'norman-agent' ? 'Norman' : 'Shared'),
        display_name: routeMeta?.serviceName || item.connector_name || item.session_name,
        console_url: routeMeta?.consoleUrl || String(item.web_url || '').trim(),
        app_url: routeMeta?.appUrl || '',
        proxy_path: routeMeta?.proxyPath || '',
      };
    });
    const laneOptions = laneOptionsForOps(normalizedItems);
    if (!laneOptions.some((entry) => entry.lane === selectedPrimeOpsLane)) {
      selectedPrimeOpsLane = 'All';
    }
    const laneItems = opsItemsForLane(normalizedItems, selectedPrimeOpsLane);
    const modeOptions = opsModeOptions(laneItems);
    if (!modeOptions.some((entry) => entry.mode === selectedPrimeOpsMode)) {
      selectedPrimeOpsMode = modeOptions[0]?.mode || 'all';
    }
    const modeItems = opsItemsForMode(laneItems, selectedPrimeOpsMode);
    const lanePayload = {
      ...payload,
      items: modeItems,
      running: modeItems.filter((item) => item.running).length,
      working: modeItems.filter((item) => item.state === 'working').length,
      needs_turn: modeItems.filter((item) => item.state === 'needs_turn').length,
      locked: modeItems.filter((item) => item.state === 'locked').length,
      stopped: modeItems.filter((item) => item.state === 'stopped').length,
    };
    const visible = visibleOpsItems(lanePayload);
    const topWaiting = modeItems.find((item) => item.state === 'needs_turn')
      || modeItems.find((item) => item.state === 'working')
      || modeItems.find((item) => ['locked', 'manual', 'shared', 'stopped'].includes(String(item.state || '')))
      || modeItems[0]
      || null;

    renderPrimeOpsSummary(lanePayload);
    if (homePrimeAgentCount) {
      homePrimeAgentCount.textContent = String(payload.needs_turn || 0);
    }
    renderPrimeChats(normalizedItems);
    if (homePrimeOpsStatus) {
      const liveCount = lanePayload.running || 0;
      const prefix = selectedPrimeOpsLane === 'All' ? 'All lanes' : selectedPrimeOpsLane;
      homePrimeOpsStatus.textContent = `${prefix} · ${lanePayload.needs_turn || 0} waiting · ${lanePayload.working || 0} working · ${liveCount} live`;
    }

    if (homePrimeOpsFilters) {
      homePrimeOpsFilters.innerHTML = laneOptions.map((entry) => `
        <button
          type="button"
          class="home-prime__ops-filter${entry.lane === selectedPrimeOpsLane ? ' is-active' : ''}"
          data-prime-ops-lane="${escapeHtml(entry.lane)}"
        >
          <span class="home-prime__ops-filter-label">${escapeHtml(entry.lane)}</span>
          <span class="home-prime__ops-filter-count">${escapeHtml(String(entry.count))}</span>
        </button>
      `).join('');
    }

    if (homePrimeOpsModes) {
      homePrimeOpsModes.innerHTML = modeOptions.map((entry) => `
        <button
          type="button"
          class="home-prime__ops-mode${entry.mode === selectedPrimeOpsMode ? ' is-active' : ''}"
          data-prime-ops-mode="${escapeHtml(entry.mode)}"
        >
          <span class="home-prime__ops-mode-label">${escapeHtml(entry.label)}</span>
          <span class="home-prime__ops-mode-count">${escapeHtml(String(entry.count))}</span>
        </button>
      `).join('');
    }

    if (homePrimeOpsFocus) {
      if (topWaiting) {
        const focusPrompt = opsFlowPrompt(selectedPrimeOpsLane, topWaiting);
        const focusLabel = selectedPrimeOpsMode === 'working'
          ? 'Top working'
          : selectedPrimeOpsMode === 'unwind'
            ? 'Top unwind'
            : 'Top waiting';
        homePrimeOpsFocus.innerHTML = `
          <div class="home-prime__ops-focus-copy">
            <div class="home-prime__ops-focus-label">${escapeHtml(focusLabel)}</div>
            <div class="home-prime__ops-focus-title">${escapeHtml(topWaiting.display_name || topWaiting.session_name)}</div>
            <div class="home-prime__ops-focus-detail">${escapeHtml(topWaiting.state_detail || topWaiting.status_message || 'Worker ready for the next decision.')}</div>
          </div>
          <div class="home-prime__ops-focus-actions">
            <button type="button" class="btn btn-primary btn-sm" data-prime-compose-draft="${escapeHtml(focusPrompt)}">Use here</button>
            ${topWaiting.web_url ? `<a class="btn btn-outline-secondary btn-sm" href="${escapeHtml(topWaiting.web_url)}" target="_blank" rel="noreferrer">Open</a>` : ''}
            <a class="btn btn-outline-secondary btn-sm" href="${escapeHtml(primeNormanThreadHref(focusPrompt))}">Editor</a>
            <button type="button" class="btn btn-outline-secondary btn-sm" data-prime-compose-draft="${escapeHtml(opsFlowPrompt(selectedPrimeOpsLane))}">New flow</button>
          </div>
        `;
      } else {
        homePrimeOpsFocus.innerHTML = `
          <div class="home-prime__ops-focus-copy">
            <div class="home-prime__ops-focus-label">Worker focus</div>
            <div class="home-prime__ops-focus-title">Nothing matches this view right now</div>
            <div class="home-prime__ops-focus-detail">Switch the lane or worker view, or let Norman open a new flow from here.</div>
          </div>
          <div class="home-prime__ops-focus-actions">
            <button type="button" class="btn btn-primary btn-sm" data-prime-compose-draft="${escapeHtml(opsFlowPrompt(selectedPrimeOpsLane))}">New flow</button>
            <a class="btn btn-outline-secondary btn-sm" href="${escapeHtml(primeNormanThreadHref(opsFlowPrompt(selectedPrimeOpsLane)))}">Editor</a>
          </div>
        `;
      }
    }

    if (!visible.length) {
      homePrimeOps.innerHTML = '<div class="home-prime__placeholder">No workers are published for this lane.</div>';
      return;
    }

    const hiddenCount = Math.max(0, modeItems.length - visible.length);
    homePrimeOps.innerHTML = `
      <div class="home-prime__ops-grid">
        ${visible.map((item) => {
          const tone = opsTone(item.state);
          const selected = String(item.session_name || '') === selectedPrimeChatSession;
          const prompt = opsPrimePrompt(item);
          const canUnwind = item.locked || String(item.operator_mode || '').toLowerCase() !== 'observe';
          const preview = item.response_preview || item.prompt_preview || item.state_detail || item.status_message || 'No recent console detail.';
          return `
            <article class="prime-op-card prime-op-card--${escapeHtml(tone)}${selected ? ' is-selected' : ''}" data-prime-session="${escapeHtml(item.session_name)}">
              <div class="prime-op-card__head">
                <div>
                  <div class="prime-op-card__title-row">
                    <span class="prime-op-card__lane prime-op-card__lane--${escapeHtml(String(item.lane || 'Shared').toLowerCase())}">${escapeHtml(item.lane || 'Shared')}</span>
                    <div class="prime-op-card__title">${escapeHtml(item.display_name || item.session_name)}</div>
                  </div>
                  <div class="prime-op-card__session">${escapeHtml(item.session_name)}</div>
                </div>
                <span class="prime-op-card__state prime-op-card__state--${escapeHtml(tone)}">${escapeHtml(item.state_label || 'Ready')}</span>
              </div>
              <div class="prime-op-card__detail">${escapeHtml(item.state_detail || item.status_message || 'Worker ready.')}</div>
              <div class="prime-op-card__preview">${escapeHtml(preview)}</div>
              <div class="prime-op-card__meta">${escapeHtml(opsActionSummary(item))}</div>
              <div class="prime-op-card__actions">
                <button type="button" class="btn btn-primary btn-sm" data-prime-compose-draft="${escapeHtml(prompt)}">Use here</button>
                <a class="btn btn-outline-secondary btn-sm" href="${escapeHtml(primeNormanThreadHref(prompt))}">Editor</a>
                ${item.web_url ? `<a class="btn btn-outline-secondary btn-sm" href="${escapeHtml(item.web_url)}" target="_blank" rel="noreferrer">Open</a>` : ''}
                ${item.running
                  ? `<button type="button" class="btn btn-outline-secondary btn-sm" data-prime-op-action="stop" data-prime-session="${escapeHtml(item.session_name)}">Stop</button>`
                  : `<button type="button" class="btn btn-outline-secondary btn-sm" data-prime-op-action="start" data-prime-session="${escapeHtml(item.session_name)}">Continue</button>`}
                ${item.locked
                  ? `<button type="button" class="btn btn-outline-secondary btn-sm" data-prime-op-action="unlock" data-prime-session="${escapeHtml(item.session_name)}">Unlock</button>`
                  : `<button type="button" class="btn btn-outline-secondary btn-sm" data-prime-op-action="lock" data-prime-session="${escapeHtml(item.session_name)}">Lock</button>`}
                ${canUnwind ? `<button type="button" class="btn btn-outline-secondary btn-sm" data-prime-op-action="unwind" data-prime-session="${escapeHtml(item.session_name)}">Unwind</button>` : ''}
              </div>
            </article>
          `;
        }).join('')}
      </div>
      ${hiddenCount ? `<div class="prime-op-card__footnote">Showing ${visible.length} active workers first · ${hiddenCount} quieter worker${hiddenCount === 1 ? '' : 's'} tucked away.</div>` : ''}
    `;
  }

  function formatPrimeCount(value) {
    return Number(value || 0).toLocaleString();
  }

  function formatPrimeTokenCompact(value) {
    const amount = Number(value || 0);
    if (!Number.isFinite(amount) || amount <= 0) return '0';
    if (amount >= 1000000) return `${(amount / 1000000).toFixed(amount >= 10000000 ? 0 : 1)}M`;
    if (amount >= 1000) return `${(amount / 1000).toFixed(amount >= 100000 ? 0 : 1)}k`;
    return formatPrimeCount(amount);
  }

  function primeCreditTone(item) {
    if (item.issue_code === 'needs_billing') return 'danger';
    if (item.issue_code === 'needs_reauth') return 'warn';
    if (item.codex_subscription_capacity_state === 'blocked') return 'warn';
    if (item.recommended_speed) return 'shared';
    if (Number(item.usage_window_total_tokens || 0) > 0) return 'ok';
    return 'idle';
  }

  function primeSubscriptionCapacityLabel(item) {
    const state = String(item.codex_subscription_capacity_state || 'unknown');
    const percent = Number(item.codex_subscription_capacity_percent_left);
    if (state === 'available' && item.codex_subscription_capacity_fresh && Number.isFinite(percent) && percent >= 0) {
      return `Plan ${percent}% left`;
    }
    if (state === 'blocked') return 'Plan capped';
    if (state === 'available') return 'Plan reading stale';
    return 'Plan unavailable';
  }

  function primeCreditItems(payload) {
    return [...(payload.items || [])]
      .filter((item) => item.issue_code || item.recommended_speed || item.codex_subscription_capacity_state === 'available' || item.codex_subscription_capacity_state === 'blocked' || Number(item.usage_window_total_tokens || 0) > 0 || Number(item.usage_total_tokens || 0) > 0)
      .sort((left, right) => {
        const leftPriority = left.issue_code === 'needs_billing' ? 0 : left.issue_code === 'needs_reauth' ? 1 : left.recommended_speed ? 2 : 3;
        const rightPriority = right.issue_code === 'needs_billing' ? 0 : right.issue_code === 'needs_reauth' ? 1 : right.recommended_speed ? 2 : 3;
        if (leftPriority !== rightPriority) return leftPriority - rightPriority;
        return Number(right.usage_window_total_tokens || 0) - Number(left.usage_window_total_tokens || 0);
      });
  }

  function renderPrimeCredits(payload) {
    if (!homePrimeCreditsSummary || !homePrimeCreditsItems) return;
    if (!payload || !Array.isArray(payload.items)) {
      homePrimeCreditsSummary.innerHTML = '<div class="home-prime__placeholder">Fleet credit state is unavailable right now.</div>';
      homePrimeCreditsItems.innerHTML = '<div class="home-prime__placeholder">No fleet credit details are available.</div>';
      if (homePrimeCreditsStatus) homePrimeCreditsStatus.textContent = 'Unavailable';
      return;
    }

    const cards = [
      { label: 'Needs billing', value: payload.needs_billing || 0, tone: payload.needs_billing ? 'danger' : 'idle' },
      { label: 'Needs reauth', value: payload.needs_reauth || 0, tone: payload.needs_reauth ? 'warn' : 'idle' },
      { label: 'Fast to rebalance', value: payload.downgrade_candidates || 0, tone: payload.downgrade_candidates ? 'shared' : 'idle' },
      { label: '24h burn', value: formatPrimeTokenCompact(payload.usage_window_total_tokens || 0), tone: payload.usage_window_total_tokens ? 'ok' : 'idle' },
      { label: 'Plan capacity', value: payload.codex_subscription_capacity_available || 0, tone: payload.codex_subscription_capacity_available ? 'ok' : 'idle' },
    ];
    homePrimeCreditsSummary.innerHTML = cards.map((card) => `
      <article class="prime-ops-summary-card prime-ops-summary-card--${escapeHtml(card.tone)}">
        <div class="prime-ops-summary-card__value">${escapeHtml(String(card.value))}</div>
        <div class="prime-ops-summary-card__label">${escapeHtml(card.label)}</div>
      </article>
    `).join('');

    const actionable = primeCreditItems(payload).slice(0, 4);
    if (!actionable.length) {
      homePrimeCreditsItems.innerHTML = '<div class="home-prime__placeholder">Fleet credit state looks steady right now.</div>';
    } else {
      homePrimeCreditsItems.innerHTML = actionable.map((item) => `
        <article class="prime-credit-card prime-credit-card--${escapeHtml(primeCreditTone(item))}">
          <div class="prime-credit-card__head">
            <div class="prime-credit-card__title">${escapeHtml(item.display_name || item.connector_name || item.session_name)}</div>
            <div class="prime-credit-card__meta">${escapeHtml(item.chat_model || item.default_speed || 'bot')}</div>
          </div>
          <div class="prime-credit-card__detail">${escapeHtml(item.issue_summary || item.recommended_speed_reason || 'No credit issue detected.')}</div>
          <div class="prime-credit-card__stats">
            <span>24h ${escapeHtml(formatPrimeTokenCompact(item.usage_window_total_tokens || 0))} tok</span>
            <span>Total ${escapeHtml(formatPrimeTokenCompact(item.usage_total_tokens || 0))} tok</span>
            <span>${escapeHtml(formatPrimeCount(item.usage_turns || 0))} turn${Number(item.usage_turns || 0) === 1 ? '' : 's'}</span>
            <span>${escapeHtml(primeSubscriptionCapacityLabel(item))}</span>
            ${Number(item.codex_subscription_capacity_tokens_per_hour || 0) > 0 ? `<span>Forecast ${escapeHtml(formatPrimeTokenCompact(item.codex_subscription_capacity_tokens_per_hour))} tok/h</span>` : ''}
          </div>
          <div class="prime-credit-card__actions">
            ${item.billing_url ? `<a class="btn btn-outline-secondary btn-sm" href="${escapeHtml(item.billing_url)}" target="_blank" rel="noreferrer">Billing</a>` : ''}
            ${item.limits_url ? `<a class="btn btn-outline-secondary btn-sm" href="${escapeHtml(item.limits_url)}" target="_blank" rel="noreferrer">Limits</a>` : ''}
            ${item.web_url ? `<a class="btn btn-outline-secondary btn-sm" href="${escapeHtml(item.web_url)}" target="_blank" rel="noreferrer">Open bot</a>` : ''}
          </div>
        </article>
      `).join('');
    }

    if (homePrimeCreditsStatus) {
      homePrimeCreditsStatus.textContent = `${payload.checked || 0}/${payload.count || 0} checked · ${payload.reachable || 0} reachable · ${payload.usage_tracked || 0} tracked · ${formatPrimeCount(payload.usage_turns || 0)} turns`;
    }
  }

  function llmStatusTone(payload) {
    const mode = String(payload?.mode || '').trim();
    if (mode === 'primary') return 'ok';
    if (mode === 'backup_online' || mode === 'offline_local') return 'warn';
    if (mode === 'control_only') return payload?.configured ? 'danger' : 'idle';
    return 'idle';
  }

  function llmCreditToneClass(tone) {
    if (tone === 'danger') return ' prime-credit-card--danger';
    if (tone === 'warn') return ' prime-credit-card--warn';
    return '';
  }

  function llmProviderEndpoint(baseUrl) {
    const raw = String(baseUrl || '').trim();
    if (!raw) return '';
    try {
      const parsed = new URL(raw);
      const path = parsed.pathname && parsed.pathname !== '/' ? parsed.pathname : '';
      return `${parsed.host}${path}`;
    } catch (err) {
      return raw.split('?')[0].replace(/\/\/[^/@]+@/, '//');
    }
  }

  function llmProviderSummary(provider) {
    const pieces = [
      String(provider.model || '').trim(),
      llmProviderEndpoint(provider.base_url),
    ].filter(Boolean);
    return pieces.join(' @ ') || provider.kind || provider.label || 'Provider';
  }

  function llmPingTone(item) {
    if (item.status === 'ok') return 'ok';
    if (item.status === 'warn') return 'warn';
    if (item.status === 'error') return 'danger';
    return 'idle';
  }

  function llmTimestampAge(epochSeconds) {
    const value = Number(epochSeconds || 0);
    if (!Number.isFinite(value) || value <= 0) return 'No success yet';
    return formatPrimeInboxAge(value < 100000000000 ? value * 1000 : value);
  }

  function renderPrimeLlmStatus(payload) {
    if (!homePrimeLlmSummary || !homePrimeLlmItems) return;
    if (!payload || !Array.isArray(payload.providers)) {
      homePrimeLlmSummary.innerHTML = '<div class="home-prime__placeholder">Model runtime state is unavailable right now.</div>';
      homePrimeLlmItems.innerHTML = '<div class="home-prime__placeholder">No provider chain details are available.</div>';
      if (homePrimeLlmStatus) homePrimeLlmStatus.textContent = 'Unavailable';
      return;
    }

    const tone = llmStatusTone(payload);
    const modeLabel = String(payload.mode_label || payload.mode || 'Unknown').trim() || 'Unknown';
    const providerLabel = String(payload.active_provider_label || 'Unavailable').trim() || 'Unavailable';
    const activeModel = String(payload.active_model || '').trim() || 'Unset';
    const lastSuccess = llmTimestampAge(payload.last_success_at);
    const cards = [
      { label: 'Mode', value: modeLabel, tone },
      { label: 'Provider', value: providerLabel, tone },
      { label: 'Model', value: activeModel, tone: payload.active_model ? tone : 'idle' },
      { label: 'Last success', value: lastSuccess, tone: payload.last_success_at ? 'ok' : 'idle' },
    ];
    homePrimeLlmSummary.innerHTML = cards.map((card) => `
      <article class="prime-ops-summary-card prime-ops-summary-card--${escapeHtml(card.tone)}">
        <div class="prime-ops-summary-card__value">${escapeHtml(String(card.value))}</div>
        <div class="prime-ops-summary-card__label">${escapeHtml(card.label)}</div>
      </article>
    `).join('');

    const providerRows = payload.providers.map((provider) => {
      const providerData = provider || {};
      const configured = Boolean(providerData.configured);
      return `
        <span>${escapeHtml(providerData.slot || 'provider')} · ${configured ? 'ready' : 'off'}</span>
        <span>${escapeHtml(llmProviderSummary(providerData))}</span>
      `;
    }).join('');
    const pingPayload = window.__normanLlmPingPayload || null;
    const pingRows = Array.isArray(pingPayload?.items)
      ? pingPayload.items.map((item) => {
        const label = `${item.name || item.id || 'model'} · ${item.status || 'unknown'}`;
        const detailText = item.status === 'error'
          ? (item.error || 'Ping failed')
          : `${item.model || 'model'} · ${item.latency_ms || 0}ms`;
        return `
          <span class="prime-credit-card__stats--${escapeHtml(llmPingTone(item))}">${escapeHtml(label)}</span>
          <span>${escapeHtml(detailText)}</span>
        `;
      }).join('')
      : '';
    const detail = String(
      payload.fallback_reason
      || payload.last_error
      || (payload.configured ? 'Provider chain is configured and waiting for the next model call.' : 'No model provider is configured.'),
    ).trim();
    homePrimeLlmItems.innerHTML = `
      <article class="prime-credit-card${llmCreditToneClass(tone)}">
        <div class="prime-credit-card__head">
          <div class="prime-credit-card__title">${escapeHtml(modeLabel)}</div>
          <div class="prime-credit-card__meta">${escapeHtml(payload.fallback_active ? 'fallback' : 'active')}</div>
        </div>
        <div class="prime-credit-card__detail">${escapeHtml(detail)}</div>
        <div class="prime-credit-card__stats">${providerRows}</div>
        ${pingRows ? `<div class="prime-credit-card__stats">${pingRows}</div>` : ''}
      </article>
    `;

    if (homePrimeLlmStatus) {
      homePrimeLlmStatus.textContent = payload.fallback_active ? `${modeLabel} fallback` : modeLabel;
    }
  }

  function primeChatTimestamp(item) {
    const stamps = [
      Number(item?.last_action_at || 0),
      Number(item?.last_finished_at || 0),
      Number(item?.updated_at || 0),
    ].filter((value) => Number.isFinite(value) && value > 0);
    return (stamps.length ? Math.max(...stamps) : Date.now() / 1000) * 1000;
  }

  function primeChatPreview(item) {
    return String(
      item?.response_preview
      || item?.status_message
      || item?.state_detail
      || 'No recent reply captured yet.',
    ).trim();
  }

  function syncPrimeChatSelection(items) {
    if (!selectedPrimeChatSession || !items.some((item) => String(item.session_name || '') === selectedPrimeChatSession)) {
      selectedPrimeChatSession = items[0] ? String(items[0].session_name || '') : null;
    }
  }

  function syncPrimeOpsToChat(item) {
    if (!item) return;
    selectedPrimeChatSession = String(item.session_name || '');
    selectedPrimeOpsLane = String(item.lane || 'All');
    if (item.state === 'working') {
      selectedPrimeOpsMode = 'working';
    } else if (item.state === 'needs_turn') {
      selectedPrimeOpsMode = 'waiting';
    } else if (['locked', 'manual', 'shared', 'stopped'].includes(String(item.state || ''))) {
      selectedPrimeOpsMode = 'unwind';
    } else {
      selectedPrimeOpsMode = 'all';
    }
  }

  function renderPrimeChats(items) {
    if (!homePrimeChats || !homePrimeChatsStatus) return;
    if (!Array.isArray(items)) {
      if (homePrimeChatCount) homePrimeChatCount.textContent = '0';
      homePrimeChatsStatus.textContent = 'Unavailable';
      homePrimeChats.innerHTML = '<div class="home-prime__placeholder">Recent chat traces are unavailable right now.</div>';
      return;
    }

    const recent = [...items]
      .sort((left, right) => primeChatTimestamp(right) - primeChatTimestamp(left))
      .slice(0, 6);
    const liveCount = items.filter((item) => item.running || item.state === 'working').length;
    syncPrimeChatSelection(recent);

    if (homePrimeChatCount) {
      homePrimeChatCount.textContent = String(items.length || 0);
    }

    if (!recent.length) {
      homePrimeChatsStatus.textContent = '0 recent';
      homePrimeChats.innerHTML = '<div class="home-prime__placeholder">No recent chat traces yet. Prime will show the latest worker tone here once replies start landing.</div>';
      return;
    }

    homePrimeChatsStatus.textContent = `${recent.length} recent · ${liveCount} live`;
    homePrimeChats.innerHTML = recent.map((item) => {
      const tone = opsTone(item.state);
      const lane = String(item.lane || 'Shared');
      const laneSlug = lane.toLowerCase();
      const stateLabel = String(item.state_label || 'Ready');
      const selected = String(item.session_name || '') === selectedPrimeChatSession;
      const preview = primeChatPreview(item);
      const prompt = opsPrimePrompt(item);
      const primeHref = buildEditorDraftLink({
        thread: `console - ${item.display_name || item.session_name || 'Worker'}`,
        draft: prompt,
      });
      const consoleHref = String(item.console_url || item.web_url || '').trim();
      const appHref = String(item.app_url || '').trim();
      const sourceLabel = item.session_name
        ? `Source · ${item.session_name}`
        : item.status_available
          ? 'Source · Live status'
          : 'Source · Snapshot';

      return `
        <article class="prime-chat-card prime-chat-card--${escapeHtml(tone)}${selected ? ' is-selected' : ''}" data-prime-chat-session="${escapeHtml(String(item.session_name || ''))}" tabindex="0">
          <div class="prime-chat-card__head">
            <div class="prime-chat-card__title-row">
              <span class="prime-chat-card__lane prime-chat-card__lane--${escapeHtml(laneSlug)}">${escapeHtml(lane)}</span>
              <div class="prime-chat-card__title">${escapeHtml(item.display_name || item.session_name)}</div>
            </div>
            <span class="prime-chat-card__state prime-chat-card__state--${escapeHtml(tone)}">${escapeHtml(stateLabel)}</span>
          </div>
          <div class="prime-chat-card__preview-label">Latest reply</div>
          <div class="prime-chat-card__preview">${escapeHtml(preview)}</div>
          <div class="prime-chat-card__meta">
            <span>${escapeHtml(formatPrimeInboxAge(primeChatTimestamp(item)))}</span>
            <span>${escapeHtml(sourceLabel)}</span>
          </div>
          <div class="prime-chat-card__actions">
            <button type="button" class="btn btn-primary btn-sm" data-prime-compose-draft="${escapeHtml(prompt)}">Use here</button>
            <a class="btn btn-outline-secondary btn-sm" href="${escapeHtml(primeHref)}">Editor</a>
            ${consoleHref ? `<a class="btn btn-outline-secondary btn-sm" href="${escapeHtml(consoleHref)}" target="_blank" rel="noreferrer">Console</a>` : ''}
            ${appHref && appHref !== consoleHref ? `<a class="btn btn-outline-secondary btn-sm" href="${escapeHtml(appHref)}" target="_blank" rel="noreferrer">App</a>` : ''}
            ${item.proxy_path ? `<a class="btn btn-outline-secondary btn-sm" href="${escapeHtml(item.proxy_path)}" target="_blank" rel="noreferrer">Norman</a>` : ''}
          </div>
          <div class="prime-chat-card__trace">${selected ? 'Tracing this source in Workers' : 'Trace this source'}</div>
        </article>
      `;
    }).join('');
  }

  function primeAuditTone(item) {
    const severity = String(item?.severity || 'info').trim().toLowerCase();
    if (severity === 'critical' || severity === 'danger' || severity === 'error') return 'danger';
    if (severity === 'warn' || severity === 'warning') return 'warn';
    if (String(item?.event_type || '').trim().toLowerCase().includes('relay')) return 'shared';
    return 'ok';
  }

  function primeAuditLabel(item) {
    const eventType = String(item?.event_type || 'audit.event').trim();
    if (!eventType) return 'Audit event';
    return eventType
      .split(/[._:-]+/g)
      .filter(Boolean)
      .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
      .join(' ');
  }

  function primeAuditPrompt(item) {
    const label = primeAuditLabel(item);
    const summary = String(item?.summary || 'No summary recorded.').trim();
    const detail = String(item?.detail || '').trim();
    const session = String(item?.session_name || item?.agent_name || 'worker').trim();
    const host = String(item?.host_name || '').trim();
    return `Norman, review this TUI audit event.\n\nEvent: ${label}\nSession: ${session}\nHost: ${host || 'unknown'}\nSeverity: ${String(item?.severity || 'info').trim()}\nSummary: ${summary}${detail ? `\nDetail: ${detail}` : ''}\n\nTell me whether this is just operator noise, a forensics lead, or something that should move into Subprime for coordination.`;
  }

  function renderPrimeAudit(payload) {
    if (!homePrimeAuditSummary || !homePrimeAudit || !homePrimeAuditStatus) return;
    if (!payload || !Array.isArray(payload.items)) {
      homePrimeAuditSummary.innerHTML = '<div class="home-prime__placeholder">Recent TUI audit is unavailable right now.</div>';
      homePrimeAudit.innerHTML = '<div class="home-prime__placeholder">No centralized TUI audit details are available.</div>';
      homePrimeAuditStatus.textContent = 'Unavailable';
      return;
    }

    const items = [...payload.items]
      .sort((left, right) => parseTimestampMs(right.event_at || right.collected_at || 0) - parseTimestampMs(left.event_at || left.collected_at || 0))
      .slice(0, 6);
    const counts = items.reduce((acc, item) => {
      const tone = primeAuditTone(item);
      acc[tone] = (acc[tone] || 0) + 1;
      return acc;
    }, { danger: 0, warn: 0, shared: 0, ok: 0 });

    const cards = [
      { label: 'Recent', value: items.length, tone: items.length ? 'ok' : 'idle' },
      { label: 'Errors', value: counts.danger || 0, tone: counts.danger ? 'danger' : 'idle' },
      { label: 'Warnings', value: counts.warn || 0, tone: counts.warn ? 'warn' : 'idle' },
      { label: 'Relay / flow', value: counts.shared || 0, tone: counts.shared ? 'shared' : 'idle' },
    ];
    homePrimeAuditSummary.innerHTML = cards.map((card) => `
      <article class="prime-ops-summary-card prime-ops-summary-card--${escapeHtml(card.tone)}">
        <div class="prime-ops-summary-card__value">${escapeHtml(String(card.value))}</div>
        <div class="prime-ops-summary-card__label">${escapeHtml(card.label)}</div>
      </article>
    `).join('');

    if (!items.length) {
      homePrimeAudit.innerHTML = '<div class="home-prime__placeholder">No recent TUI audit events yet. Prime will surface prompts, relays, errors, and operator actions here.</div>';
      homePrimeAuditStatus.textContent = '0 recent';
      return;
    }

    homePrimeAudit.innerHTML = items.map((item) => {
      const tone = primeAuditTone(item);
      const when = parseTimestampMs(item.event_at || item.collected_at || 0);
      const session = String(item.session_name || item.agent_name || '').trim();
      const host = String(item.host_name || '').trim();
      const prompt = primeAuditPrompt(item);
      return `
        <article class="prime-audit-card prime-audit-card--${escapeHtml(tone)}" data-prime-audit-session="${escapeHtml(session)}" tabindex="0">
          <div class="prime-audit-card__head">
            <div class="prime-audit-card__title">${escapeHtml(primeAuditLabel(item))}</div>
            <span class="prime-audit-card__severity prime-audit-card__severity--${escapeHtml(tone)}">${escapeHtml(String(item.severity || 'info'))}</span>
          </div>
          <div class="prime-audit-card__detail">${escapeHtml(item.summary || 'No summary recorded.')}</div>
          ${item.detail ? `<div class="prime-audit-card__detail prime-audit-card__detail--muted">${escapeHtml(item.detail)}</div>` : ''}
          <div class="prime-audit-card__meta">
            ${session ? `<span>${escapeHtml(session)}</span>` : ''}
            ${host ? `<span>${escapeHtml(host)}</span>` : ''}
            <span>${escapeHtml(formatPrimeInboxAge(when || Date.now()))}</span>
          </div>
          <div class="prime-audit-card__actions">
            <button type="button" class="btn btn-primary btn-sm" data-prime-compose-draft="${escapeHtml(prompt)}">Use here</button>
            <a class="btn btn-outline-secondary btn-sm" href="${escapeHtml(primeNormanThreadHref(prompt))}">Editor</a>
            ${session ? '<span class="prime-audit-card__trace">Trace in Workers</span>' : '<span class="prime-audit-card__trace">Forensics view</span>'}
          </div>
        </article>
      `;
    }).join('');

    homePrimeAuditStatus.textContent = `${items.length} recent · ${counts.danger || 0} errors · ${counts.warn || 0} warnings`;
  }

  function inferInboxLane(item) {
    const href = String(item?.actionHref || '').toLowerCase();
    const title = String(item?.title || '').toLowerCase();
    if (
      href.includes('finance')
      || href.includes('health')
      || href.includes('private')
      || title.includes('finance')
      || title.includes('health')
      || title.includes('parkergale')
      || title.includes('parker gale')
      || title.includes('private equity funbot')
      || title.includes('pef')
    ) return 'Private';
    if (href.includes('/bots') || title.includes('bot')) return 'Work';
    if (href.includes('/connectors') || href.includes('/filters') || href.includes('/actions')) return 'Shared';
    if (href.includes('/channels') || href.includes('/editor')) return 'Norman';
    return 'Shared';
  }

  function principalByName(groups, name) {
    return groups.find((principal) => String(principal.display_name || '').trim().toLowerCase() === String(name || '').trim().toLowerCase()) || null;
  }

  function recommendedLaneLead(groups, laneName) {
    const principal = principalByName(groups, laneName) || groups[0] || null;
    if (!principal) return null;
    return principal.services.find((service) => primaryServiceLink(service, 'console')) || principal.services[0] || null;
  }

  function inboxPromptForItem(item, groups) {
    const lane = inferInboxLane(item);
    const lead = recommendedLaneLead(groups, lane);
    const leadName = lead ? (lead.display_name || lead.slug) : 'the right specialist bot';
    const evidence = item?.evidence ? `\nEvidence:\n${JSON.stringify(item.evidence, null, 2)}` : '';
    return `Norman, take point on this task card.\n\nLane: ${lane}\nTitle: ${item.title}\nDetail: ${item.detail}\nSuggested source: ${item.actionLabel}\nRecommended specialist: ${leadName}\n\nTriage it at a high level, decide whether ${leadName} or another bot should own it, and tell me the next action.${evidence}`;
  }

  function formatPrimeInboxAge(timestamp) {
    const age = formatAge(timestamp);
    if (age) return age;
    return new Date(timestamp || Date.now()).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });
  }

  function renderPrimeInbox(items, groups) {
    if (!homePrimeInbox || !homePrimeInboxCount) return;
    if (!items.length) {
      homePrimeInboxCount.textContent = '0 active';
      homePrimeInbox.innerHTML = '<div class="home-prime__placeholder">Nothing urgent. Norman Prime is waiting for the next task card.</div>';
      renderPrimeSummary([], groups);
      return;
    }

    if (!selectedPrimeInboxId || !items.some((item) => item.id === selectedPrimeInboxId)) {
      selectedPrimeInboxId = items[0].id;
    }

    homePrimeInboxCount.textContent = `${items.length} active`;
    homePrimeInbox.innerHTML = items.map((item) => {
      const lane = inferInboxLane(item);
      const laneSlug = lane.toLowerCase();
      const selected = item.id === selectedPrimeInboxId;
      const level = String(item.level || 'idle').toLowerCase();
      const levelLabel = level.charAt(0).toUpperCase() + level.slice(1);
      return `
        <article class="prime-inbox-card prime-inbox-card--${escapeHtml(level)}${selected ? ' is-selected' : ''}" data-prime-inbox-id="${escapeHtml(item.id)}" tabindex="0">
          <div class="prime-inbox-card__signal">
            <span class="prime-inbox-card__lane prime-inbox-card__lane--${escapeHtml(laneSlug)}">${escapeHtml(lane)}</span>
            <span class="prime-inbox-card__severity prime-inbox-card__severity--${escapeHtml(level)}">${escapeHtml(levelLabel)}</span>
          </div>
          <div class="prime-inbox-card__top">
            <div>
              <div class="prime-inbox-card__title">${escapeHtml(item.title)}</div>
              <div class="prime-inbox-card__detail">${escapeHtml(item.detail)}</div>
              <div class="prime-inbox-card__next">Next: ${escapeHtml(item.actionLabel || 'Review')}</div>
            </div>
            <span class="prime-inbox-card__state">${selected ? 'Selected' : 'Prime'}</span>
          </div>
          <div class="prime-inbox-card__meta">
            <span class="prime-inbox-card__pill">Fresh · ${escapeHtml(formatPrimeInboxAge(item.ts))}</span>
            <span class="prime-inbox-card__pill">Source · ${escapeHtml(item.actionLabel || 'Open')}</span>
          </div>
          <div class="prime-inbox-card__action">${selected ? 'Focused in Prime Desk' : 'Send to Prime Desk'}</div>
        </article>
      `;
    }).join('');

    renderPrimeSummary(items, groups);
    renderPrimeDesk(items.find((item) => item.id === selectedPrimeInboxId) || items[0], groups);
  }

  function renderPrimeDesk(item, groups) {
    if (!homePrimeDeskTitle || !homePrimeDeskMeta || !homePrimeDeskDetail || !homePrimeDeskPrompt || !homePrimeDeskActions) return;
    if (!item) {
      homePrimeDeskTitle.textContent = 'No task card selected';
      homePrimeDeskMeta.textContent = 'Waiting for the next task';
      homePrimeDeskDetail.textContent = 'Subprime will use the selected task card to coordinate the right worker while deep context stays in the specialist thread.';
      homePrimeDeskPrompt.textContent = 'Norman, look across the current task cards, decide what matters most, and tell me what should happen next.';
      homePrimeDeskActions.innerHTML = '<span class="home-prime__placeholder">Waiting for task actions…</span>';
      if (homePrimeDeskStatus) homePrimeDeskStatus.textContent = 'Waiting for task…';
      return;
    }

    const lane = inferInboxLane(item);
    const laneSlug = lane.toLowerCase();
    const level = String(item.level || 'idle').toLowerCase();
    const levelLabel = level.charAt(0).toUpperCase() + level.slice(1);
    const normanLead = findNormanLead(groups);
    const normanChat = primaryServiceLink(normanLead, 'console');
    const laneLead = recommendedLaneLead(groups, lane);
    const laneLeadChat = primaryServiceLink(laneLead, 'console');
    const laneLeadName = laneLead ? (laneLead.display_name || laneLead.slug) : 'Norman';
    const prompt = inboxPromptForItem(item, groups);
    const editorHref = primeNormanThreadHref(prompt);

    homePrimeDeskTitle.textContent = item.title;
    homePrimeDeskMeta.innerHTML = `
      <span class="prime-desk__meta-pill prime-desk__meta-pill--${escapeHtml(laneSlug)}">${escapeHtml(lane)} lane</span>
      <span class="prime-desk__meta-pill prime-desk__meta-pill--${escapeHtml(level)}">${escapeHtml(levelLabel)}</span>
      <span class="prime-desk__meta-pill">${escapeHtml(formatPrimeInboxAge(item.ts))}</span>
      <span class="prime-desk__meta-pill">Lead · ${escapeHtml(laneLeadName)}</span>
    `;
    homePrimeDeskDetail.textContent = item.detail;
    homePrimeDeskPrompt.textContent = prompt;
    seedPrimeNormanDraft(prompt);
    homePrimeDeskActions.innerHTML = `
      <button type="button" class="btn btn-primary btn-sm" data-prime-chat-send="${escapeHtml(prompt)}">Send now</button>
      <button type="button" class="btn btn-outline-secondary btn-sm" data-prime-compose-draft="${escapeHtml(prompt)}">Use here</button>
      <button type="button" class="btn btn-outline-secondary btn-sm dispatch-copy-btn" data-prime-prompt="${escapeHtml(prompt)}">Copy brief</button>
      <a class="btn btn-outline-secondary btn-sm" href="${escapeHtml(editorHref)}">Editor</a>
      ${normanChat ? `<a class="btn btn-outline-secondary btn-sm" href="${escapeHtml(normanChat)}" target="_blank" rel="noreferrer">Console</a>` : ''}
      ${laneLeadChat ? `<a class="btn btn-outline-secondary btn-sm" href="${escapeHtml(laneLeadChat)}" target="_blank" rel="noreferrer">Open ${escapeHtml(laneLeadName)}</a>` : ''}
      <a class="btn btn-outline-secondary btn-sm" href="${escapeHtml(item.actionHref || '/systems.html#agent-directory')}">${escapeHtml(item.actionLabel || 'Open source')}</a>
    `;
    if (homePrimeDeskStatus) {
      homePrimeDeskStatus.textContent = `${lane} card ready`;
    }
  }

  function classifyFleetUrl(url) {
    const value = String(url || '').trim();
    const lower = value.toLowerCase();
    if (!value) return '';
    if (isTailnetHostLike(lower)) return 'Tailnet';
    if (lower.includes('127.0.0.1') || lower.includes('localhost')) return 'Local';
    if (isLanHostLike(lower)) return 'LAN';
    return 'Web';
  }

  function hasFleetLinks(service) {
    return [
      service?.web_url,
      service?.web_url_tailnet,
      service?.console_url,
      service?.console_url_tailnet,
    ].some((value) => String(value || '').trim());
  }

  function fleetRouteState(service) {
    const hasApp = [service?.web_url, service?.web_url_tailnet].some((value) => String(value || '').trim());
    const hasChat = [service?.console_url, service?.console_url_tailnet].some((value) => String(value || '').trim());
    if (hasApp && hasChat) return { label: 'App + Chat', tone: 'ok' };
    if (hasChat) return { label: 'Chat', tone: 'warn' };
    if (hasApp) return { label: 'App', tone: 'warn' };
    return { label: 'Pending', tone: 'idle' };
  }

  function renderFleetActionButtons(service) {
    const actions = [];
    const webRoute = resolvePreferredFleetRoute(service.web_url, service.web_url_tailnet);
    const consoleRoute = resolvePreferredFleetRoute(service.console_url, service.console_url_tailnet);
    const proxyPath = proxyPathForService(service);

    if (proxyPath) {
      actions.push(
        `<a class="btn btn-sm btn-primary" href="${escapeHtml(proxyPath)}" target="_blank" rel="noreferrer">Norman</a>`,
      );
    }

    if (webRoute.primary) {
      actions.push(
        `<a class="btn btn-sm btn-outline-secondary" href="${escapeHtml(webRoute.primary)}" target="_blank" rel="noreferrer">${escapeHtml(routeModeLabel('Open', webRoute.mode, Boolean(webRoute.alternate)))}</a>`,
      );
    }
    if (webRoute.alternate) {
      actions.push(
        `<a class="btn btn-sm btn-outline-secondary" href="${escapeHtml(webRoute.alternate)}" target="_blank" rel="noreferrer">${escapeHtml(alternateRouteLabel('Open', webRoute.mode))}</a>`,
      );
    }
    if (consoleRoute.primary) {
      actions.push(
        `<a class="btn btn-sm btn-primary" href="${escapeHtml(consoleRoute.primary)}" target="_blank" rel="noreferrer">${escapeHtml(routeModeLabel('Chat', consoleRoute.mode, Boolean(consoleRoute.alternate)))}</a>`,
      );
    }
    if (consoleRoute.alternate) {
      actions.push(
        `<a class="btn btn-sm btn-primary" href="${escapeHtml(consoleRoute.alternate)}" target="_blank" rel="noreferrer">${escapeHtml(alternateRouteLabel('Chat', consoleRoute.mode))}</a>`,
      );
    }
    return actions;
  }

  function renderFleetServiceCard(service, { mobile = false } = {}) {
    const pills = [
      service.bot_name,
      service.policy_mode || service.policy_profile_name,
      service.worker_name || service.place_name,
      service.domain_name,
    ].filter(Boolean).slice(0, mobile ? 2 : 3);
    const actions = renderFleetActionButtons(service);
    const routeState = fleetRouteState(service);
    const proxyDisplay = proxyDisplayForService(service);
    const laneLabel = laneNameForService(service, {
      display_name: service.principal_name,
      slug: service.principal_slug,
    });
    const tone = laneLabel.toLowerCase();
    const mark = fleetMarkForService(service);
    const plateLabel = `${laneLabel} lane`;
    const kindLine = [
      service.kind || 'service',
      service.principal_name,
    ].filter(Boolean).join(' · ');
    return `
      <div class="fleet-card${mobile ? ' fleet-card--mobile' : ''}">
        <div class="fleet-card__header">
          <div class="fleet-card__identity" data-tone="${escapeHtml(tone)}">
            <span class="fleet-card__mark" data-tone="${escapeHtml(tone)}" aria-hidden="true">${escapeHtml(mark)}</span>
            <div class="fleet-card__identity-copy">
              <div class="fleet-card__eyebrow">${escapeHtml(plateLabel)}</div>
              <div class="fleet-card__title">${escapeHtml(service.display_name || service.slug)}</div>
              <div class="fleet-card__kind">${escapeHtml(kindLine)}</div>
            </div>
          </div>
          <span class="status-chip ${escapeHtml(routeState.tone)}">${escapeHtml(routeState.label)}</span>
        </div>
        ${proxyDisplay ? `<div class="fleet-card__shortcut">${escapeHtml(proxyDisplay)}</div>` : ''}
        <div class="fleet-card__meta">
          ${pills.map((pill) => `<span class="fleet-card__pill">${escapeHtml(pill)}</span>`).join('')}
        </div>
        <div class="fleet-card__actions">
          ${actions.join('') || '<span class="fleet-card__hint">Link not configured yet.</span>'}
        </div>
      </div>
    `;
  }

  function renderHomeFleet(payload) {
    const groups = fleetGroupsFromPayload(payload);
    const services = fleetFlattenedServices(groups);
    const total = services.length;

    renderHomePrime(groups);
    renderPrimeInbox(attentionItemsRef.current || [], groups);

    if (homeAgentFleetCount) {
      homeAgentFleetCount.textContent = total ? `${total} routes live` : 'No links';
    }

    if (homeAgentFleetItems) {
      if (!total) {
        homeAgentFleetItems.innerHTML = '<div class="home-agent-fleet__empty">No directory routes have been published in the estate registry yet.</div>';
      } else {
        homeAgentFleetItems.innerHTML = groups.map((principal) => `
          <section class="fleet-group">
            <div class="fleet-group__header">
              <div class="fleet-group__title">${escapeHtml(principal.display_name)}</div>
              <div class="fleet-group__meta">${principal.services.length} routes</div>
            </div>
            <div class="fleet-group__items">
              ${principal.services.map((service) => renderFleetServiceCard(service)).join('')}
            </div>
          </section>
        `).join('');
      }
    }

    if (homeMobileFleetItems) {
      if (!total) {
        homeMobileFleetItems.innerHTML = '<div class="home-mobile-fleet__empty">No directory routes published yet.</div>';
      } else {
        homeMobileFleetItems.innerHTML = services
          .slice(0, 10)
          .map((service) => renderFleetServiceCard(service, { mobile: true }))
          .join('');
      }
    }
  }

  async function loadHomeFleet() {
    if (!homeAgentFleetItems && !homeMobileFleetItems) return;
    try {
      const payload = await fetchJson('/api/v1/estate/overview');
      window.__normanFleetPayload = payload;
      renderHomeFleet(payload);
      renderPrimeOps(window.__normanOpsPayload || null, fleetGroupsFromPayload(payload));
    } catch (err) {
      if (homeAgentFleetCount) {
        homeAgentFleetCount.textContent = 'Unavailable';
      }
      if (homeAgentFleetItems) {
        homeAgentFleetItems.innerHTML = '<div class="home-agent-fleet__empty">Unable to load the current fleet routes.</div>';
      }
      if (homeMobileFleetItems) {
        homeMobileFleetItems.innerHTML = '<div class="home-mobile-fleet__empty">Unable to load the current fleet routes.</div>';
      }
      if (homePrimeActions) {
        homePrimeActions.innerHTML = '<span class="home-prime__placeholder">Unable to load Norman routes right now.</span>';
      }
      if (homePrimeSummary) {
        homePrimeSummary.innerHTML = '<div class="home-prime__placeholder">Norman summary is unavailable right now.</div>';
      }
      if (homePrimeFocus) {
        homePrimeFocus.textContent = 'Norman Prime data is temporarily unavailable';
      }
      if (homePrimeLanes) {
        homePrimeLanes.innerHTML = '<div class="home-prime__placeholder">Unable to load the lane map.</div>';
      }
      if (homePrimeDispatch) {
        homePrimeDispatch.innerHTML = '<div class="home-prime__placeholder">Unable to load dispatch recipes.</div>';
      }
      if (homePrimeDispatchStatus) {
        homePrimeDispatchStatus.textContent = 'Unavailable';
      }
    }
  }

  function setPrimeOpsBusy(busy, label = '') {
    if (homePrimeOpsStatus && label) {
      homePrimeOpsStatus.textContent = label;
    }
    [
      homePrimeOpsRefresh,
      homePrimeOpsUnlockAll,
      homePrimeOpsKillswitch,
      ...Array.from(homePrimeOps?.querySelectorAll('[data-prime-op-action]') || []),
    ].forEach((element) => {
      if (element) {
        element.disabled = Boolean(busy);
      }
    });
  }

  async function loadPrimeOps({ silent = false } = {}) {
    if (!homePrimeOps) return;
    if (document.hidden && silent) return;
    try {
      const payload = await fetchJson('/api/v1/tmux/control/ops');
      window.__normanOpsPayload = payload;
      renderPrimeOps(payload, fleetGroupsFromPayload(window.__normanFleetPayload || {}));
      renderPrimeSummary(attentionItemsRef.current || [], fleetGroupsFromPayload(window.__normanFleetPayload || {}));
    } catch (err) {
      if (!silent) {
        renderPrimeOps(null, fleetGroupsFromPayload(window.__normanFleetPayload || {}));
      }
    }
  }

  async function loadPrimeCredits({ silent = false } = {}) {
    if (!homePrimeCreditsSummary || !homePrimeCreditsItems) return;
    if (document.hidden && silent) return;
    try {
      const payload = await fetchJson('/api/v1/tmux/control/credits');
      window.__normanCreditsPayload = payload;
      renderPrimeCredits(payload);
    } catch (err) {
      if (!silent) {
        renderPrimeCredits(null);
      }
    }
  }

  async function loadPrimeLlmStatus({ silent = false } = {}) {
    if (!homePrimeLlmSummary || !homePrimeLlmItems) return;
    if (document.hidden && silent) return;
    try {
      const payload = await fetchJson('/api/llm/status');
      window.__normanLlmPayload = payload;
      renderPrimeLlmStatus(payload);
    } catch (err) {
      if (!silent) {
        renderPrimeLlmStatus(null);
      }
    }
  }

  async function runPrimeLlmPing() {
    if (!homePrimeLlmSummary || !homePrimeLlmItems) return;
    if (homePrimeLlmPing) {
      homePrimeLlmPing.disabled = true;
      homePrimeLlmPing.textContent = 'Pinging…';
    }
    if (homePrimeLlmStatus) {
      homePrimeLlmStatus.textContent = 'Pinging models…';
    }
    try {
      const payload = await postJson('/api/llm/ping', {});
      window.__normanLlmPingPayload = payload;
      renderPrimeLlmStatus(window.__normanLlmPayload || null);
      if (homePrimeLlmStatus) {
        homePrimeLlmStatus.textContent = `${payload.ok || 0}/${payload.count || 0} ping ok`;
      }
    } catch (err) {
      window.__normanLlmPingPayload = {
        items: [{ name: 'Model ping', status: 'error', error: err.message || 'Ping failed' }],
      };
      renderPrimeLlmStatus(window.__normanLlmPayload || null);
      if (homePrimeLlmStatus) {
        homePrimeLlmStatus.textContent = 'Ping failed';
      }
    } finally {
      if (homePrimeLlmPing) {
        homePrimeLlmPing.disabled = false;
        homePrimeLlmPing.textContent = 'Ping';
      }
    }
  }

  async function loadPrimeAudit({ silent = false } = {}) {
    if (!homePrimeAuditSummary || !homePrimeAudit) return;
    if (document.hidden && silent) return;
    try {
      const payload = await fetchJson('/api/v1/tmux/control/audit?limit=12');
      window.__normanAuditPayload = payload;
      renderPrimeAudit(payload);
    } catch (err) {
      if (!silent) {
        renderPrimeAudit(null);
      }
    }
  }

  async function runPrimeOpAction(action, session) {
    const payload = window.__normanOpsPayload || { items: [] };
    const item = (payload.items || []).find((entry) => entry.session_name === session);
    if (!item) return;
    setPrimeOpsBusy(true, `${item.connector_name || item.session_name}…`);
    try {
      if (action === 'start') {
        await postJson('/api/v1/tmux/control/start', { session });
      } else if (action === 'stop') {
        await postJson('/api/v1/tmux/control/stop', { session });
      } else if (action === 'lock') {
        await postJson('/api/v1/tmux/control/lock', { session, locked: true, stop_session: false });
      } else if (action === 'unlock') {
        await postJson('/api/v1/tmux/control/lock', { session, locked: false });
      } else if (action === 'unwind') {
        if (item.locked) {
          await postJson('/api/v1/tmux/control/lock', { session, locked: false });
        }
        if (String(item.operator_mode || '').toLowerCase() !== 'observe') {
          await postJson('/api/v1/tmux/control/operator', { session, mode: 'observe', note: '' });
        }
      }
      await loadPrimeOps();
      if (homePrimeOpsStatus) {
        homePrimeOpsStatus.textContent = `${item.connector_name || item.session_name} updated`;
      }
    } catch (err) {
      if (homePrimeOpsStatus) {
        homePrimeOpsStatus.textContent = `Action failed for ${item.connector_name || item.session_name}`;
      }
    } finally {
      setPrimeOpsBusy(false);
    }
  }

  async function runPrimeBulkAction(action) {
    if (action === 'killswitch' && !window.confirm('Stop and lock every managed session Norman can control?')) {
      return;
    }
    setPrimeOpsBusy(true, action === 'killswitch' ? 'Stopping and locking managed sessions…' : 'Unlocking managed sessions…');
    try {
      if (action === 'killswitch') {
        await postJson('/api/v1/tmux/control/lock-all', { locked: true, stop_sessions: true });
      } else if (action === 'unlock-all') {
        await postJson('/api/v1/tmux/control/lock-all', { locked: false });
      }
      await loadPrimeOps();
      if (homePrimeOpsStatus) {
        homePrimeOpsStatus.textContent = action === 'killswitch' ? 'Managed sessions stopped + locked' : 'Managed sessions unlocked';
      }
    } catch (err) {
      if (homePrimeOpsStatus) {
        homePrimeOpsStatus.textContent = action === 'killswitch' ? 'Stop + lock failed' : 'Unlock failed';
      }
    } finally {
      setPrimeOpsBusy(false);
    }
  }

  if (homePrimeDispatch) {
    homePrimeDispatch.addEventListener('click', async (event) => {
      const draftButton = event.target.closest('[data-prime-compose-draft]');
      if (draftButton) {
        const prompt = String(draftButton.getAttribute('data-prime-compose-draft') || '');
        if (prompt) {
          seedPrimeNormanDraft(prompt, { force: true, announce: true });
          homePrimeChatInput?.focus({ preventScroll: true });
        }
        return;
      }
      const button = event.target.closest('[data-dispatch-prompt]');
      if (!button) return;
      const prompt = String(button.getAttribute('data-dispatch-prompt') || '');
      if (!prompt) return;
      try {
        await navigator.clipboard.writeText(prompt);
        button.classList.add('is-copied');
        button.textContent = 'Copied';
        if (homePrimeDispatchStatus) {
          homePrimeDispatchStatus.textContent = 'Prompt copied';
        }
        window.setTimeout(() => {
          button.classList.remove('is-copied');
          button.textContent = 'Copy brief';
          if (homePrimeDispatchStatus && homePrimeDispatchStatus.textContent === 'Prompt copied') {
            homePrimeDispatchStatus.textContent = 'Recipes ready';
          }
        }, 1400);
      } catch (err) {
        if (homePrimeDispatchStatus) {
          homePrimeDispatchStatus.textContent = 'Copy failed';
        }
      }
    });
  }

  homePrimeActions?.addEventListener('click', (event) => {
    const button = event.target.closest('[data-prime-jump-compose]');
    if (!button) return;
    event.preventDefault();
    homePrimeChatInput?.focus({ preventScroll: false });
    document.getElementById('home-prime-chat')?.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  });

  if (homePrimeInbox) {
    const selectInboxCard = (target) => {
      const card = target.closest('[data-prime-inbox-id]');
      if (!card) return;
      selectedPrimeInboxId = String(card.getAttribute('data-prime-inbox-id') || '');
      renderPrimeInbox(attentionItemsRef.current || [], fleetGroupsFromPayload(window.__normanFleetPayload || {}));
    };

    homePrimeInbox.addEventListener('click', (event) => {
      selectInboxCard(event.target);
    });

    homePrimeInbox.addEventListener('keydown', (event) => {
      if (event.key !== 'Enter' && event.key !== ' ') return;
      selectInboxCard(event.target);
      event.preventDefault();
    });
  }

  if (homePrimeDeskActions) {
    homePrimeDeskActions.addEventListener('click', async (event) => {
      const draftButton = event.target.closest('[data-prime-compose-draft]');
      if (draftButton) {
        const prompt = String(draftButton.getAttribute('data-prime-compose-draft') || '');
        if (prompt) {
          seedPrimeNormanDraft(prompt, { force: true, announce: true });
          homePrimeChatInput?.focus({ preventScroll: false });
        }
        return;
      }
      const sendButton = event.target.closest('[data-prime-chat-send]');
      if (sendButton) {
        const prompt = String(sendButton.getAttribute('data-prime-chat-send') || '');
        if (!prompt) return;
        try {
          await sendPrimeNormanMessage(prompt);
        } catch (err) {
          if (homePrimeDeskStatus) {
            homePrimeDeskStatus.textContent = err.message || 'Send failed';
          }
        }
        return;
      }
      const button = event.target.closest('[data-prime-prompt]');
      if (!button) return;
      const prompt = String(button.getAttribute('data-prime-prompt') || '');
      if (!prompt) return;
      try {
        await navigator.clipboard.writeText(prompt);
        button.classList.add('is-copied');
        button.textContent = 'Copied';
        if (homePrimeDeskStatus) {
          homePrimeDeskStatus.textContent = 'Prompt copied for Norman';
        }
        window.setTimeout(() => {
          button.classList.remove('is-copied');
          button.textContent = 'Copy brief';
        }, 1400);
      } catch (err) {
        if (homePrimeDeskStatus) {
          homePrimeDeskStatus.textContent = 'Copy failed';
        }
      }
    });
  }

  if (homePrimeChats) {
    const focusPrimeChatCard = (target) => {
      const card = target.closest('[data-prime-chat-session]');
      if (!card) return;
      const session = String(card.getAttribute('data-prime-chat-session') || '');
      const payload = window.__normanOpsPayload || { items: [] };
      const selected = (payload.items || []).find((item) => String(item.session_name || '') === session);
      if (!selected) return;
      syncPrimeOpsToChat(selected);
      renderPrimeOps(payload, fleetGroupsFromPayload(window.__normanFleetPayload || {}));
      const activeCard = homePrimeOps?.querySelector(`[data-prime-session="${CSS.escape(session)}"]`);
      activeCard?.scrollIntoView({ block: 'nearest', inline: 'nearest', behavior: 'smooth' });
    };

    homePrimeChats.addEventListener('click', (event) => {
      const draftButton = event.target.closest('[data-prime-compose-draft]');
      if (draftButton) {
        const prompt = String(draftButton.getAttribute('data-prime-compose-draft') || '');
        if (prompt) {
          seedPrimeNormanDraft(prompt, { force: true, announce: true });
          homePrimeChatInput?.focus({ preventScroll: false });
        }
        return;
      }
      const button = event.target.closest('.btn');
      if (button) return;
      focusPrimeChatCard(event.target);
    });

    homePrimeChats.addEventListener('keydown', (event) => {
      if (event.key !== 'Enter' && event.key !== ' ') return;
      event.preventDefault();
      focusPrimeChatCard(event.target);
    });
  }

  if (homePrimeAudit) {
    const focusPrimeAuditCard = (target) => {
      const card = target.closest('[data-prime-audit-session]');
      if (!card) return;
      const session = String(card.getAttribute('data-prime-audit-session') || '');
      if (!session) return;
      const payload = window.__normanOpsPayload || { items: [] };
      const selected = (payload.items || []).find((item) => String(item.session_name || '') === session);
      if (!selected) return;
      syncPrimeOpsToChat(selected);
      renderPrimeOps(payload, fleetGroupsFromPayload(window.__normanFleetPayload || {}));
      const activeCard = homePrimeOps?.querySelector(`[data-prime-session="${CSS.escape(session)}"]`);
      activeCard?.scrollIntoView({ block: 'nearest', inline: 'nearest', behavior: 'smooth' });
    };

    homePrimeAudit.addEventListener('click', (event) => {
      const draftButton = event.target.closest('[data-prime-compose-draft]');
      if (draftButton) {
        const prompt = String(draftButton.getAttribute('data-prime-compose-draft') || '');
        if (prompt) {
          seedPrimeNormanDraft(prompt, { force: true, announce: true });
          homePrimeChatInput?.focus({ preventScroll: false });
        }
        return;
      }
      const button = event.target.closest('.btn');
      if (button) return;
      focusPrimeAuditCard(event.target);
    });

    homePrimeAudit.addEventListener('keydown', (event) => {
      if (event.key !== 'Enter' && event.key !== ' ') return;
      event.preventDefault();
      focusPrimeAuditCard(event.target);
    });
  }

  homePrimeLlmPing?.addEventListener('click', () => {
    runPrimeLlmPing();
  });

  homePrimeOpsRefresh?.addEventListener('click', () => {
    loadPrimeOps();
  });

  homePrimeOpsUnlockAll?.addEventListener('click', () => {
    runPrimeBulkAction('unlock-all');
  });

  homePrimeOpsKillswitch?.addEventListener('click', () => {
    runPrimeBulkAction('killswitch');
  });

  homePrimeOps?.addEventListener('click', (event) => {
    const laneButton = event.target.closest('[data-prime-ops-lane]');
    if (laneButton) {
      selectedPrimeOpsLane = String(laneButton.getAttribute('data-prime-ops-lane') || 'All');
      renderPrimeOps(window.__normanOpsPayload || null, fleetGroupsFromPayload(window.__normanFleetPayload || {}));
      return;
    }
    const modeButton = event.target.closest('[data-prime-ops-mode]');
    if (modeButton) {
      selectedPrimeOpsMode = String(modeButton.getAttribute('data-prime-ops-mode') || 'all');
      renderPrimeOps(window.__normanOpsPayload || null, fleetGroupsFromPayload(window.__normanFleetPayload || {}));
      return;
    }
    const draftButton = event.target.closest('[data-prime-compose-draft]');
    if (draftButton) {
      const prompt = String(draftButton.getAttribute('data-prime-compose-draft') || '');
      if (prompt) {
        seedPrimeNormanDraft(prompt, { force: true, announce: true });
        homePrimeChatInput?.focus({ preventScroll: false });
      }
      return;
    }
    const button = event.target.closest('[data-prime-op-action]');
    if (!button) return;
    const action = String(button.getAttribute('data-prime-op-action') || '');
    const session = String(button.getAttribute('data-prime-session') || '');
    if (!action || !session) return;
    runPrimeOpAction(action, session);
  });

  homePrimeChatInput?.addEventListener('input', () => {
    const current = String(homePrimeChatInput.value || '').trim();
    primeNormanDraftDirty = Boolean(current) && current !== String(primeNormanSuggestedPrompt || '').trim();
    syncPrimeNormanComposerState();
  });

  homePrimeChatInput?.addEventListener('keydown', (event) => {
    const isEnter = event.key === 'Enter' || event.key === 'NumpadEnter';
    if (!isEnter) return;
    if (event.shiftKey || event.altKey || event.ctrlKey || event.metaKey || event.isComposing) {
      return;
    }
    event.preventDefault();
    const prompt = String(homePrimeChatInput?.value || '').trim();
    if (!prompt || primeNormanSendInFlight) return;
    if (typeof homePrimeChatForm?.requestSubmit === 'function') {
      homePrimeChatForm.requestSubmit();
      return;
    }
    homePrimeChatSend?.click();
  });

  homePrimeChatLoad?.addEventListener('click', () => {
    if (!primeNormanSuggestedPrompt) return;
    seedPrimeNormanDraft(primeNormanSuggestedPrompt, { force: true, announce: true });
    homePrimeChatInput?.focus({ preventScroll: false });
  });

  homePrimeChatForm?.addEventListener('submit', async (event) => {
    event.preventDefault();
    const prompt = String(homePrimeChatInput?.value || '').trim();
    if (!prompt || primeNormanSendInFlight) return;
    try {
      await sendPrimeNormanMessage(prompt);
      homePrimeChatInput?.focus({ preventScroll: false });
    } catch (err) {
      if (homePrimeDeskStatus) {
        homePrimeDeskStatus.textContent = err.message || 'Send failed';
      }
    }
  });

  const FLOW_BASE_WIDTH = 1600;
  const FLOW_BASE_HEIGHT = 900;

  function layoutFlowNodes(aspect, opts = {}) {
    const baseWidth = FLOW_BASE_WIDTH;
    const baseHeight = FLOW_BASE_HEIGHT;

    // Portrait wants a top-to-bottom flow; landscape is left-to-right.
    const mode = aspect < 1.05 ? 'portrait' : 'landscape';
    const wantsWidePortrait = Boolean(opts.forceWidePortrait);
    const portraitVariant = aspect < 0.72 && !wantsWidePortrait ? 'portrait-narrow' : 'portrait-wide';
    // Variant selection is how we maximize readability: we morph the composition so the
    // camera viewBox can zoom in without cropping on any aspect ratio.
    let landscapeVariant = 'landscape-tall';
    if (aspect >= 2.6) {
      landscapeVariant = 'landscape-ultrawide';
    } else if (aspect >= 1.9) {
      landscapeVariant = 'landscape-wide';
    }
    if (flowMap) {
      flowMap.dataset.layout = mode === 'portrait' ? portraitVariant : landscapeVariant;
    }

    // Tile base bounding boxes (matching the SVG hit rectangles).
    const channelsBase = { x: 40, y: 138, w: 400, h: 196 };
    const botsBase = { x: 40, y: 330, w: 400, h: 196 };
    const filtersBase = { x: 520, y: 228, w: 460, h: 238 };
    const actionsBase = { x: 1020, y: 244, w: 360, h: 200 };

    let txChannels = 0;
    let tyChannels = 0;
    let txBots = 0;
    let tyBots = 0;
    let txFilters = 0;
    let tyFilters = 0;
    let txActions = 0;
    let tyActions = 0;

    if (mode === 'portrait') {
      const topY = 66;

      if (portraitVariant === 'portrait-narrow') {
        // Single-column layout reduces overall content width so the camera viewBox can fill tall screens.
        const totalH = channelsBase.h + botsBase.h + filtersBase.h + actionsBase.h;
        // Make the layout "tall enough" for very skinny panels: otherwise the camera must
        // expand the viewBox height to satisfy aspect ratio, creating empty vertical bands.
        const pad = cameraPadForAspect(aspect);
        const maxW = Math.max(channelsBase.w, botsBase.w, filtersBase.w, actionsBase.w);
        const vbW = maxW + pad * 2;
        const vbH = vbW / Math.max(0.2, aspect);
        const desiredContentH = vbH - pad * 2;
        const gapY = clamp((desiredContentH - totalH) / 3, 18, 360);

        const xChannels = (baseWidth - channelsBase.w) / 2;
        const xBots = (baseWidth - botsBase.w) / 2;
        const xFilters = (baseWidth - filtersBase.w) / 2;
        const xActions = (baseWidth - actionsBase.w) / 2;

        const yChannels = topY;
        const yBots = yChannels + channelsBase.h + gapY;
        const yFilters = yBots + botsBase.h + gapY;
        const yActions = yFilters + filtersBase.h + gapY;

        txChannels = xChannels - channelsBase.x;
        tyChannels = yChannels - channelsBase.y;
        txBots = xBots - botsBase.x;
        tyBots = yBots - botsBase.y;
        txFilters = xFilters - filtersBase.x;
        tyFilters = yFilters - filtersBase.y;
        txActions = xActions - actionsBase.x;
        tyActions = yActions - actionsBase.y;
      } else {
        // Two-up top row keeps the "fork" feeling when there's enough width.
        const t = clamp((aspect - 0.75) / (1.05 - 0.75), 0, 1);
        const marginX = lerp(220, 84, t);

        txChannels = marginX - channelsBase.x;
        tyChannels = topY - channelsBase.y;

        const botsLeft = baseWidth - marginX - botsBase.w;
        txBots = botsLeft - botsBase.x;
        tyBots = topY - botsBase.y;

        const row1Bottom = topY + channelsBase.h;
        const available = baseHeight - row1Bottom - 42;
        const gapY = clamp((available - filtersBase.h - actionsBase.h) / 2, 34, 82);
        const filtersTop = row1Bottom + gapY;
        const actionsTop = filtersTop + filtersBase.h + gapY;

        const filtersLeft = (baseWidth - filtersBase.w) / 2;
        txFilters = filtersLeft - filtersBase.x;
        tyFilters = filtersTop - filtersBase.y;

        const actionsLeft = (baseWidth - actionsBase.w) / 2;
        txActions = actionsLeft - actionsBase.x;
        tyActions = actionsTop - actionsBase.y;
      }
    } else {
      // Landscape: push tiles outward to fill width without leaving the viewBox.
      // Interpolate the spread based on aspect ratio to avoid overlap on tighter screens.
      const t = clamp((aspect - 1.05) / (1.95 - 1.05), 0, 1);
      txChannels = lerp(0, -18, t);
      txBots = lerp(0, -18, t);
      txFilters = lerp(50, 150, t);

      // Use more vertical space as panels get wider to reduce letterboxing and increase readability.
      // But on ultrawide, too much vertical spread forces the camera to expand the viewBox width massively.
      let v = lerp(0, 240, clamp((aspect - 1.15) / (2.6 - 1.15), 0, 1));
      if (landscapeVariant === 'landscape-ultrawide') {
        v = Math.min(v, 90);
      } else if (landscapeVariant === 'landscape-wide') {
        v = Math.min(v, 160);
      }
      tyChannels = -v * 0.55;
      tyBots = v * 0.55;
      tyFilters = -v * 0.08;

      if (landscapeVariant === 'landscape-tall') {
        // When the panel is wide-but-tall, stacking Actions underneath makes the bbox less "ultra-wide",
        // which increases the effective zoom and reduces the empty bottom band.
        txActions = txFilters + 30;
        tyActions = 240 + v * 0.12;
      } else if (landscapeVariant === 'landscape-ultrawide') {
        // Spend width aggressively to match the panel aspect ratio and increase effective zoom.
        const tUltra = clamp((aspect - 2.6) / (4.0 - 2.6), 0, 1);
        txFilters = lerp(160, 300, tUltra);
        txActions = lerp(420, 740, tUltra);
        // Keep Actions aligned with Filters for a clean, straight delivery track.
        tyActions = tyFilters;
      } else {
        const tWide = clamp((aspect - 1.9) / (2.6 - 1.9), 0, 1);
        txActions = lerp(160, 380, tWide);
        // Keep Actions aligned with Filters for a straight, readable horizontal delivery track.
        tyActions = tyFilters;
      }
    }

    setTranslate(tileChannels, txChannels, tyChannels);
    setTranslate(tileBots, txBots, tyBots);
    setTranslate(tileFilters, txFilters, tyFilters);
    setTranslate(tileActions, txActions, tyActions);

    const channels = tileBox(channelsBase.x, channelsBase.y, channelsBase.w, channelsBase.h, txChannels, tyChannels);
    const bots = tileBox(botsBase.x, botsBase.y, botsBase.w, botsBase.h, txBots, tyBots);
    const filters = tileBox(filtersBase.x, filtersBase.y, filtersBase.w, filtersBase.h, txFilters, tyFilters);
    const actions = tileBox(actionsBase.x, actionsBase.y, actionsBase.w, actionsBase.h, txActions, tyActions);

    if (mode === 'portrait') {
      const j1 = (Math.max(channels.b, bots.b) + filters.t) / 2;
      const j2 = (filters.b + actions.t) / 2;
      const endXChannels = portraitVariant === 'portrait-narrow' ? filters.cx - 52 : filters.cx;
      const endXBots = portraitVariant === 'portrait-narrow' ? filters.cx + 52 : filters.cx;

      if (lineChannels) {
        const startX = channels.cx;
        const startY = channels.b - 6;
        const endY = filters.t + 6;
        lineChannels.setAttribute('d', `M${startX.toFixed(2)} ${startY.toFixed(2)} L${startX.toFixed(2)} ${j1.toFixed(2)} L${endXChannels.toFixed(2)} ${j1.toFixed(2)} L${endXChannels.toFixed(2)} ${endY.toFixed(2)}`);
      }
      if (lineBots) {
        const startX = bots.cx;
        const startY = bots.b - 6;
        const endY = filters.t + 6;
        lineBots.setAttribute('d', `M${startX.toFixed(2)} ${startY.toFixed(2)} L${startX.toFixed(2)} ${j1.toFixed(2)} L${endXBots.toFixed(2)} ${j1.toFixed(2)} L${endXBots.toFixed(2)} ${endY.toFixed(2)}`);
      }
      if (lineActions) {
        const startX = filters.cx;
        const startY = filters.b - 6;
        const endX = actions.cx;
        const endY = actions.t + 6;
        lineActions.setAttribute('d', `M${startX.toFixed(2)} ${startY.toFixed(2)} L${startX.toFixed(2)} ${j2.toFixed(2)} L${endX.toFixed(2)} ${j2.toFixed(2)} L${endX.toFixed(2)} ${endY.toFixed(2)}`);
      }

      setCheck(checkChannels, checkChannelsMark, portraitVariant === 'portrait-narrow' ? endXChannels : channels.cx, j1);
      setCheck(checkBots, checkBotsMark, portraitVariant === 'portrait-narrow' ? endXBots : bots.cx, j1);
      setCheck(checkActions, checkActionsMark, portraitVariant === 'portrait-narrow' ? filters.cx : actions.cx, j2);

      // Drops ride the tracks, not fixed coordinates.
      const dripChX = channels.cx;
      const dripChY = (channels.b + j1) / 2;
      const dripBotX = bots.cx;
      const dripBotY = (bots.b + j1) / 2;
      const dripActX = filters.cx;
      const dripActY = (filters.b + j2) / 2;
      setDrip(dripChannels, dripChX, dripChY);
      setDrip(dripBots, dripBotX, dripBotY);
      setDrip(dripActions, dripActX, dripActY);

      const points = [];
      pushBox(points, channels);
      pushBox(points, bots);
      pushBox(points, filters);
      pushBox(points, actions);
      // Track elbows/endpoints and checks/drops.
      points.push(channels.cx, channels.b - 6);
      points.push(channels.cx, j1);
      points.push(endXChannels, j1);
      points.push(endXChannels, filters.t + 6);
      points.push(bots.cx, bots.b - 6);
      points.push(bots.cx, j1);
      points.push(endXBots, j1);
      points.push(endXBots, filters.t + 6);
      points.push(filters.cx, filters.b - 6);
      points.push(filters.cx, j2);
      points.push(actions.cx, j2);
      points.push(actions.cx, actions.t + 6);
      points.push(driftSafeNumber(dripChX), driftSafeNumber(dripChY));
      points.push(driftSafeNumber(dripBotX), driftSafeNumber(dripBotY));
      points.push(driftSafeNumber(dripActX), driftSafeNumber(dripActY));
      points.push(endXChannels, j1);
      points.push(endXBots, j1);
      points.push(filters.cx, j2);
      return boundsFromPoints(points);
    }

    // Landscape junctions, anchored relative to the filter tile (keeps the "tracks junction" stable).
    const junctionX = (channels.r + filters.l) / 2;
    const endX = filters.l + 20;
    const chElbowY = filters.t + 82;
    const botElbowY = filters.t + 142;
    const actionStraightStartX = filters.r - 20;
    const actionStraightStartY = filters.cy;
    const actionStraightEndX = actions.l + 20;
    const actionStraightEndY = actions.cy;

    if (lineChannels) {
      const startX = channels.r - 16;
      const startY = channels.cy;
      lineChannels.setAttribute('d', `M${startX.toFixed(2)} ${startY.toFixed(2)} L${junctionX.toFixed(2)} ${startY.toFixed(2)} L${junctionX.toFixed(2)} ${chElbowY.toFixed(2)} L${endX.toFixed(2)} ${chElbowY.toFixed(2)}`);
    }
    if (lineBots) {
      const startX = bots.r - 16;
      const startY = bots.cy;
      lineBots.setAttribute('d', `M${startX.toFixed(2)} ${startY.toFixed(2)} L${junctionX.toFixed(2)} ${startY.toFixed(2)} L${junctionX.toFixed(2)} ${botElbowY.toFixed(2)} L${endX.toFixed(2)} ${botElbowY.toFixed(2)}`);
    }
    if (lineActions) {
      if (landscapeVariant === 'landscape-tall') {
        const startX = filters.cx;
        const startY = filters.b - 8;
        const endX2 = actions.cx;
        const endY2 = actions.t + 8;
        const midY = (startY + endY2) / 2;
        lineActions.setAttribute('d', `M${startX.toFixed(2)} ${startY.toFixed(2)} L${startX.toFixed(2)} ${midY.toFixed(2)} L${endX2.toFixed(2)} ${midY.toFixed(2)} L${endX2.toFixed(2)} ${endY2.toFixed(2)}`);
      } else {
        const startX = filters.r - 20;
        const startY = filters.cy;
        const endAX = actions.l + 20;
        const endAY = actions.cy;
        lineActions.setAttribute('d', `M${startX.toFixed(2)} ${startY.toFixed(2)} L${endAX.toFixed(2)} ${endAY.toFixed(2)}`);
      }
    }

    setCheck(checkChannels, checkChannelsMark, junctionX, chElbowY);
    setCheck(checkBots, checkBotsMark, junctionX, botElbowY);
    if (landscapeVariant === 'landscape-tall') {
      setCheck(checkActions, checkActionsMark, filters.cx, (filters.b + actions.t) / 2);
    } else {
      const actionMidX = ((filters.r - 20) + (actions.l + 20)) / 2;
      setCheck(checkActions, checkActionsMark, actionMidX, filters.cy);
    }

    // Drops: one per ingress lane, one on delivery.
    const dripChX = (channels.r + junctionX) / 2;
    const dripChY = channels.cy;
    const dripBotX = (bots.r + junctionX) / 2;
    const dripBotY = bots.cy;
    setDrip(dripChannels, dripChX, dripChY);
    setDrip(dripBots, dripBotX, dripBotY);
    if (landscapeVariant === 'landscape-tall') {
      setDrip(dripActions, filters.cx, (filters.b + actions.t) / 2);
    } else {
      setDrip(dripActions, (filters.r + actions.l) / 2, filters.cy);
    }

    const points = [];
    pushBox(points, channels);
    pushBox(points, bots);
    pushBox(points, filters);
    pushBox(points, actions);
    // Ingress lanes.
    points.push(channels.r - 16, channels.cy);
    points.push(junctionX, channels.cy);
    points.push(junctionX, chElbowY);
    points.push(endX, chElbowY);
    points.push(bots.r - 16, bots.cy);
    points.push(junctionX, bots.cy);
    points.push(junctionX, botElbowY);
    points.push(endX, botElbowY);
    // Delivery lane.
    if (landscapeVariant === 'landscape-tall') {
      const startX = filters.cx;
      const startY = filters.b - 8;
      const endX2 = actions.cx;
      const endY2 = actions.t + 8;
      const midY = (startY + endY2) / 2;
      points.push(startX, startY);
      points.push(startX, midY);
      points.push(endX2, midY);
      points.push(endX2, endY2);
    } else {
      points.push(actionStraightStartX, actionStraightStartY);
      points.push(actionStraightEndX, actionStraightEndY);
    }
    // Drops.
    points.push(dripChX, dripChY);
    points.push(dripBotX, dripBotY);
    if (landscapeVariant === 'landscape-tall') {
      points.push(filters.cx, (filters.b + actions.t) / 2);
    } else {
      points.push((filters.r + actions.l) / 2, filters.cy);
    }
    return boundsFromPoints(points);
  }

  function fitFlowLayout() {
    if (!flowSvg || !flowLayout) return;
    const width = flowSvg.clientWidth;
    const height = flowSvg.clientHeight;
    if (!width || !height) return;
    const baseWidth = FLOW_BASE_WIDTH;
    const baseHeight = FLOW_BASE_HEIGHT;
    const isRotated = flowMap && flowMap.classList.contains('is-rotated');
    const layoutWidth = isRotated ? height : width;
    const layoutHeight = isRotated ? width : height;
    const aspect = layoutWidth / layoutHeight;
    flowLayout.setAttribute('transform', 'translate(0 0) scale(1)');

    // Layout in base coordinates, then set a viewBox that "cameras" the content and matches
    // the panel aspect ratio. This avoids letterboxing on extreme aspect ratios.
    // In rotate mode on landscape panels, we still want the "fork" (channels/bots spread)
    // instead of collapsing to the single-column portrait-narrow layout.
    const forceWidePortrait = Boolean(isRotated && width / height > 1.2);
    const bounds = layoutFlowNodes(aspect, { forceWidePortrait });
    if (!bounds) return;

    const bboxW = bounds.maxX - bounds.minX;
    const bboxH = bounds.maxY - bounds.minY;
    if (!(bboxW > 0) || !(bboxH > 0)) return;

    const pad = aspect >= 2.6 ? 12 : cameraPadForAspect(aspect);
    const contentW = bboxW + pad * 2;
    const contentH = bboxH + pad * 2;

    // Camera strategy:
    // - Moderate aspect ratios: expand viewBox to match panel aspect ratio (less letterboxing).
    // - Extreme aspect ratios: keep viewBox tight to content to maximize readability.
    const aspectMatch = aspect >= 0.8 && aspect <= 2.2;
    let vbW = contentW;
    let vbH = contentH;
    if (aspectMatch) {
      vbH = vbW / aspect;
      if (vbH < contentH) {
        vbH = contentH;
        vbW = vbH * aspect;
      }
    }

    // NOTE: We intentionally avoid "extra zoom" multipliers here because they can crop content
    // on near-square panels. The layout variants should reduce bbox width/height instead.

    const cx = (bounds.minX + bounds.maxX) / 2;
    const cy = (bounds.minY + bounds.maxY) / 2;
    const vbX = cx - vbW / 2;
    const vbY = cy - vbH / 2;

    flowSvg.setAttribute('viewBox', `${vbX.toFixed(2)} ${vbY.toFixed(2)} ${vbW.toFixed(2)} ${vbH.toFixed(2)}`);

    // Debug hook for quick sanity checks from DevTools.
    window.__norman_flow = {
      aspect,
      layout: flowMap?.dataset?.layout || null,
      bounds,
      viewBox: { x: vbX, y: vbY, w: vbW, h: vbH },
      aspectMatch,
    };
  }

  function scheduleFlowFit() {
    window.requestAnimationFrame(fitFlowLayout);
  }

  flowLinks.forEach(link => {
    const key = link.dataset.flow;
    if (!key) return;
    const lineClass = `.flow-line-${key}`;
    link.addEventListener('mouseenter', () => {
      document.querySelectorAll(lineClass).forEach(line => line.classList.add('highlight'));
    });
    link.addEventListener('mouseleave', () => {
      document.querySelectorAll(lineClass).forEach(line => line.classList.remove('highlight'));
    });
  });

  scheduleFlowFit();
  updateFlowViewportSizing();
  window.addEventListener('resize', () => {
    clearTimeout(window.__flowFitTimer);
    updateFlowViewportSizing();
    window.__flowFitTimer = setTimeout(scheduleFlowFit, 120);
  });
  if (window.visualViewport) {
    window.visualViewport.addEventListener('resize', () => {
      updateFlowViewportSizing();
      scheduleFlowFit();
    });
    window.visualViewport.addEventListener('scroll', updateFlowViewportSizing);
  }

  assistantChips.forEach(chip => {
    chip.addEventListener('click', () => {
      assistantChips.forEach(btn => btn.classList.remove('is-active'));
      chip.classList.add('is-active');
    });
  });

  // Touch devices: the ops assistant is a collapsed overlay; tap the header to expand.
  const flowAssistant = document.querySelector('.flow-assistant');
  const flowAssistantHeader = flowAssistant?.querySelector('.flow-assistant__header');
  const isTouch = window.matchMedia && window.matchMedia('(hover: none) and (pointer: coarse)').matches;
  if (isTouch && flowAssistant && flowAssistantHeader) {
    flowAssistantHeader.setAttribute('role', 'button');
    flowAssistantHeader.setAttribute('tabindex', '0');
    flowAssistantHeader.setAttribute('aria-expanded', 'false');

    const setOpen = (open) => {
      flowAssistant.classList.toggle('is-open', open);
      flowAssistantHeader.setAttribute('aria-expanded', open ? 'true' : 'false');
    };

    const toggleOpen = () => setOpen(!flowAssistant.classList.contains('is-open'));

    flowAssistantHeader.addEventListener('click', (event) => {
      event.preventDefault();
      toggleOpen();
    });

    flowAssistantHeader.addEventListener('keydown', (event) => {
      if (event.key === 'Enter' || event.key === ' ') {
        event.preventDefault();
        toggleOpen();
      } else if (event.key === 'Escape') {
        setOpen(false);
      }
    });

    document.addEventListener('click', (event) => {
      if (!flowAssistant.classList.contains('is-open')) return;
      if (flowAssistant.contains(event.target)) return;
      setOpen(false);
    });
  }

  if (infoToggle && infoPanel) {
    infoToggle.addEventListener('click', () => {
      infoPanel.classList.toggle('show');
    });
  }

  if (flowMap) {
    flowMap.classList.add('breathing');
  }

  if (breatheToggle && flowMap) {
    breatheToggle.addEventListener('click', () => {
      const isOn = flowMap.classList.toggle('breathing');
      breatheToggle.textContent = isOn ? 'Pause Breathing' : 'Resume Breathing';
    });
  }

  if (rotateToggle && flowMap) {
    rotateToggle.addEventListener('click', () => {
      const isRotated = flowMap.classList.toggle('is-rotated');
      rotateToggle.textContent = isRotated ? 'Reset View' : 'Rotate View';
      scheduleFlowFit();
    });
  }

  if (flowControls.messages) flowControls.messages.addEventListener('click', () => window.location.href = '/editor.html');
  if (flowControls.channels) flowControls.channels.addEventListener('click', () => window.location.href = '/channels.html');
  if (flowControls.filters) flowControls.filters.addEventListener('click', () => window.location.href = '/filters.html');
  if (flowControls.bots) flowControls.bots.addEventListener('click', () => window.location.href = '/editor.html');
  if (flowControls.actions) flowControls.actions.addEventListener('click', () => window.location.href = '/actions.html');
  if (flowControls.connectors) flowControls.connectors.addEventListener('click', () => window.location.href = '/connectors.html');

  let lastSignalTs = null;
  let lastActionTs = null;
  let lastPulseAt = 0;

  function formatAge(timestamp) {
    if (!timestamp) return null;
    const then = new Date(timestamp);
    if (Number.isNaN(then.getTime())) return null;
    const seconds = Math.max(0, Math.floor((Date.now() - then.getTime()) / 1000));
    if (seconds < 60) return `${seconds}s ago`;
    const minutes = Math.floor(seconds / 60);
    if (minutes < 60) return `${minutes}m ago`;
    const hours = Math.floor(minutes / 60);
    return `${hours}h ago`;
  }

  function ageClass(seconds) {
    if (seconds === null) return 'idle';
    if (seconds < 60) return 'ok';
    if (seconds < 300) return 'warn';
    return 'danger';
  }

  function formatExpiryAge(epochSeconds) {
    if (!Number.isFinite(epochSeconds)) return null;
    const delta = Math.floor(epochSeconds - (Date.now() / 1000));
    if (delta <= 0) return 'expired';
    if (delta < 3600) return `${Math.floor(delta / 60)}m`;
    if (delta < 86400) return `${Math.floor(delta / 3600)}h`;
    return `${Math.floor(delta / 86400)}d`;
  }

  function isPresentValue(value) {
    if (value === null || value === undefined) return false;
    if (typeof value === 'string') return value.trim() !== '';
    if (Array.isArray(value)) return value.length > 0;
    return true;
  }

  function detectConnectorMode(connectorType, config = {}) {
    const has = (key) => isPresentValue(config?.[key]);
    if (connectorType === 'discord') {
      if (has('webhook_url')) return 'webhook';
      if (has('token') || has('channel_id')) return 'bot';
      return 'webhook';
    }
    if (connectorType === 'teams') {
      if (has('webhook_url')) return 'webhook';
      if (has('app_id') || has('app_password') || has('tenant_id') || has('bot_endpoint')) return 'bot';
      return 'webhook';
    }
    return null;
  }

  function getRequiredFieldsForConnector(connectorType, config = {}, availableRow = null) {
    const fields = availableRow?.fields || [];
    const defaults = availableRow?.defaults || {};
    const required = fields.filter((field) => !Object.prototype.hasOwnProperty.call(defaults, field));
    const mode = detectConnectorMode(connectorType, config);
    if (connectorType === 'discord') {
      return mode === 'webhook' ? ['webhook_url'] : ['token', 'channel_id'];
    }
    if (connectorType === 'teams') {
      return mode === 'webhook'
        ? ['webhook_url']
        : ['app_id', 'app_password', 'tenant_id', 'bot_endpoint'];
    }
    if (connectorType === 'signal') {
      return required.length ? required : ['service_url', 'phone_number'];
    }
    return required;
  }

  function getMissingRequiredFields(connectorType, config = {}, availableRow = null) {
    const required = getRequiredFieldsForConnector(connectorType, config, availableRow);
    return (required || []).filter((field) => !isPresentValue(config?.[field]));
  }

  function readAttentionState() {
    try {
      const raw = localStorage.getItem(ATTENTION_STATE_KEY);
      if (!raw) return {};
      const parsed = JSON.parse(raw);
      return parsed && typeof parsed === 'object' ? parsed : {};
    } catch (err) {
      return {};
    }
  }

  function writeAttentionState(state) {
    try {
      localStorage.setItem(ATTENTION_STATE_KEY, JSON.stringify(state || {}));
    } catch (err) {
      // noop
    }
  }

  function getSuppressionState(itemId, state) {
    const entry = state[itemId];
    if (!entry) return { suppressed: false, kind: 'none', until: null };
    if (entry.acked === true) return { suppressed: true, kind: 'acked', until: null };
    if (Number.isFinite(entry.snooze_until) && entry.snooze_until > Date.now()) {
      return { suppressed: true, kind: 'snoozed', until: entry.snooze_until };
    }
    return { suppressed: false, kind: 'none', until: null };
  }

  function issueId(kind, payload) {
    return `${kind}:${payload}`;
  }

  function formatSnoozeRemaining(untilMs) {
    if (!Number.isFinite(untilMs)) return '';
    const deltaMs = Math.max(0, untilMs - Date.now());
    const mins = Math.ceil(deltaMs / 60000);
    return `${mins}m`;
  }

  function buildAttentionItems({ connectors, available, events, rules, jobs }) {
    const items = [];
    const availableByType = new Map((available || []).map((row) => [row.id, row]));

    if (!connectors || connectors.length === 0) {
      items.push({
        id: issueId('connectors', 'none'),
        level: 'warn',
        title: 'No connectors configured',
        detail: 'Add at least one connector so channels can ingest real traffic.',
        actionHref: '/connectors.html',
        actionLabel: 'Open Connectors',
        ts: Date.now(),
        evidence: {
          category: 'connectors',
          connector_count: 0,
          recommendation: 'Create at least one inbound connector.',
        },
      });
    }

    if (!rules || rules.length === 0) {
      items.push({
        id: issueId('rules', 'none'),
        level: 'warn',
        title: 'No routing rules',
        detail: 'Messages will fall back to default bot behavior.',
        actionHref: '/connectors.html#routing-rules-panel',
        actionLabel: 'Add Rule',
        ts: Date.now(),
        evidence: {
          category: 'routing',
          active_rules: 0,
          behavior: 'fallback_bot_only',
        },
      });
    }

    (connectors || []).forEach((connector) => {
      const availableRow = availableByType.get(connector.connector_type) || null;
      const missing = getMissingRequiredFields(
        connector.connector_type,
        connector.config || {},
        availableRow,
      );
      if (missing.length) {
        items.push({
          id: issueId('connector-missing', connector.id || connector.connector_type),
          level: 'warn',
          title: `${connector.name}: setup incomplete`,
          detail: `Missing ${missing.slice(0, 3).join(', ')}${missing.length > 3 ? '...' : ''}`,
          actionHref: '/connectors.html',
          actionLabel: 'Fix Connector',
          ts: Date.now(),
          evidence: {
            connector_id: connector.id || null,
            connector_name: connector.name,
            connector_type: connector.connector_type,
            missing_fields: missing,
          },
        });
      }

      const expiresAt = Number.parseInt(connector?.config?.oauth_expires_at || 0, 10);
      if (Number.isFinite(expiresAt) && expiresAt > 0) {
        const remaining = expiresAt - (Date.now() / 1000);
        if (remaining <= 0) {
          items.push({
            id: issueId('oauth-expired', connector.id || connector.connector_type),
            level: 'danger',
            title: `${connector.name}: SSO token expired`,
            detail: 'Reconnect this connector now.',
            actionHref: '/connectors.html',
            actionLabel: 'Reconnect',
            ts: Date.now(),
            evidence: {
              connector_id: connector.id || null,
              connector_name: connector.name,
              connector_type: connector.connector_type,
              oauth_provider: connector?.config?.oauth_provider || null,
              oauth_expires_at: expiresAt,
            },
          });
        } else if (remaining <= 24 * 3600) {
          items.push({
            id: issueId('oauth-expiring', connector.id || connector.connector_type),
            level: 'warn',
            title: `${connector.name}: SSO expires soon`,
            detail: `Token expires in ${formatExpiryAge(expiresAt)}.`,
            actionHref: '/connectors.html',
            actionLabel: 'Review Auth',
            ts: Date.now(),
            evidence: {
              connector_id: connector.id || null,
              connector_name: connector.name,
              connector_type: connector.connector_type,
              oauth_provider: connector?.config?.oauth_provider || null,
              oauth_expires_at: expiresAt,
              expires_in: formatExpiryAge(expiresAt),
            },
          });
        }
      }
    });

    const deadJobs = (jobs || []).filter((job) => job.status === 'dead');
    deadJobs.slice(0, 2).forEach((job) => {
      items.push({
        id: issueId('routing-job', job.id),
        level: 'danger',
        title: `Routing job ${job.id} dead-lettered`,
        detail: job.event_delivery_error || job.last_error || 'Retry budget exhausted',
        actionHref: '/connectors.html#routing-jobs-panel',
        actionLabel: 'Open Queue',
        ts: job.updated_at ? new Date(job.updated_at).getTime() : Date.now(),
        evidence: {
          job_id: job.id,
          event_id: job.event_id || null,
          status: job.status,
          attempts: job.attempts,
          max_attempts: job.max_attempts,
          last_error: job.last_error || null,
          event_status: job.event_status || null,
          event_delivery_status: job.event_delivery_status || null,
          event_delivery_error: job.event_delivery_error || null,
          next_attempt_at: job.next_attempt_at || null,
        },
      });
    });

    const queuedJobs = (jobs || []).filter((job) => job.status === 'pending' || job.status === 'processing');
    if (queuedJobs.length >= 5) {
      items.push({
        id: issueId('routing-backlog', queuedJobs.length),
        level: 'warn',
        title: 'Routing queue backing up',
        detail: `${queuedJobs.length} jobs are waiting for delivery or retry.`,
        actionHref: '/connectors.html#routing-jobs-panel',
        actionLabel: 'Inspect Queue',
        ts: Date.now(),
        evidence: {
          queued_jobs: queuedJobs.length,
          processing_jobs: queuedJobs.filter((job) => job.status === 'processing').length,
          pending_jobs: queuedJobs.filter((job) => job.status === 'pending').length,
        },
      });
    }

    const deadEventIds = new Set(deadJobs.map((job) => job.event_id).filter(Boolean));
    (events || [])
      .filter((evt) => (
        evt.delivery_status === 'failed'
        || evt.status === 'failed'
        || evt.status === 'dead_letter'
      ) && !deadEventIds.has(evt.id))
      .slice(0, 3)
      .forEach((evt) => {
        items.push({
          id: issueId('routing-event', evt.id),
          level: 'danger',
          title: `Routing event ${evt.id} failed`,
          detail: evt.delivery_error || evt.error || 'Delivery or processing error',
          actionHref: '/connectors.html#routing-events-panel',
          actionLabel: 'Open Events',
          ts: evt.created_at ? new Date(evt.created_at).getTime() : Date.now(),
          evidence: {
            event_id: evt.id,
            connector_id: evt.connector_id || null,
            connector_type: evt.connector_type || null,
            bot_id: evt.bot_id || null,
            rule_id: evt.rule_id || null,
            status: evt.status,
            delivery_status: evt.delivery_status,
            error: evt.error || null,
            delivery_error: evt.delivery_error || null,
            created_at: evt.created_at || null,
          },
        });
      });

    return items.slice(0, 6);
  }

  function renderAttentionRail(items) {
    if (!attentionRail || !attentionRailItems || !attentionRailCount) return;
    if (!items.length) {
      attentionRailCount.textContent = '0 active';
      attentionRailItems.innerHTML = '<div class="attention-rail__empty">No incidents detected.</div>';
      return;
    }
    attentionRailCount.textContent = `${items.length} active`;
    attentionRailItems.innerHTML = items
      .map((item) => `
        <div class="attention-rail__item ${escapeHtml(item.level)}">
          <div class="attention-rail__item-title">${escapeHtml(item.title)}</div>
          <div class="attention-rail__item-detail">${escapeHtml(item.detail)}</div>
          <a class="btn btn-sm btn-outline-secondary attention-rail__item-action" href="${escapeHtml(item.actionHref)}">${escapeHtml(item.actionLabel)}</a>
        </div>
      `)
      .join('');
  }

  function renderAttentionTimeline(items) {
    if (!attentionTimeline || !attentionTimelineItems || !attentionTimelineCount) return;
    const state = readAttentionState();
    const withState = items.map((item) => {
      const suppression = getSuppressionState(item.id, state);
      return { ...item, suppression };
    });
    const openCount = withState.filter((item) => !item.suppression.suppressed).length;
    const hiddenCount = withState.length - openCount;
    attentionTimelineCount.textContent = `${openCount} open${hiddenCount ? ` / ${hiddenCount} hidden` : ''}`;
    const visible = showSuppressedIncidents
      ? withState
      : withState.filter((item) => !item.suppression.suppressed);
    if (!visible.length) {
      attentionTimelineItems.innerHTML = '<div class="attention-timeline__empty">No incidents logged.</div>';
      return;
    }
    attentionTimelineItems.innerHTML = visible
      .map((item) => `
        <div class="attention-timeline__item ${escapeHtml(item.level)} ${item.suppression.suppressed ? 'suppressed' : ''}">
          <div class="attention-timeline__title">${escapeHtml(item.title)}</div>
          <div class="attention-timeline__detail">${escapeHtml(item.detail)}</div>
          <div class="attention-timeline__meta">
            ${escapeHtml(new Date(item.ts || Date.now()).toLocaleTimeString())}
            ${item.suppression.kind === 'acked' ? '<span class="attention-timeline__state">ACKED</span>' : ''}
            ${item.suppression.kind === 'snoozed' ? `<span class="attention-timeline__state">SNOOZED ${escapeHtml(formatSnoozeRemaining(item.suppression.until))}</span>` : ''}
          </div>
          <div class="attention-timeline__actions">
            <a class="btn btn-sm btn-outline-secondary" href="${escapeHtml(item.actionHref)}">${escapeHtml(item.actionLabel)}</a>
            ${
              item.suppression.suppressed
                ? `<button class="btn btn-sm btn-outline-secondary" type="button" data-attn-action="restore" data-attn-id="${escapeHtml(item.id)}">Restore</button>`
                : `<button class="btn btn-sm btn-outline-secondary" type="button" data-attn-action="ack" data-attn-id="${escapeHtml(item.id)}">Acknowledge</button>
                   <button class="btn btn-sm btn-outline-secondary" type="button" data-attn-action="snooze" data-attn-id="${escapeHtml(item.id)}">Snooze 30m</button>`
            }
          </div>
          ${
            item.evidence
              ? `<details class="attention-timeline__evidence">
                   <summary>Route Evidence</summary>
                   <pre>${escapeHtml(JSON.stringify(item.evidence, null, 2))}</pre>
                 </details>`
              : ''
          }
        </div>
      `)
      .join('');
  }

  function setupAttentionTimelineActions(lastItemsRef) {
    if (!attentionTimelineItems) return;
    attentionTimelineItems.addEventListener('click', (evt) => {
      const target = evt.target;
      if (!(target instanceof HTMLElement)) return;
      const action = target.dataset.attnAction;
      const itemId = target.dataset.attnId;
      if (!action || !itemId) return;
      const state = readAttentionState();
      const entry = state[itemId] || {};
      if (action === 'ack') {
        entry.acked = true;
        entry.snooze_until = null;
      } else if (action === 'snooze') {
        entry.snooze_until = Date.now() + (30 * 60 * 1000);
        entry.acked = false;
      } else if (action === 'restore') {
        entry.snooze_until = null;
        entry.acked = false;
      }
      state[itemId] = entry;
      writeAttentionState(state);
      renderAttentionTimeline(lastItemsRef.current || []);
    });
  }

  function setupAttentionTimelineControls(lastItemsRef) {
    attentionToggleHiddenBtn?.addEventListener('click', () => {
      showSuppressedIncidents = !showSuppressedIncidents;
      attentionToggleHiddenBtn.textContent = showSuppressedIncidents ? 'Hide Hidden' : 'Show Hidden';
      renderAttentionTimeline(lastItemsRef.current || []);
    });

    attentionClearAckedBtn?.addEventListener('click', () => {
      const state = readAttentionState();
      const next = {};
      const now = Date.now();
      Object.entries(state).forEach(([id, entry]) => {
        if (!entry || typeof entry !== 'object') return;
        if (entry.acked) return;
        if (Number.isFinite(entry.snooze_until) && entry.snooze_until > now) {
          next[id] = entry;
        }
      });
      writeAttentionState(next);
      renderAttentionTimeline(lastItemsRef.current || []);
    });
  }

  const attentionItemsRef = { current: [] };
  setupAttentionTimelineActions(attentionItemsRef);
  setupAttentionTimelineControls(attentionItemsRef);

  async function pollAttentionRail() {
    if (!attentionRail) return;
    if (document.hidden) return;
    try {
      const [connectorsResp, availableResp, eventsResp, rulesResp, jobsResp] = await Promise.all([
        fetch('/api/connectors', { cache: 'no-store' }),
        fetch('/api/v1/connectors/available', { cache: 'no-store' }),
        fetch('/api/v1/routing/events?limit=20', { cache: 'no-store' }),
        fetch('/api/v1/routing/rules', { cache: 'no-store' }),
        fetch('/api/v1/routing/jobs?limit=20&include_done=true', { cache: 'no-store' }),
      ]);
      if (!connectorsResp.ok || !availableResp.ok || !eventsResp.ok || !rulesResp.ok || !jobsResp.ok) return;
      const [connectors, available, events, rules, jobs] = await Promise.all([
        connectorsResp.json(),
        availableResp.json(),
        eventsResp.json(),
        rulesResp.json(),
        jobsResp.json(),
      ]);
      const items = buildAttentionItems({ connectors, available, events, rules, jobs });
      attentionItemsRef.current = items;
      renderAttentionRail(items);
      renderAttentionTimeline(items);
      renderPrimeInbox(items, fleetGroupsFromPayload(window.__normanFleetPayload || {}));
    } catch (err) {
      // ignore attention polling errors
    }
  }

  function updateAgeMetric(el, label, timestamp) {
    if (!el) return;
    const then = timestamp ? new Date(timestamp) : null;
    const seconds = then && !Number.isNaN(then.getTime())
      ? Math.max(0, Math.floor((Date.now() - then.getTime()) / 1000))
      : null;
    const text = seconds === null ? '--' : formatAge(timestamp);
    el.textContent = `${label}: ${text || '--'}`;
    el.classList.remove('ok', 'warn', 'danger', 'idle');
    el.classList.add(ageClass(seconds));
  }

  function parseTimestampMs(value) {
    if (!value) return null;
    const parsed = new Date(value);
    return Number.isNaN(parsed.getTime()) ? null : parsed.getTime();
  }

  async function pollTraffic() {
    if (document.hidden) return;
    try {
      const [eventsResp, jobsResp] = await Promise.all([
        fetch('/api/v1/routing/events?limit=50', { cache: 'no-store' }),
        fetch('/api/v1/routing/jobs?limit=50&include_done=true', { cache: 'no-store' }),
      ]);
      if (!eventsResp.ok || !jobsResp.ok) return;
      const [events, jobs] = await Promise.all([eventsResp.json(), jobsResp.json()]);
      const latest = Array.isArray(events) && events.length ? events[0] : null;
      const ts = latest?.created_at || null;
      if (ts) {
        lastSignalTs = ts;
        lastActionTs = ts;
      }

      const nowMs = Date.now();
      const recentWindowMs = 5 * 60 * 1000;
      const recentEvents = (Array.isArray(events) ? events : []).filter((event) => {
        const createdMs = parseTimestampMs(event.created_at);
        return createdMs !== null && (nowMs - createdMs) <= recentWindowMs;
      });
      const activeJobs = (Array.isArray(jobs) ? jobs : []).filter((job) => (
        job.status === 'pending' || job.status === 'processing'
      ));
      const processingJobs = activeJobs.filter((job) => job.status === 'processing');
      const matchedEvents = recentEvents.filter((event) => Number.isFinite(Number.parseInt(event.rule_id, 10)));
      const routedEvents = recentEvents.filter((event) => String(event.delivery_status || '').trim() !== 'skipped');
      const sentEvents = recentEvents.filter((event) => event.delivery_status === 'sent');
      const failedEvents = recentEvents.filter((event) => (
        event.delivery_status === 'failed'
        || event.delivery_status === 'dead_letter'
        || event.status === 'failed'
        || event.status === 'dead_letter'
      ));

      if (metricInflight) metricInflight.textContent = String(activeJobs.length);
      if (metricChannelMsgs) metricChannelMsgs.textContent = String(recentEvents.length);
      if (metricProcessing) metricProcessing.textContent = String(processingJobs.length);
      if (metricBotLatency) metricBotLatency.textContent = '--';
      if (metricBotWait) metricBotWait.textContent = String(activeJobs.length);
      if (metricMatched) metricMatched.textContent = String(matchedEvents.length);
      if (metricRouted) metricRouted.textContent = String(routedEvents.length);
      if (metricFilterDelay) metricFilterDelay.textContent = '--';
      if (metricSent) metricSent.textContent = String(sentEvents.length);
      if (metricFailed) metricFailed.textContent = String(failedEvents.length);
      updateAgeMetric(metricLastSignal, 'Last signal', lastSignalTs);
      updateAgeMetric(metricLastAction, 'Last action', lastActionTs);
      if (ts && ts !== lastMessageTimestamp) {
        lastMessageTimestamp = ts;
        lastPulseAt = Date.now();
        flowMap?.classList.add('active');
        flowLines.forEach(line => line.classList.add('active'));
        setTimeout(() => {
          flowLines.forEach(line => line.classList.remove('active'));
          flowMap?.classList.remove('active');
        }, 1400);
      }
    } catch (err) {
      // ignore polling errors
    }
  }

  loadHomeFleet();
  loadPrimeOps();
  loadPrimeCredits();
  loadPrimeLlmStatus();
  loadPrimeAudit();
  loadPrimeNormanChat();
  pollTraffic();
  pollAttentionRail();
  startAdaptiveLoop('prime-panels', async () => {
    await Promise.allSettled([
      loadPrimeOps({ silent: true }),
      loadPrimeCredits({ silent: true }),
      loadPrimeLlmStatus({ silent: true }),
      loadPrimeAudit({ silent: true }),
      loadPrimeNormanChat({ silent: true }),
    ]);
  }, 12000, 45000);
  startAdaptiveLoop('fleet', loadHomeFleet, 60000, 180000);
  startAdaptiveLoop('traffic', async () => {
    if (document.hidden) {
      return;
    }
    await pollTraffic();
  }, 5000, 30000);
  startAdaptiveLoop('attention', pollAttentionRail, 20000, 60000);
  startAdaptiveLoop('age-metrics', async () => {
    updateAgeMetric(metricLastSignal, 'Last signal', lastSignalTs);
    updateAgeMetric(metricLastAction, 'Last action', lastActionTs);
    const now = Date.now();
    if (flowMap && now - lastPulseAt > 60000) {
      flowMap.classList.add('active');
      flowLines.forEach(line => line.classList.add('active'));
      setTimeout(() => {
        flowLines.forEach(line => line.classList.remove('active'));
        flowMap.classList.remove('active');
      }, 1200);
      lastPulseAt = now;
    }
  }, 10000, 30000);
});
