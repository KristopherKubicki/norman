(() => {
  const summaryRow = document.getElementById('systems-summary-row');
  const tuiFleetHealthEl = document.getElementById('tui-fleet-health');
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
    'norman-home': 1,
    'finance-reader': 1,
    'health-reader': 2,
    parkergale: 3,
    'private-home': 4,
    'toy-box-home': 5,
    housebot: 6,
    glimpser: 7,
    dj: 8,
    tv: 9,
    studio: 10,
    castle: 11,
    'phone-ops': 12,
    'diamond-roc': 13,
    uscache: 14,
    theseus: 15,
    artmonster: 16,
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
    netops: 31,
    uplink: 32,
    cloudagent: 33,
    'dohio-topology': 34,
    'switchyard-network-board': 35,
  };

  const DIRECTORY_LANE_ORDER = ['Norman', 'Private', 'Personal', 'Work', 'Shared'];
  const DIRECTORY_LANE_COPY = {
    Norman: 'Norman Prime, editor, and control surfaces.',
    Private: 'Finance, health, and confidential advisors that should be entered deliberately.',
    Personal: 'Toy Box agents, Glimpser, phone work, and personal operators.',
    Work: 'Work Special bots, live projects, and operator-heavy work sessions.',
    Shared: 'Networking, Uplink, CloudAgent, DOHIO topology, and shared infrastructure control.',
  };
  const PRIVATE_SERVICE_SLUGS = new Set(['finance-reader', 'health-reader', 'parkergale', 'private-home']);
  const PERSONAL_SERVICE_SLUGS = new Set(['toy-box-home', 'housebot', 'glimpser', 'dj', 'tv', 'studio', 'castle', 'phone-ops', 'diamond-roc', 'uscache', 'autocamera', 'theseus', 'artmonster']);
  const WORK_SERVICE_SLUGS = new Set(['work-special-home', 'earlybird', 'infra', 'control-plane', 'market-sizing', 'tmi-dashboards', 'gold-book', 'platinum-standard', 'publisher', 'compere', 'leadership-kpis', 'panelbot', 'd-ace']);
  const SHARED_SERVICE_SLUGS = new Set(['networking-home', 'networking', 'netops', 'uplink', 'cloudagent', 'dohio-topology', 'switchyard-network-board']);
  const BOT_PROXY_ALIASES = {
    autocamera: 'auto',
    compere: 'keystone',
    'control-plane': 'cp',
    'diamond-roc': 'diamond',
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
    netops: 'networking.home.arpa',
    panelbot: 'panelbot.kris.openbrand.com',
    parkergale: 'pefb.home.arpa',
    'phone-ops': 'phone.home.arpa',
    'diamond-roc': 'diamond.home.arpa',
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
    autocamera: 'AC',
    artmonster: 'AM',
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
    netops: 'NE',
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

  function fleetHealthTone(health) {
    const status = String(health?.status || '').trim().toLowerCase();
    const summary = health?.summary || {};
    if (!health?.available || status === 'missing' || status === 'invalid') return 'idle';
    if (status === 'fail' || Number(summary.fail || 0) > 0) return 'fail';
    if (status === 'warn' || Number(summary.warn || 0) > 0) return 'warn';
    return 'ok';
  }

  function fleetHealthLabel(tone) {
    if (tone === 'fail') return 'Fail';
    if (tone === 'warn') return 'Warn';
    if (tone === 'ok') return 'OK';
    return 'Unavailable';
  }

  function renderFleetHealth(health) {
    if (!tuiFleetHealthEl) return;
    const summary = health?.summary || {};
    const issues = Array.isArray(health?.issues) ? health.issues : [];
    const tone = fleetHealthTone(health);
    const source = health?.source || {};
    const age = Number(source.age_seconds || 0);
    const ageLabel = health?.available && age > 0
      ? `${Math.floor(age / 60)}m old`
      : '';
    const checkedAt = health?.checked_at ? String(health.checked_at).replace('T', ' ').replace('Z', ' UTC') : 'not available';
    const topIssues = issues.slice(0, 4);
    const issueRows = topIssues.map((issue) => `
      <div class="systems-fleet-health-issue">
        <span class="status-chip ${escapeHtml(issue.severity === 'fail' ? 'danger' : 'warn')}">${escapeHtml(issue.severity || 'warn')}</span>
        <span>${escapeHtml([issue.host, issue.instance, issue.check].filter(Boolean).join(' / '))}</span>
        <span class="text-muted">${escapeHtml(issue.detail || '')}</span>
      </div>
    `).join('');

    tuiFleetHealthEl.innerHTML = `
      <div class="card p-3 systems-fleet-health systems-fleet-health-${escapeHtml(tone)}">
        <div class="systems-fleet-health-main">
          <div>
            <div class="systems-fleet-health-title">TUI Fleet Health</div>
            <div class="systems-fleet-health-meta">${escapeHtml(checkedAt)}${ageLabel ? ` · ${escapeHtml(ageLabel)}` : ''}</div>
          </div>
          <span class="status-chip ${escapeHtml(tone === 'fail' ? 'danger' : tone === 'warn' ? 'warn' : tone === 'ok' ? 'ok' : 'idle')}">${escapeHtml(fleetHealthLabel(tone))}</span>
        </div>
        <div class="systems-fleet-health-stats">
          <div><span>${Number(summary.active || 0)}</span><small>active</small></div>
          <div><span>${Number(summary.fail || 0)}</span><small>fail</small></div>
          <div><span>${Number(summary.warn || 0)}</span><small>warn</small></div>
          <div><span>${Number(summary.hosts || 0)}</span><small>hosts</small></div>
        </div>
        ${topIssues.length ? `<div class="systems-fleet-health-issues">${issueRows}</div>` : ''}
        ${!health?.available && health?.detail ? `<div class="systems-fleet-health-detail">${escapeHtml(health.detail)}</div>` : ''}
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

  function directoryLaneGroups(payload) {
    const laneMap = new Map(DIRECTORY_LANE_ORDER.map((lane) => [lane, {
      slug: lane.toLowerCase(),
      display_name: lane,
      copy: DIRECTORY_LANE_COPY[lane],
      services: [],
    }]));

    (payload?.principals || []).forEach((principal) => {
      (principal.services || []).forEach((service) => {
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
    const laneLabel = laneNameForService(service, principal);
    const tone = laneLabel.toLowerCase();
    const mark = fleetMarkForService(service);
    const plateLabel = `${laneLabel} lane`;
    const kindLine = [
      service.kind || 'service',
      principal.display_name,
    ].filter(Boolean).join(' · ');
    return `
      <div class="fleet-card systems-directory-service">
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
    renderFleetHealth(payload.tuiFleetHealth || null);
    renderAgentDirectory(payload);
    renderSummary(payload.summary || {});
    renderPrincipalFilters(payload.principals || []);
    renderPrincipals(payload.principals || []);
  }

  async function loadSystems() {
    setStatus('Loading directory...');
    try {
      const [payload, tuiFleetHealth] = await Promise.all([
        fetchJson('/api/v1/estate/overview'),
        fetchJson('/api/v1/estate/tui-fleet-health').catch((err) => ({
          available: false,
          status: 'error',
          detail: err.message,
          summary: { active: 0, fail: 0, warn: 0, hosts: 0, ok: false },
          issues: [],
        })),
      ]);
      payload.tuiFleetHealth = tuiFleetHealth;
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
