const fs = require('fs');
const source = fs.readFileSync('app/static/js/bridge_dashboard.js', 'utf8');
let dashboard;
const group = { id: 'kristopher', slug: 'kristopher', label: 'Kristopher' };
const agents = [{ slug: 'housebot', principal_id: 'kristopher' }];
const now = () => new Date().toISOString();
const app = overrides => ({ id: 'housebot', name: 'Housebot', primary_tui: 'housebot', lifecycle: 'managed', observations: [], kpi_contracts: [{ id: 'cycle_success', value: null, target: null, status: 'unwired', source_kind: 'cycle ledger' }], ...overrides });
const render = apps => dashboard.render({ payload: { applications: apps }, group, agents });
beforeEach(() => { window.eval(source); dashboard = window.BridgeDashboard; });

test('missing sources are not shown as zero or healthy, and never produce a trend', () => {
  document.body.innerHTML = render([app()]);
  const card = document.querySelector('.program-card');
  expect(card.textContent).toContain('No monitoring feed connected');
  expect(card.textContent).toContain('Not connected');
  expect(card.dataset.tone).toBe('unknown');
  expect(card.querySelector('svg')).toBeNull();
});

test('workspace filtering excludes unrelated and retired programs', () => {
  const apps = [app(), app({ id: 'retired', lifecycle: 'retired' }), app({ id: 'work', primary_tui: 'control-plane', account: 'openbrand' })];
  expect(dashboard.scopedApps({ applications: apps }, group, agents).map(a => a.id)).toEqual(['housebot']);
});

test('a reachable but old observation is stale and future timestamps are unknown', () => {
  const c = dashboard.coverage(app({ observations: [
    { health: 'reachable', observed_at: new Date(Date.now() - 11 * 60000).toISOString() },
    { health: 'reachable', observed_at: new Date(Date.now() + 3600000).toISOString() },
    { health: 'degraded', observed_at: now() },
  ] }));
  expect(c).toMatchObject({ reachable: 0, stale: 1, unknown: 1, degraded: 1, total: 3 });
});

test('measured zero is preserved only with a valid timestamp and source', () => {
  const metric = { id: 'incidents', value: 0, status: 'measured', source_url: 'https://example.com/metrics', observed_at: now() };
  expect(dashboard.metricState(metric).valid).toBe(true);
  expect(dashboard.metricState({ ...metric, source_url: '' }).valid).toBe(false);
  expect(dashboard.metricState({ ...metric, value: '0' }).valid).toBe(false);
  expect(dashboard.metricState({ ...metric, status: 'unwired' }).valid).toBe(false);
  document.body.innerHTML = render([app({ kpi_contracts: [metric] })]);
  expect(document.querySelector('dd').textContent).toBe('0');
});

test('only reported observations produce accessible sparklines', () => {
  const metric = { id: 'output', value: 7, status: 'measured', observed_at: now(), source_url: '/reports', history: [ { value: 3, observed_at: new Date(Date.now() - 60000).toISOString() }, { value: 7, observed_at: now() } ] };
  document.body.innerHTML = render([app({ kpi_contracts: [metric] })]);
  expect(document.querySelector('svg').getAttribute('aria-label')).toContain('3 to 7');
  expect(document.querySelector('polyline').getAttribute('points')).not.toContain('NaN');
});

test('unsafe links and HTML from upstream cannot execute', () => {
  expect(dashboard.safeUrl('javascript:alert(1)')).toBe('');
  expect(dashboard.safeUrl('//evil.example')).toBe('');
  expect(dashboard.safeUrl('/\\evil.example')).toBe('');
  document.body.innerHTML = render([app({ id: 'custom', name: '<img src=x onerror=alert(1)>', web_url: 'javascript:alert(1)' })]);
  expect(document.querySelector('img')).toBeNull();
  expect(document.querySelector('[href^="javascript:"]')).toBeNull();
});

