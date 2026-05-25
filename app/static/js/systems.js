(() => {
  const summaryRow = document.getElementById('systems-summary-row');
  const directoryGroupsEl = document.getElementById('systems-directory-groups');
  const directoryCountEl = document.getElementById('systems-directory-count');
  const principalsEl = document.getElementById('systems-principals');
  const refreshBtn = document.getElementById('systems-refresh');
  const statusEl = document.getElementById('systems-status');
  const searchEl = document.getElementById('systems-search');
  const principalFiltersEl = document.getElementById('systems-principal-filters');

  if (!summaryRow || !principalsEl) return;

  let selectedLane = 'all';
  let searchTerm = '';
  let latestPayload = null;

  const FLEET_PRIORITY = {
    'norman-service': 0,
    switchboard: 1,
    'norman-home': 2,
    'finance-reader': 1,
    'health-reader': 2,
    parkergale: 3,
    'private-home': 4,
    'toy-box-home': 5,
    housebot: 6,
    glimpser: 7,
    dj: 8,
    castle: 9,
    'diamond-roc': 10,
    'phone-ops': 12,
    uscache: 13,
    theseus: 14,
    'work-special': 12,
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
    'networking-home': 30,
    networking: 31,
    uplink: 32,
    cloudagent: 33,
    'null-agent': 40,
  };

  const DIRECTORY_LANE_ORDER = ['Norman', 'Private', 'Personal', 'Work', 'Yhix', 'Shared'];
  const DIRECTORY_LANE_COPY = {
    Norman: 'Norman, Switchboard, editor, and control surfaces.',
    Private: 'Finance, health, and confidential advisors that should be entered deliberately.',
    Personal: 'Toy Box agents, Glimpser, phone work, and personal operators.',
    Work: 'Work Special bots, live projects, and operator-heavy work sessions.',
    Yhix: 'Yhix cloud experiments, game TUIs, and venture-specific bot lanes.',
    Shared: 'Networking, Uplink, CloudAgent, and shared infrastructure control.',
  };
  const PRIVATE_SERVICE_SLUGS = new Set(['finance-reader', 'health-reader', 'parkergale', 'private-home']);
  const PERSONAL_SERVICE_SLUGS = new Set(['toy-box-home', 'housebot', 'glimpser', 'dj', 'castle', 'diamond-roc', 'phone-ops', 'uscache', 'autocamera', 'theseus']);
  const WORK_SERVICE_SLUGS = new Set(['work-special', 'work-special-home', 'earlybird', 'infra', 'control-plane', 'market-sizing', 'tmi-dashboards', 'gold-book', 'platinum-standard', 'compere', 'leadership-kpis', 'panelbot', 'd-ace']);
  const YHIX_SERVICE_SLUGS = new Set(['null-agent']);
  const SHARED_SERVICE_SLUGS = new Set(['networking-home', 'networking', 'uplink', 'cloudagent']);
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
    'tmi-dashboards': 'tmi',
    'work-special': 'work-special',
    'work-special-home': 'work-special',
  };
  const BOT_HOST_SHORTCUTS = {
    autocamera: 'autocamera.home.arpa',
    castle: 'castle.home.arpa',
    cloudagent: 'cloudagent.home.arpa',
    compere: 'keystone.work.example.test',
    'control-plane': 'cp.work.example.test',
    'diamond-roc': 'diamond-roc.home.arpa',
    dj: 'dj.home.arpa',
    earlybird: 'earlybird.work.example.test',
    glimpser: 'glimpser.home.arpa',
    'gold-book': 'goldbook.work.example.test',
    housebot: 'housebot.home.arpa',
    infra: 'infra.work.example.test',
    'leadership-kpis': 'kpis.work.example.test',
    'market-sizing': 'market.work.example.test',
    mls: 'mls.work.example.test',
    networking: 'networking.home.arpa',
    panelbot: 'panelbot.work.example.test',
    parkergale: 'pefb.home.arpa',
    'phone-ops': 'phone.home.arpa',
    'platinum-standard': 'platinum.work.example.test',
    scout: 'scout.work.example.test',
    switchboard: 'switchboard.home.arpa',
    theseus: 'theseus.home.arpa',
    'tmi-dashboards': 'dashboards.work.example.test',
    uplink: 'uplink.home.arpa',
    usbhome: 'usbhome.home.arpa',
    uscache: 'uscache.home.arpa',
    'work-special': 'work-special.home.arpa',
    'work-special-home': 'work-special.home.arpa',
  };

  function setStatus(message, level = 'info') {
    if (!statusEl) return;
    if (!message) {
      statusEl.classList.add('d-none');
      statusEl.textContent = '';
      statusEl.classList.remove('alert-danger', 'alert-warning', 'alert-success');
      statusEl.classList.add('alert-info');
      return;
    }
    statusEl.classList.remove('d-none', 'alert-info', 'alert-danger', 'alert-warning', 'alert-success');
    statusEl.classList.add(level === 'danger' ? 'alert-danger' : level === 'warn' ? 'alert-warning' : level === 'ok' ? 'alert-success' : 'alert-info');
    statusEl.textContent = message;
  }

  async function fetchJson(url) {
    const response = await fetch(url, {
      credentials: 'same-origin',
      headers: { Accept: 'application/json' },
    });
    if (!response.ok) {
      throw new Error(`Request failed: ${response.status}`);
    }
    return response.json();
  }

  function renderSummary(summary) {
    const order = ['principals', 'bots', 'workers', 'services', 'places', 'assets', 'domains'];
    summaryRow.innerHTML = `
      <div class="card p-3 systems-summary-card">
        <div class="systems-summary-header">
          <div>
            <div class="fw-semibold">Directory Overview</div>
            <div class="small text-muted">Lanes stay separated. Agents, services, and routes stay visible in one place.</div>
          </div>
        </div>
        <div class="systems-summary-strip">
          ${order.map((key) => `
            <div class="systems-summary-stat">
              <div class="systems-summary-value">${summary[key] ?? 0}</div>
              <div class="systems-summary-label">${key}</div>
            </div>
          `).join('')}
        </div>
      </div>
    `;
  }

  function escapeHtml(value) {
    return String(value || '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  const NAMED_TUI_TEXTURES = {
    'norman-service': { angle: 12, crossAngle: 102, grain: 4, crossGrain: 9, glowX: 24, accent: 'blue' },
    switchboard: { angle: 0, crossAngle: 90, grain: 4, crossGrain: 6, glowX: 20, accent: 'gold' },
    dohio: { angle: 145, crossAngle: 55, grain: 6, crossGrain: 10, glowX: 12, accent: 'cyan' },
    housebot: { angle: 0, crossAngle: 90, grain: 5, crossGrain: 8, glowX: 30, accent: 'teal' },
    glimpser: { angle: 128, crossAngle: 38, grain: 4, crossGrain: 12, glowX: 76, accent: 'blue' },
    castle: { angle: 90, crossAngle: 0, grain: 9, crossGrain: 5, glowX: 18, accent: 'stoneGold' },
    maps: { angle: 100, crossAngle: 10, grain: 6, crossGrain: 14, glowX: 58, accent: 'mapGreen' },
    'diamond-roc': { angle: 45, crossAngle: 135, grain: 6, crossGrain: 6, glowX: 50, accent: 'roseGold' },
    'phone-ops': { angle: 90, crossAngle: 12, grain: 4, crossGrain: 7, glowX: 68, accent: 'green' },
    uscache: { angle: 118, crossAngle: 28, grain: 8, crossGrain: 11, glowX: 34, accent: 'archiveGold' },
    usbhome: { angle: 22, crossAngle: 112, grain: 5, crossGrain: 9, glowX: 72, accent: 'cyan' },
    autocamera: { angle: 160, crossAngle: 70, grain: 4, crossGrain: 10, glowX: 82, accent: 'blue' },
    'finance-reader': { angle: 35, crossAngle: 125, grain: 7, crossGrain: 10, glowX: 24, accent: 'emeraldGold' },
    'health-reader': { angle: 64, crossAngle: 154, grain: 6, crossGrain: 8, glowX: 62, accent: 'mint' },
    parkergale: { angle: 42, crossAngle: 132, grain: 7, crossGrain: 10, glowX: 38, accent: 'privatePink' },
    'work-special': { angle: 28, crossAngle: 118, grain: 5, crossGrain: 7, glowX: 18, accent: 'gold' },
    'work-special-home': { angle: 28, crossAngle: 118, grain: 5, crossGrain: 7, glowX: 18, accent: 'gold' },
    earlybird: { angle: 72, crossAngle: 162, grain: 5, crossGrain: 9, glowX: 64, accent: 'sunrise' },
    infra: { angle: 0, crossAngle: 90, grain: 6, crossGrain: 12, glowX: 48, accent: 'steel' },
    'control-plane': { angle: 52, crossAngle: 142, grain: 4, crossGrain: 8, glowX: 42, accent: 'commandGold' },
    'market-sizing': { angle: 108, crossAngle: 18, grain: 7, crossGrain: 6, glowX: 58, accent: 'blueGold' },
    'tmi-dashboards': { angle: 90, crossAngle: 0, grain: 5, crossGrain: 5, glowX: 74, accent: 'purple' },
    'gold-book': { angle: 36, crossAngle: 126, grain: 5, crossGrain: 11, glowX: 26, accent: 'bookGold' },
    compere: { angle: 156, crossAngle: 66, grain: 6, crossGrain: 10, glowX: 46, accent: 'violetGold' },
    'leadership-kpis': { angle: 0, crossAngle: 90, grain: 4, crossGrain: 10, glowX: 84, accent: 'kpiGreen' },
    kpis: { angle: 0, crossAngle: 90, grain: 4, crossGrain: 10, glowX: 84, accent: 'kpiGreen' },
    panelbot: { angle: 136, crossAngle: 46, grain: 6, crossGrain: 8, glowX: 60, accent: 'panelBlue' },
    scout: { angle: 64, crossAngle: 154, grain: 5, crossGrain: 12, glowX: 76, accent: 'scoutBlue' },
    networking: { angle: 72, crossAngle: 162, grain: 4, crossGrain: 13, glowX: 78, accent: 'netCyan' },
    uplink: { angle: 14, crossAngle: 104, grain: 5, crossGrain: 12, glowX: 82, accent: 'signalBlue' },
    cloudagent: { angle: 145, crossAngle: 55, grain: 6, crossGrain: 10, glowX: 70, accent: 'cloudCyan' },
    'null-agent': { angle: 17, crossAngle: 123, grain: 6, crossGrain: 11, glowX: 62, accent: 'yhixPurple' },
    'd-ace': { angle: 154, crossAngle: 64, grain: 8, crossGrain: 5, glowX: 80, accent: 'indigo' },
    acast: { angle: 110, crossAngle: 20, grain: 7, crossGrain: 9, glowX: 66, accent: 'audioPink' },
    artmonster: { angle: 24, crossAngle: 114, grain: 7, crossGrain: 7, glowX: 46, accent: 'artMagenta' },
    'platinum-standard': { angle: 0, crossAngle: 90, grain: 5, crossGrain: 9, glowX: 52, accent: 'platinum' },
  };

  const TUI_TEXTURE_ACCENTS = {
    archiveGold: 'rgba(255, 221, 145, 0.052)',
    artMagenta: 'rgba(217, 70, 239, 0.044)',
    audioPink: 'rgba(244, 114, 182, 0.042)',
    blue: 'rgba(56, 189, 248, 0.040)',
    blueGold: 'rgba(125, 211, 252, 0.040)',
    bookGold: 'rgba(250, 204, 21, 0.060)',
    cloudCyan: 'rgba(103, 232, 249, 0.044)',
    commandGold: 'rgba(250, 204, 21, 0.064)',
    cyan: 'rgba(108, 200, 255, 0.052)',
    emeraldGold: 'rgba(110, 231, 183, 0.042)',
    gold: 'rgba(250, 204, 21, 0.052)',
    green: 'rgba(45, 212, 191, 0.044)',
    indigo: 'rgba(99, 102, 241, 0.040)',
    inkBlue: 'rgba(96, 165, 250, 0.042)',
    kpiGreen: 'rgba(74, 222, 128, 0.044)',
    mapGreen: 'rgba(132, 204, 22, 0.040)',
    mint: 'rgba(167, 243, 208, 0.040)',
    netCyan: 'rgba(34, 211, 238, 0.048)',
    panelBlue: 'rgba(147, 197, 253, 0.040)',
    platinum: 'rgba(226, 232, 240, 0.046)',
    privatePink: 'rgba(244, 114, 182, 0.044)',
    purple: 'rgba(168, 85, 247, 0.046)',
    roseGold: 'rgba(251, 191, 136, 0.046)',
    scoutBlue: 'rgba(96, 165, 250, 0.046)',
    signalBlue: 'rgba(56, 189, 248, 0.050)',
    steel: 'rgba(148, 163, 184, 0.040)',
    stoneGold: 'rgba(214, 169, 83, 0.046)',
    sunrise: 'rgba(251, 191, 36, 0.050)',
    teal: 'rgba(45, 212, 191, 0.040)',
    violetGold: 'rgba(196, 181, 253, 0.042)',
    yhixPurple: 'rgba(139, 92, 246, 0.048)',
  };

  function microtextureSeed(value) {
    return Array.from(String(value || 'shared')).reduce((hash, char) => {
      const nextHash = ((hash << 5) - hash) + char.charCodeAt(0);
      return nextHash | 0;
    }, 216613626);
  }

  function namedTuiTexture(value) {
    const key = String(value || '').trim().toLowerCase();
    return NAMED_TUI_TEXTURES[key] || null;
  }

  function textureStyleFromSpec(spec) {
    const accent = TUI_TEXTURE_ACCENTS[spec.accent] || spec.accent || TUI_TEXTURE_ACCENTS.gold;
    return [
      `--service-card-angle: ${spec.angle}deg`,
      `--service-card-cross-angle: ${spec.crossAngle}deg`,
      `--service-card-grain: ${spec.grain}px`,
      `--service-card-cross-grain: ${spec.crossGrain}px`,
      `--service-card-glow-x: ${spec.glowX}%`,
      `--service-card-accent: ${accent}`,
    ].join('; ');
  }

  function microtextureStyleForService(service, lane = '') {
    const named = namedTuiTexture(service?.slug);
    if (named) return textureStyleFromSpec(named);
    const key = service?.slug || service?.display_name || service?.bot_name || 'service';
    const laneKey = lane || service?.principal_name || service?.domain_name || service?.kind || 'shared';
    const seed = Math.abs(microtextureSeed(`${key}:${laneKey}`));
    const angle = seed % 180;
    const crossAngle = (angle + 86 + (seed % 11)) % 180;
    const grain = 4 + (seed % 6);
    const crossGrain = 5 + ((seed >> 3) % 8);
    const glowX = 18 + ((seed >> 5) % 64);
    const accents = [
      'rgba(250, 204, 21, 0.050)',
      'rgba(168, 85, 247, 0.046)',
      'rgba(45, 212, 191, 0.040)',
      'rgba(56, 189, 248, 0.038)',
      'rgba(244, 114, 182, 0.040)',
    ];
    const accent = accents[seed % accents.length];
    return [
      `--service-card-angle: ${angle}deg`,
      `--service-card-cross-angle: ${crossAngle}deg`,
      `--service-card-grain: ${grain}px`,
      `--service-card-cross-grain: ${crossGrain}px`,
      `--service-card-glow-x: ${glowX}%`,
      `--service-card-accent: ${accent}`,
    ].join('; ');
  }

  function classifyServiceUrl(url) {
    const value = String(url || '').trim();
    const lower = value.toLowerCase();
    if (!value) return '';
    if (isTailnetHostLike(lower)) return 'Tailnet';
    if (lower.includes('127.0.0.1') || lower.includes('localhost')) return 'Local';
    if (isLanHostLike(lower)) return 'LAN';
    return 'Web';
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

  function currentDirectoryRoutePreference() {
    const host = String(window.location.hostname || '').trim().toLowerCase();
    if (isTailnetHostLike(host)) return 'tailnet';
    return 'lan';
  }

  function resolvePreferredServiceRoute(primaryUrl, tailnetUrl) {
    const primary = String(primaryUrl || '').trim();
    const tailnet = String(tailnetUrl || '').trim();
    const preferTailnet = currentDirectoryRoutePreference() === 'tailnet';
    if (preferTailnet) {
      if (tailnet) return { primary: tailnet, alternate: primary, mode: 'tailnet' };
      if (primary) return { primary, alternate: '', mode: 'lan' };
      return { primary: '', alternate: '', mode: 'tailnet' };
    }
    if (primary) return { primary, alternate: tailnet, mode: 'lan' };
    if (tailnet) return { primary: tailnet, alternate: '', mode: 'tailnet' };
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

  function hasDirectoryLinks(service) {
    return [
      service?.web_url,
      service?.web_url_tailnet,
      service?.console_url,
      service?.console_url_tailnet,
    ].some((value) => String(value || '').trim());
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

  function directoryServiceRank(service) {
    const slug = String(service?.slug || '');
    return Object.prototype.hasOwnProperty.call(FLEET_PRIORITY, slug) ? FLEET_PRIORITY[slug] : 20;
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
    if (slug === 'norman-service' || slug === 'switchboard') return 'Norman';
    if (
      PRIVATE_SERVICE_SLUGS.has(slug)
      || routeText.includes('finance')
      || routeText.includes('health')
      || routeText.includes('parkergale')
      || routeText.includes('pef')
      || routeText.includes('private')
    ) return 'Private';
    if (PERSONAL_SERVICE_SLUGS.has(slug) || routeText.includes('toy-box') || routeText.includes('toy box') || routeText.includes('192.168.0.146')) return 'Personal';
    if (WORK_SERVICE_SLUGS.has(slug) || routeText.includes('work-special') || routeText.includes('192.168.0.147')) return 'Work';
    if (YHIX_SERVICE_SLUGS.has(slug) || routeText.includes('yhix')) return 'Yhix';
    if (SHARED_SERVICE_SLUGS.has(slug) || routeText.includes('networking.tail00000.ts.net') || routeText.includes('192.168.0.242')) return 'Shared';
    if (String(principal?.slug || '').trim().toLowerCase() === 'openbrand') return 'Work';
    if (String(principal?.slug || '').trim().toLowerCase() === 'yhix') return 'Yhix';
    return 'Shared';
  }

  function directoryLaneGroups(payload) {
    const laneMap = new Map(DIRECTORY_LANE_ORDER.map((lane) => [lane, {
      slug: lane.toLowerCase(),
      display_name: lane,
      copy: DIRECTORY_LANE_COPY[lane],
      services: [],
    }]));

    (payload?.principals || []).forEach((principal) => {
      (principal.services || []).forEach((service) => {
        if (service?.is_active === false) return;
        if (!hasDirectoryLinks(service)) return;
        if (!directoryServiceMatches(principal, service)) return;
        const lane = laneNameForService(service, principal);
        const group = laneMap.get(lane) || laneMap.get('Shared');
        group.services.push({
          ...service,
          principal_name: principal.display_name,
          principal_slug: principal.slug,
        });
      });
    });

    return DIRECTORY_LANE_ORDER
      .map((lane) => {
        const group = laneMap.get(lane);
        group.services = group.services.sort((a, b) => {
          const aRank = directoryServiceRank(a);
          const bRank = directoryServiceRank(b);
          if (aRank !== bRank) return aRank - bRank;
          return String(a.display_name || a.slug).localeCompare(String(b.display_name || b.slug));
        });
        group.counts = { services: group.services.length };
        return group;
      })
      .filter((group) => group.services.length > 0);
  }

  function directoryRouteState(service) {
    const hasApp = [service?.web_url, service?.web_url_tailnet].some((value) => String(value || '').trim());
    const hasChat = [service?.console_url, service?.console_url_tailnet].some((value) => String(value || '').trim());
    if (hasApp && hasChat) return { label: 'App + Chat', tone: 'ok' };
    if (hasChat) return { label: 'Chat', tone: 'warn' };
    if (hasApp) return { label: 'App', tone: 'warn' };
    return { label: 'Pending', tone: 'idle' };
  }

  function directoryServiceMatches(principal, service) {
    if (service?.is_active === false) return false;
    if (!searchTerm) return true;
    return JSON.stringify({
      principal: principal.display_name,
      principal_slug: principal.slug,
      ...service,
    }).toLowerCase().includes(searchTerm);
  }

  function renderBadges(parts) {
    const items = (parts || []).filter(Boolean);
    if (!items.length) return '';
    return `<div class="systems-item-badges">${items.map((part) => `<span class="systems-badge">${escapeHtml(part)}</span>`).join('')}</div>`;
  }

  function formatMeta(meta) {
    const items = (meta || []).filter(Boolean);
    return items.length ? escapeHtml(items.join(' · ')) : '';
  }

  function itemRow(item, { meta = [], badges = [], actions = '' } = {}) {
    const title = escapeHtml(item.display_name || item.slug);
    const slug = escapeHtml(item.slug);
    const detail = formatMeta(meta);
    return `
      <div class="list-group-item systems-item">
        <div class="systems-item-main">
          <div class="fw-semibold">${title}</div>
          <div class="small text-muted">${slug}${detail ? ` · ${detail}` : ''}</div>
          ${renderBadges(badges)}
        </div>
        ${actions ? `<div class="systems-item-actions">${actions}</div>` : ''}
      </div>
    `;
  }

  function renderServiceActions(item) {
    const actions = [];
    const webRoute = resolvePreferredServiceRoute(item.web_url, item.web_url_tailnet);
    const consoleRoute = resolvePreferredServiceRoute(item.console_url, item.console_url_tailnet);
    const proxyPath = proxyPathForService(item);

    if (proxyPath) {
      actions.push(`<a class="btn btn-primary btn-sm" href="${escapeHtml(proxyPath)}" target="_blank" rel="noreferrer">Norman</a>`);
    }

    if (webRoute.primary) {
      actions.push(`<a class="btn btn-outline-secondary btn-sm" href="${escapeHtml(webRoute.primary)}" target="_blank" rel="noreferrer">${escapeHtml(routeModeLabel('Open', webRoute.mode, Boolean(webRoute.alternate)))}</a>`);
    }
    if (webRoute.alternate) {
      actions.push(`<a class="btn btn-outline-secondary btn-sm" href="${escapeHtml(webRoute.alternate)}" target="_blank" rel="noreferrer">${escapeHtml(alternateRouteLabel('Open', webRoute.mode))}</a>`);
    }
    if (consoleRoute.primary) {
      actions.push(`<a class="btn btn-primary btn-sm" href="${escapeHtml(consoleRoute.primary)}" target="_blank" rel="noreferrer">${escapeHtml(routeModeLabel('Chat', consoleRoute.mode, Boolean(consoleRoute.alternate)))}</a>`);
    }
    if (consoleRoute.alternate) {
      actions.push(`<a class="btn btn-primary btn-sm" href="${escapeHtml(consoleRoute.alternate)}" target="_blank" rel="noreferrer">${escapeHtml(alternateRouteLabel('Chat', consoleRoute.mode))}</a>`);
    }
    return actions.join('');
  }

  function renderDirectoryCard(principal, service) {
    const routeState = directoryRouteState(service);
    const pills = [
      service.worker_name || service.place_name,
      service.bot_name,
      service.policy_mode || service.policy_profile_name,
      service.principal_name || principal.display_name,
    ].filter(Boolean).slice(0, 4);
    const proxyDisplay = proxyDisplayForService(service);
    const textureStyle = microtextureStyleForService(service, principal.display_name);
    return `
      <div class="fleet-card systems-directory-service" data-service-slug="${escapeHtml(service.slug || '')}" style="${escapeHtml(textureStyle)}">
        <div class="fleet-card__header">
          <div>
            <div class="fleet-card__title">${escapeHtml(service.display_name || service.slug)}</div>
            <div class="fleet-card__kind">${escapeHtml(service.kind || 'service')}</div>
          </div>
          <span class="status-chip ${escapeHtml(routeState.tone)}">${escapeHtml(routeState.label)}</span>
        </div>
        ${proxyDisplay ? `<div class="fleet-card__shortcut">${escapeHtml(proxyDisplay)}</div>` : ''}
        <div class="fleet-card__meta">
          <span class="fleet-card__pill">${escapeHtml(principal.display_name)}</span>
          ${pills.map((pill) => `<span class="fleet-card__pill">${escapeHtml(pill)}</span>`).join('')}
        </div>
        <div class="fleet-card__actions">
          ${renderServiceActions(service) || '<span class="fleet-card__hint">Link not configured yet.</span>'}
        </div>
      </div>
    `;
  }

  function renderAgentDirectory(payload) {
    if (!directoryGroupsEl) return;
    const allGroups = directoryLaneGroups(payload);
    const groups = selectedLane === 'all'
      ? allGroups
      : allGroups.filter((group) => String(group.slug || '').trim() === selectedLane);

    const total = groups.reduce((sum, principal) => sum + principal.services.length, 0);
    if (directoryCountEl) {
      directoryCountEl.textContent = total ? `${total} published routes` : 'No published routes';
    }
    if (!total) {
      directoryGroupsEl.innerHTML = '<div class="home-agent-fleet__empty">No agent routes match the current filter.</div>';
      return;
    }
    directoryGroupsEl.innerHTML = groups.map((principal) => `
      <section class="fleet-group systems-directory-group">
        <div class="fleet-group__header">
          <div>
            <div class="fleet-group__title">${escapeHtml(principal.display_name)}</div>
            <div class="fleet-group__meta">${escapeHtml(principal.copy || '')}</div>
          </div>
          <div class="fleet-group__meta">${principal.services.length} routes</div>
        </div>
        <div class="fleet-group__items systems-directory-grid">
          ${principal.services.map((service) => renderDirectoryCard(principal, service)).join('')}
        </div>
      </section>
    `).join('');
  }

  function renderObjectList(title, items, formatter, options = {}) {
    const rows = Array.isArray(items) ? items : [];
    if (!rows.length && options.hideWhenEmpty !== false) {
      return '';
    }
    const classes = ['card', 'p-3', 'systems-section-card'];
    if (options.variant) classes.push(`systems-section-card-${options.variant}`);
    return `
      <div class="${escapeHtml(options.colClass || 'col-12')}">
        <div class="${classes.join(' ')}">
          <div class="d-flex align-items-center justify-content-between mb-2">
            <div class="fw-semibold">${title}</div>
            <span class="badge bg-light text-dark">${rows.length}</span>
          </div>
          <div class="list-group menu-list systems-object-list">
            ${rows.length ? rows.map((item) => formatter(item)).join('') : '<div class="list-group-item text-muted small">None</div>'}
          </div>
        </div>
      </div>
    `;
  }

  function principalMatches(principal) {
    if (selectedLane !== 'all') {
      const hasLaneMatch = (principal.services || []).some((service) => laneNameForService(service, principal).toLowerCase() === selectedLane);
      if (!hasLaneMatch) {
        return false;
      }
    }
    if (searchTerm && !JSON.stringify(principal).toLowerCase().includes(searchTerm)) {
      return false;
    }
    return true;
  }

  function renderPrincipalFilters(principals) {
    if (!principalFiltersEl) return;
    const groups = directoryLaneGroups({ principals: principals || [] });
    const items = [{
      slug: 'all',
      display_name: 'All',
      counts: { services: groups.reduce((sum, group) => sum + group.services.length, 0) },
    }, ...groups];
    principalFiltersEl.innerHTML = items.map((principal) => `
      <button type="button" class="systems-chip ${principal.slug === selectedLane ? 'is-active' : ''}" data-principal-filter="${escapeHtml(principal.slug)}">
        <span>${escapeHtml(principal.display_name)}</span>
        <span class="systems-chip-count">${principal.counts.services}</span>
      </button>
    `).join('');
    principalFiltersEl.querySelectorAll('[data-principal-filter]').forEach((btn) => {
      btn.addEventListener('click', () => {
        selectedLane = btn.getAttribute('data-principal-filter') || 'all';
        renderPrincipalFilters((latestPayload && latestPayload.principals) || []);
        renderAgentDirectory(latestPayload || { principals: [] });
        renderPrincipals((latestPayload && latestPayload.principals) || []);
      });
    });
  }

  function renderPrincipals(principals) {
    const visible = (principals || []).filter(principalMatches);
    principalsEl.innerHTML = visible.map((principal, index) => `
      <details class="card p-3 systems-principal" ${index === 0 ? 'open' : ''}>
        <summary class="systems-principal-summary">
          <div class="systems-principal-heading">
            <div class="fw-semibold">${escapeHtml(principal.display_name)}</div>
            <div class="small text-muted">${escapeHtml(principal.slug)} · ${escapeHtml(principal.kind)}</div>
          </div>
          <div class="systems-principal-counts">
            <span class="badge bg-light text-dark">services ${principal.counts.services}</span>
            <span class="badge bg-light text-dark">workers ${principal.counts.workers}</span>
            <span class="badge bg-light text-dark">bots ${principal.counts.bots}</span>
            <span class="badge bg-light text-dark">places ${principal.counts.places}</span>
          </div>
        </summary>
        <div class="systems-principal-body">
          <div class="systems-principal-note">Principal inventory with live routes filtered through the active Norman lane.</div>
          <div class="row g-3">
            <div class="col-12 col-xl-7">
              <div class="row g-3">
                ${renderObjectList('Services', principal.services, (item) => itemRow(item, {
                  meta: [item.kind, item.domain_name, item.worker_name || item.place_name],
                  badges: [item.bot_name, item.policy_mode || item.policy_profile_name],
                  actions: renderServiceActions(item),
                }), { variant: 'primary' })}
                ${renderObjectList('Workers', principal.workers, (item) => itemRow(item, {
                  meta: [item.kind, item.place_name],
                  badges: [item.control_class_name, item.policy_mode || item.policy_profile_name],
                }), { colClass: 'col-12', variant: 'primary' })}
              </div>
            </div>
            <div class="col-12 col-xl-5">
              <div class="row g-3">
                ${renderObjectList('Bots', principal.bots, (item) => itemRow(item, {
                  meta: [item.class_name, item.domain_name],
                  badges: [item.policy_mode || item.policy_profile_name],
                }), { colClass: 'col-12', variant: 'compact' })}
                ${renderObjectList('Places', principal.places, (item) => itemRow(item, {
                  meta: [item.kind],
                }), { colClass: 'col-12 col-md-6 col-xl-12', variant: 'compact' })}
                ${renderObjectList('Assets', principal.assets, (item) => itemRow(item, {
                  meta: [item.kind, item.place_name || item.worker_name],
                  badges: [item.control_class_name],
                }), { colClass: 'col-12 col-md-6 col-xl-12', variant: 'compact' })}
                ${renderObjectList('Domains', principal.domains, (item) => itemRow(item, {
                  meta: [item.kind],
                  badges: [item.default_policy_mode || item.default_policy_profile_name],
                }), { colClass: 'col-12', variant: 'compact' })}
              </div>
            </div>
          </div>
        </div>
      </details>
    `).join('');
    if (!visible.length) {
      principalsEl.innerHTML = '<div class="card p-3 text-muted small">No directory entries match the current filter.</div>';
    }
  }

  function renderAll(payload) {
    latestPayload = payload;
    renderAgentDirectory(payload);
    renderSummary(payload.summary || {});
    renderPrincipalFilters(payload.principals || []);
    renderPrincipals(payload.principals || []);
  }

  async function loadSystems() {
    setStatus('Loading directory...');
    try {
      const payload = await fetchJson('/api/v1/estate/overview');
      renderAll(payload);
      setStatus('');
    } catch (err) {
      console.error(err);
      setStatus('Failed to load directory.', 'danger');
    }
  }

  searchEl?.addEventListener('input', () => {
    searchTerm = String(searchEl.value || '').trim().toLowerCase();
    renderAgentDirectory(latestPayload || { principals: [] });
    renderPrincipalFilters((latestPayload && latestPayload.principals) || []);
    renderPrincipals((latestPayload && latestPayload.principals) || []);
  });

  refreshBtn?.addEventListener('click', () => {
    loadSystems();
  });

  loadSystems();
})();
