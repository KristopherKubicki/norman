/* Program pulse uses declared KPI sources and explicitly bound monitoring only. */
(() => {
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const title = value => String(value || '').replaceAll('_', ' ').replace(/\b\w/g, c => c.toUpperCase()).replace(/\b(Asr|Kpi|Cpu|Ok)\b/g, word => word.toUpperCase());
  const number = value => new Intl.NumberFormat(undefined, { maximumFractionDigits: 1 }).format(value);
  const retired = new Set(['retired', 'archived', 'planned']);
  const priority = ['housebot', 'glimpser', 'phobos', 'network-fabric', 'autocamera', 'earlybird', 'leadership-kpis', 'control-plane', 'panelbot', 'norllama', 'tmi', 'artdrop', 'usbhome', 'diamond-roc', 'pefb'];
  const names = { norllama: 'Norllama', norman: 'Norman', earlybird: 'Earlybird', housebot: 'Home automation', glimpser: 'Glimpser', phobos: 'Phobos radio', 'network-fabric': 'Network fabric', autocamera: 'Autocamera', 'control-plane': 'Control Plane', 'leadership-kpis': 'Leadership KPIs', tmi: 'TMI dashboards', artdrop: 'Artdrop' };
  const accounts = { kristopher: 'personal', personal: 'personal', 'kubicki-trust': 'evergreen', openbrand: 'openbrand', work: 'openbrand', yhix: 'yhix', parkergale: 'pefb', 'diamond-roc': 'diamondroc' };
  function safeUrl(value) {
    if (typeof value !== 'string' || /[\x00-\x20\\]/.test(value)) return '';
    if (value.startsWith('/') && !value.startsWith('//')) return value;
    try {
      const url = new URL(value);
      return ['https:', 'http:'].includes(url.protocol) && !url.username && !url.password ? value : '';
    } catch (_) { return ''; }
  }
  function age(stamp, now = Date.now()) {
    const value = Date.parse(stamp);
    return Number.isFinite(value) && value <= now + 60000 ? Math.max(0, now - value) : null;
  }
  function freshness(stamp) {
    const elapsed = age(stamp);
    if (elapsed === null) return 'No observation time';
    const minutes = Math.floor(elapsed / 60000);
    return minutes < 1 ? 'Observed just now' : minutes < 60 ? `Observed ${minutes}m ago` : minutes < 1440 ? `Observed ${Math.floor(minutes / 60)}h ago` : `Observed ${Math.floor(minutes / 1440)}d ago`;
  }
  function observationState(item) {
    const elapsed = age(item.observed_at);
    if (elapsed === null) return 'unknown';
    if (elapsed > (Number(item.max_age_seconds) > 0 ? Number(item.max_age_seconds) : 600) * 1000) return 'stale';
    return ['reachable', 'degraded', 'stale', 'attention', 'idle'].includes(item.health) ? item.health : 'unknown';
  }
  function coverage(app) {
    const observations = Array.isArray(app.observations) ? app.observations : [];
    const states = observations.map(observationState);
    return { observations, states, total: states.length, reachable: states.filter(s => s === 'reachable').length, degraded: states.filter(s => s === 'degraded').length, attention: states.filter(s => s === 'attention').length, idle: states.filter(s => s === 'idle').length, stale: states.filter(s => s === 'stale').length, unknown: states.filter(s => s === 'unknown').length };
  }
  function metrics(app) {
    return (app.kpi_contracts || []).map(contract => {
      const m = contract.measurement;
      if (!m) return contract;
      const binding = contract.binding || {};
      const observation = (app.observations || []).find(o => o.id === m.source);
      const bound = observation && binding.observation_id === m.source && binding.metric_id === m.id;
      return {
        ...contract, value: bound ? m.value : null, status: m.status,
        unit: m.unit || contract.unit, observed_at: m.source_timestamp,
        max_age_seconds: observation?.max_age_seconds || 600,
        source_url: bound ? safeUrl(observation.url) || '/api/v1/estate/applications' : '',
        source_id: m.source, environment: m.environment,
        history: m.history || contract.history,
      };
    }).sort((a, b) => {
      const rank = m => { const state = metricState(m); return !state.valid ? 0 : state.stale ? 1 : 2; };
      return rank(b) - rank(a);
    });
  }
  function formatMetric(metric, value = metric.value) {
    if (metric.unit === 'ratio') return `${number(value * 100)}%`;
    if (metric.unit === 'boolean') return value === 1 ? 'Yes' : value === 0 ? 'No' : number(value);
    if (metric.unit === 'seconds') return value >= 3600 ? `${number(value / 3600)} hr` : value >= 60 ? `${number(value / 60)} min` : `${number(value)} sec`;
    return `${number(value)}${metric.unit ? ` ${value === 1 && ['sites', 'requests', 'connections', 'instances', 'workers'].includes(metric.unit) ? metric.unit.slice(0, -1) : metric.unit}` : ''}`;
  }
  function metricState(metric) {
    // A defined number without provenance and a reporting time is not a measured KPI.
    const source = safeUrl(metric.source_url);
    const elapsed = age(metric.observed_at);
    const valid = typeof metric.value === 'number' && Number.isFinite(metric.value) && !!source && elapsed !== null && !['unwired', 'unknown', 'unavailable'].includes(metric.status);
    const stale = valid && (metric.status === 'stale' || elapsed > (Number(metric.max_age_seconds) > 0 ? Number(metric.max_age_seconds) : 86400) * 1000);
    return { valid, stale, source };
  }
  function sparkline(metric) {
    const points = (Array.isArray(metric.history) ? metric.history : []).filter(p => typeof p.value === 'number' && Number.isFinite(p.value) && age(p.observed_at) !== null).sort((a, b) => Date.parse(a.observed_at) - Date.parse(b.observed_at)).slice(-48);
    if (points.length < 2) return '';
    const values = points.map(p => p.value), min = Math.min(...values), span = Math.max(...values) - min;
    const start = Date.parse(points[0].observed_at), duration = Date.parse(points.at(-1).observed_at) - start;
    const coordinates = values.map((v, i) => `${(duration ? (Date.parse(points[i].observed_at) - start) * 120 / duration : i * 120 / (values.length - 1)).toFixed(1)},${span ? (32 - ((v - min) / span) * 28).toFixed(1) : 18}`).join(' ');
    return `<svg class="program-sparkline" viewBox="0 0 120 36" role="img" aria-label="${esc(`${title(metric.id)}: ${number(values[0])} to ${number(values.at(-1))}, ${values.length} reported observations`)}"><polyline points="${coordinates}" /></svg>`;
  }
  function metricHtml(metric) {
    const state = metricState(metric);
    const target = typeof metric.target === 'number' && Number.isFinite(metric.target) ? `${metric.target_comparison === 'at_most' ? '≤ ' : metric.target_comparison === 'at_least' ? '≥ ' : ''}${formatMetric(metric, metric.target)}` : 'Not set';
    const display = state.valid ? formatMetric(metric) : 'Not connected';
    return `<div class="program-metric" data-metric-state="${state.stale ? 'stale' : state.valid ? 'measured' : 'missing'}"><dt title="${esc(metric.definition || '')}">${esc(metric.label || title(metric.id))}</dt><dd>${esc(display)}</dd>${state.valid ? sparkline(metric) : ''}<small>${state.valid ? `${state.stale ? 'Stale · ' : ''}${esc(metric.window || metric.environment || 'Latest observation')} · Target: ${esc(target)}` : `Needs ${esc(metric.source_kind || 'a measurement source')}`}</small>${state.valid ? `<a href="${esc(state.source)}" target="_blank" rel="noopener noreferrer" title="${esc(metric.source_id || 'Measurement source')}">${esc(freshness(metric.observed_at))} ↗</a>` : ''}</div>`;
  }
  function scopedApps(payload, group, agents) {
    const slugs = new Set(agents.filter(a => a.principal_id === group.id).map(a => a.slug));
    return (payload?.applications || []).filter(app => !retired.has(app.lifecycle) && (app.principal_slug ? app.principal_slug === group.slug : slugs.has(app.primary_tui) || (accounts[group.slug] && app.account === accounts[group.slug])));
  }
  function ranked(apps) {
    return [...apps].sort((a, b) => {
      const rank = app => priority.includes(app.id) ? priority.indexOf(app.id) : 100 + (coverage(app).total ? 0 : 10);
      const measured = app => metrics(app).some(m => metricState(m).valid && !metricState(m).stale);
      return Number(measured(b)) - Number(measured(a)) || rank(a) - rank(b) || (a.name || a.id).localeCompare(b.name || b.id);
    });
  }
  function status(app) {
    const c = coverage(app), action = app.triage?.next_action;
    if (app.monitoring_mode === 'paused' || app.health === 'paused') return { label: 'Paused', tone: 'good', rank: 9, detail: 'Intentionally paused' };
    const failed = c.observations.find((o, i) => c.states[i] === 'degraded');
    if (failed) return { label: 'Needs attention', tone: 'bad', rank: 0, detail: failed.detail || `${c.degraded} failing signal(s)` };
    const breached = metrics(app).find(m => {
      const state = metricState(m);
      return state.valid && !state.stale && typeof m.target === 'number' &&
        (m.target_comparison === 'at_most' ? m.value > m.target : m.target_comparison === 'at_least' ? m.value < m.target : false);
    });
    if (breached) return { label: 'Outside target', tone: 'warn', rank: 1, detail: `${breached.label || title(breached.id)}: ${formatMetric(breached)}` };
    if (c.attention) return { label: 'Warnings reported', tone: 'warn', rank: 2, detail: c.observations.find((o, i) => c.states[i] === 'attention')?.detail || 'The latest source reports warnings' };
    if (app.health === 'on-demand' && !c.stale) return { label: 'On demand', tone: 'good', rank: 9, detail: 'Runs when requested' };
    if (c.stale) return { label: 'Stale signals', tone: 'warn', rank: 3, detail: action || 'Monitoring observations need refreshing' };
    if (!c.total || c.unknown) return { label: 'Coverage gap', tone: 'unknown', rank: 4, detail: action || 'Some monitoring evidence is missing' };
    if (app.health === 'runtime-only') return { label: 'Runtime only', tone: 'unknown', rank: 5, detail: action || 'Connect an output or workflow check' };
    return { label: c.idle ? 'Idle / scaled down' : 'Signals reachable', tone: 'good', rank: 9, detail: '' };
  }
  function moreMetrics(contracts, count) {
    return contracts.length > count ? `<details class="program-more-metrics"><summary>View ${contracts.length - count} more metrics</summary><dl class="program-metrics">${contracts.slice(count).map(metricHtml).join('')}</dl></details>` : '';
  }
  function openButton(app, agents) {
    const agent = agents.find(a => a.slug === app.primary_tui);
    return agent ? `<button type="button" data-program-agent="${esc(agent.slug)}">Open conversation <span aria-hidden="true">↗</span></button>` : `<a href="/systems.html#estate-applications">View program ↗</a>`;
  }
  function card(app, agents, index) {
    const c = coverage(app), tone = status(app), contracts = metrics(app);
    const stamp = c.observations.map(o => o.observed_at).filter(s => age(s) !== null).sort((a, b) => Date.parse(a) - Date.parse(b))[0];
    const source = safeUrl(app.web_url) || '/systems.html#estate-applications';
    const headline = contracts.find(m => metricState(m).valid && !metricState(m).stale);
    const headlineValue = headline ? esc(formatMetric(headline)) : c.total ? `${c.reachable}<span> / ${c.total}</span>` : '—';
    const headlineLabel = headline ? esc(headline.label || title(headline.id)) : c.total ? 'monitored signals reachable' : 'No monitoring feed connected';
    return `<article class="program-card" data-program="${esc(app.id)}" data-tone="${tone.tone}" style="--program-index:${index}"><header><span class="program-mark" aria-hidden="true">${esc((app.id || 'P').slice(0, 2).toUpperCase())}</span><div><h3>${esc(names[app.id] || app.name || title(app.id))}</h3><p>${esc(app.primary_tui ? `With ${title(app.primary_tui.replaceAll('-', ' '))}` : 'Owner not assigned')}</p></div><span class="program-status">${tone.label}</span></header><div class="program-headline"><strong>${headlineValue}</strong><span>${headlineLabel}</span></div><div class="program-coverage" role="img" aria-label="Monitoring: ${c.idle} idle, ${c.attention} warnings, ${c.reachable} reachable, ${c.degraded} degraded, ${c.stale} stale, ${c.unknown} unknown signals">${c.total ? c.states.map(s => `<i data-state="${s}"></i>`).join('') : '<i data-state="unknown"></i>'}</div><dl class="program-metrics">${contracts.slice(0, 2).map(metricHtml).join('') || '<div class="program-metric"><dt>Program KPIs</dt><dd>Not defined</dd><small>No KPI contract published yet</small></div>'}</dl>${moreMetrics(contracts, 2)}<footer><span title="${esc(stamp || '')}">${esc(freshness(stamp))}</span><a href="${esc(source)}" target="_blank" rel="noopener noreferrer">Source ↗</a></footer><div class="program-card-action">${openButton(app, agents)}</div></article>`;
  }
  function render({ payload, group, agents, attention = [], conversations = [], loading, error }) {
    const apps = scopedApps(payload, group, agents), featured = ranked(apps).slice(0, 6);
    const issues = apps.filter(a => status(a).tone !== 'good').sort((a, b) => status(a).rank - status(b).rank || (a.name || a.id).localeCompare(b.name || b.id));
    const contracts = apps.flatMap(metrics), measured = contracts.filter(m => metricState(m).valid && !metricState(m).stale).length;
    const alerts = attention.filter(item => item.group === group.id);
    const recent = conversations.filter(c => c.principal_slug === group.slug).slice(0, 4);
    const sourceError = error || payload?.source?.error;
    const refresh = loading ? 'Refreshing…' : 'Refresh';
    const warning = sourceError ? 'Could not refresh every source. Saved observations may be stale.' : loading && payload ? 'Showing saved programs while checking for updates.' : 'KPI values come from program sources. Coverage bars show the latest monitoring signals.';
    return `<section class="program-dashboard" aria-label="Program dashboard"><header class="program-dashboard-head"><div><p class="program-eyebrow">${esc(group.label)} / Overview</p><h1>Your programs, at a glance.</h1><p>Signals, outcomes, and the conversations behind them.</p></div><button class="program-refresh" type="button" data-program-refresh ${loading ? 'disabled' : ''}>${refresh}</button></header><div class="program-summary"><div><strong>${payload ? apps.length : '—'}</strong><span>Active programs</span></div><div><strong>${payload ? issues.length : '—'}</strong><span>Need review</span></div><div><strong>${payload ? `${measured}<small> / ${contracts.length}</small>` : '—'}</strong><span>Fresh KPI measurements</span></div></div><p class="program-source-note" role="status">${esc(warning)}</p><div class="program-overview-layout"><section class="program-attention" aria-label="Needs your attention"><div class="program-section-heading"><h2>Needs your attention${issues.length ? ` <span class="program-issue-count">${issues.length}</span>` : ''}</h2>${alerts.length ? `<button type="button" data-cockpit-view="attention">${alerts.length} approval${alerts.length === 1 ? '' : 's'} / blocker${alerts.length === 1 ? '' : 's'} →</button>` : ''}</div>${issues.length ? `<div class="program-attention-list">${issues.slice(0, 3).map(app => `<div data-tone="${status(app).tone}"><span class="program-attention-dot" aria-hidden="true"></span><div><strong>${esc(names[app.id] || app.name)}</strong><p>${esc(status(app).label)} · ${esc(status(app).detail)}</p></div>${openButton(app, agents)}</div>`).join('')}</div>` : `<p>${!payload ? 'Loading program observations…' : apps.length ? 'No monitoring gaps reported in this snapshot.' : 'No programs are mapped to this workspace yet.'}</p>`}${contracts.length > measured ? `<a class="program-kpi-gap" href="/systems.html#estate-applications">${contracts.length - measured} KPIs need a fresh measurement. Review sources →</a>` : ''}</section><section class="program-featured"><div class="program-section-heading"><h2>Featured programs</h2><a href="/systems.html#estate-applications">All programs →</a></div><div class="program-grid">${featured.length ? featured.map((app, i) => card(app, agents, i)).join('') : loading ? [1, 2, 3].map(() => '<div class="program-card program-placeholder" aria-hidden="true"><i></i><i></i><i></i></div>').join('') : '<p>Program data is unavailable here. Use Refresh to try again or open All programs.</p>'}</div></section></div>${recent.length ? `<section class="program-recent"><div class="program-section-heading"><h2>Continue a conversation</h2></div><div>${recent.map(c => `<button type="button" data-conversation-id="${esc(c.conversation_id)}"><span>${esc(c.title || 'Conversation')}</span><small>${c.kind === 'direct' ? 'Direct message' : 'Room'}</small><b aria-hidden="true">→</b></button>`).join('')}</div></section>` : ''}</section>`;
  }
  function context({ payload, slug, group, agents }) {
    const app = ranked(scopedApps(payload, group, agents)).find(a => a.primary_tui === slug);
    if (!app) return '';
    const tone = status(app);
    return `<details class="program-context"><summary><span>Program pulse</span><strong>${esc(names[app.id] || app.name)}</strong><small>${tone.label}</small></summary><dl class="program-metrics">${metrics(app).map(metricHtml).join('') || '<p>No KPI contract published yet.</p>'}</dl><a href="/systems.html#estate-applications">Program sources and monitoring →</a></details>`;
  }
  window.BridgeDashboard = { render, context, scopedApps, coverage, metricState, metrics, formatMetric, safeUrl, status };
})();