test('program pulse appears only for a mapped conversation', () => {
  const options = { payload: { applications: [app()] }, group, agents };
  expect(dashboard.context({ ...options, slug: 'housebot' })).toContain('Program pulse');
  expect(dashboard.context({ ...options, slug: 'other' })).toBe('');
});

test('live collector bindings expose measured KPIs with their own source timestamps', () => {
  const program = app({ observations: [{ id: 'housebot-output', health: 'attention', observed_at: now(), max_age_seconds: 86400 }], kpi_contracts: [{ id: 'sites_with_warnings', binding: { observation_id: 'housebot-output', metric_id: 'warnings' }, measurement: { id: 'warnings', source: 'housebot-output', value: 3, unit: 'sites', status: 'observed', source_timestamp: now() } }] });
  const metric = dashboard.metrics(program)[0];
  expect(dashboard.metricState(metric).valid).toBe(true);
  expect(metric.source_url).toBe('/api/v1/estate/applications');
  document.body.innerHTML = render([program]);
  expect(document.querySelector('.program-headline').textContent).toContain('3 sites');
  expect(document.querySelector('.program-status').textContent).toBe('Warnings reported');
  program.kpi_contracts[0].measurement.source = 'wrong-observation';
  expect(dashboard.metricState(dashboard.metrics(program)[0]).valid).toBe(false);
});

test('display units are explicit and stale producer receipts stay stale', () => {
  expect(dashboard.formatMetric({ unit: 'ratio', value: 1 })).toBe('100%');
  expect(dashboard.formatMetric({ unit: 'boolean', value: 0 })).toBe('No');
  expect(dashboard.formatMetric({ unit: 'seconds', value: 420 })).toBe('7 min');
  expect(dashboard.metricState({ value: 1, source_url: '/reports', observed_at: now(), status: 'stale' }).stale).toBe(true);
  expect(dashboard.coverage(app({ observations: [{ health: 'idle', observed_at: now() }] })).idle).toBe(1);
});

test('paused and on-demand programs do not create outage alerts', () => {
  expect(dashboard.status(app({ monitoring_mode: 'paused' })).tone).toBe('good');
  expect(dashboard.status(app({ health: 'on-demand' })).label).toBe('On demand');
  expect(dashboard.status(app({ health: 'runtime-only', observations: [{ health: 'reachable', observed_at: now() }] })).label).toBe('Runtime only');
});

test('fresh explicit target breaches rank above stale evidence and ignore stale values', () => {
  const metric = { id: 'failures', value: 3, target: 0, target_comparison: 'at_most', source_url: '/reports', observed_at: now() };
  const failedTarget = dashboard.status(app({ kpi_contracts: [metric] }));
  expect(failedTarget.label).toBe('Outside target');
  const stale = dashboard.status(app({ observations: [{ health: 'reachable', observed_at: new Date(Date.now() - 3600000).toISOString() }] }));
  expect(failedTarget.rank).toBeLessThan(stale.rank);
  expect(dashboard.status(app({ kpi_contracts: [{ ...metric, status: 'stale' }] })).label).not.toBe('Outside target');
});

test('additional metrics are expandable and fresh values precede stale ones', () => {
  const metric = { value: 1, source_url: '/reports', observed_at: now() };
  const program = app({ kpi_contracts: [{ ...metric, id: 'old', measurement: { source: 'source', id: 'old', value: 1, source_timestamp: now(), status: 'stale' }, binding: { observation_id: 'source', metric_id: 'old' } }, { ...metric, id: 'fresh' }, { ...metric, id: 'extra' }], observations: [{ id: 'source', health: 'reachable', observed_at: now() }] });
  expect(dashboard.metrics(program)[0].id).toBe('fresh');
  document.body.innerHTML = render([program]);
  expect(document.querySelector('.program-more-metrics summary').textContent).toBe('View 1 more metrics');
  expect(document.querySelector('.program-more-metrics dt').textContent).toBe('Old');
});
