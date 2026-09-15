(() => {
  const root = document.getElementById('estate-applications');
  if (!root) return;
  const escape = (value) => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const link = (url, label) => {
    if (!url || !(url.startsWith('/') && !url.startsWith('//') || /^https?:\/\//.test(url))) return '';
    return `<a class="btn btn-sm btn-outline-secondary" href="${escape(url)}" rel="noreferrer">${escape(label)}</a>`;
  };
  const health = (value) => `<span class="badge ${value === 'degraded' ? 'bg-danger' : value === 'reachable' ? 'bg-success' : 'bg-secondary'}">${escape(value)}</span>`;
  let payload;
  let pending = false;
  const search = document.getElementById('applications-search');
  const account = document.getElementById('applications-account');
  const reason = document.getElementById('applications-reason');
  const attention = document.getElementById('applications-attention');
  const retired = document.getElementById('applications-retired');
  const message = document.getElementById('applications-source');
  const list = (items) => `<ul>${items.map(x => `<li>${escape(x)}</li>`).join('')}</ul>`;
  function card(app) {
    const kpis = app.kpi_contracts || [];
    const observations = app.observations || [];
    const instances = app.instances || [];
    return `<details class="card p-3 mb-2" data-application="${escape(app.id)}">
      <summary><strong>${escape(app.name)}</strong> ${health(app.health)}
        <span class="small text-muted"> · ${escape(app.account || 'Account unassigned')} · TUI ${escape(app.operator_observation?.health || 'unknown')}</span></summary>
      <div class="mt-3">
        <h4 class="h6">${escape(app.triage?.category || 'Needs review')} · ${escape(app.triage?.owner || app.primary_tui || 'Owner unassigned')}</h4>
        <p><strong>Next action:</strong> ${escape(app.triage?.next_action || 'Confirm the app health source.')}</p>
        <p class="small">${escape(app.triage?.evidence || '')} ${escape(app.triage?.reviewed_at || '')}</p>
        <p class="small">${escape(app.ownership_basis)}. ${escape(app.account_basis || '')}</p>
        <div class="d-flex gap-2 mb-2">${link(app.web_url, 'Open app')}${link(app.console_url, 'Open responsible TUI')}</div>
        <p>${escape(app.environment_summary)}</p>
        <p class="small">${escape(app.notes || '')}</p>
        <p class="small">Supporting TUIs: ${escape((app.supporting_tuis || []).join(', ') || 'None assigned')}. Operator fallback: ${escape(app.fallback || 'Not specified')}.</p>
        <h4 class="h6">Responsibilities</h4>${app.responsibilities?.length ? list(app.responsibilities) : '<p>Responsible TUI and responsibilities need assignment.</p>'}
        <h4 class="h6">Current observations</h4>
        <p class="small">TUI heartbeat: ${escape(app.operator_observation?.observed_at || 'Not observed')}. Reachability does not establish end-to-end app health.</p>
        ${observations.length ? list(observations.map(o => `${o.name || o.id}: ${o.health} (${o.state}) · ${o.observed_at || 'No timestamp'}${o.detail ? ' · ' + o.detail : ''}`)) : '<p>No app health source is bound yet.</p>'}
        <h4 class="h6">Environment instances</h4>
        ${instances.length ? `<div class="table-responsive"><table class="table table-sm"><thead><tr><th>Environment</th><th>Resource</th><th>Hosting</th><th>Inventory observed</th></tr></thead><tbody>${instances.map(i => `<tr><td>${escape(i.environment)}</td><td>${escape(i.name || i.id)}</td><td>${escape(i.host || [i.hosting_account,i.region].filter(Boolean).join(' / '))}</td><td>${escape(i.observed_at || 'Unverified')}</td></tr>`).join('')}</tbody></table></div>` : '<p>No individual deployment instances verified.</p>'}
        <h4 class="h6">KPIs · ${escape(app.kpi_coverage?.bound || 0)}/${kpis.length} sources bound</h4>
        ${(app.measured_metrics || []).length ? `<h4 class="h6">Collected output metrics</h4>${list(app.measured_metrics.map(m => `${m.id}: ${m.status === 'stale' ? 'stale historical value ' : ''}${m.status === 'unknown' ? 'unknown' : (m.value ?? 'unknown')} ${m.unit || ''} · ${m.source_timestamp || 'No timestamp'} · ${m.source}`))}` : ''}
        ${kpis.length ? list(kpis.map(k => `${k.id}: ${k.measurement?.status === 'observed' ? k.measurement.value + ' ' + (k.measurement.unit || '') : (k.measurement?.status || 'unknown')} — ${k.definition}. ${k.binding ? 'Source: ' + k.binding.observation_id : 'Source needed: ' + k.source_kind}. Target: ${k.target ?? 'not set'}.`)) : '<p>No KPI contract assigned.</p>'}
        ${(app.historical_findings || []).length ? `<h4 class="h6">Audit notes — require recheck</h4>${list(app.historical_findings.map(f => `${f.observed_at}: ${f.finding}`))}` : ''}
      </div></details>`;
  }
  function render() {
    if (!payload) return;
    const query = search.value.toLowerCase().trim();
    const visible = payload.applications.filter(a =>
      (retired.checked || !['retired','archived'].includes(a.lifecycle)) &&
      (!account.value || (a.account || 'unassigned') === account.value) &&
      (!reason?.value || a.triage?.category === reason.value) &&
      (!attention.checked || a.needs_attention) &&
      (!query || [a.name,a.id,a.primary_tui,a.environment_summary,...(a.supporting_tuis || [])].join(' ').toLowerCase().includes(query)));
    const groups = new Map();
    visible.forEach(a => { const owner = a.primary_tui || 'Needs an owner'; if (!groups.has(owner)) groups.set(owner, []); groups.get(owner).push(a); });
    root.innerHTML = [...groups].sort(([a],[b]) => a.localeCompare(b)).map(([owner, apps]) => `<section class="mb-3"><h3 class="h5">${escape(owner)} <span class="text-muted small">${apps.length} apps / projects · ${apps.filter(a => a.needs_attention).length} need attention</span></h3>${apps.map(card).join('')}</section>`).join('') || '<p>No applications match these filters.</p>';
    document.getElementById('applications-count').textContent = `${visible.length} of ${payload.applications.length} apps and projects`;
    const alerts = document.getElementById('applications-alerts');
    if (alerts) alerts.innerHTML = `<summary>${(payload.alerts || []).length} DOHIO estate alerts</summary>${list((payload.alerts || []).map(a => `${a.severity}: ${a.title} — ${a.detail || a.status}`))}`;
    document.getElementById('applications-discoveries').innerHTML = `<summary>${payload.discoveries.length} DOHIO records need reconciliation</summary><p class="small">These may be consoles, aliases, devices, or new services. Discovery does not assign ownership or reactivate retired apps.</p>${list(payload.discoveries.map(d => `${d.name || d.id} · ${d.kind} · ${d.inventory_status || 'unknown'}`))}`;
  }
  async function refresh() {
    if (pending) return;
    pending = true;
    try {
      const response = await fetch('/api/v1/estate/applications', {credentials:'same-origin',headers:{Accept:'application/json'}});
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      payload = await response.json();
      const selected = account.value;
      account.innerHTML = '<option value="">All accounts</option>' + [...new Set(payload.applications.map(a => a.account || 'unassigned'))].sort().map(a => `<option value="${escape(a)}">${escape(a)}</option>`).join('');
      account.value = selected;
      if (reason) {
        const selectedReason = reason.value;
        reason.innerHTML = '<option value="">All categories</option>' + [...new Set(payload.applications.map(a => a.triage?.category || 'unclassified'))].sort().map(r => `<option value="${escape(r)}">${escape(r)}</option>`).join('');
        reason.value = selectedReason;
      }
      message.textContent = payload.source.error || `DOHIO last fetched ${payload.source.fetched_at || 'never'} · App collector: ${payload.source.application_collector_at || 'not yet observed'} · Refreshes every minute while open. Account labels are policy, not verified billing.`;
      render();
    } catch (_) {
      message.textContent = 'Unable to refresh applications. Any displayed observations are from the previous refresh.';
      if (payload) {
        payload.applications.forEach(app => {
          if (!['retired', 'archived', 'planned'].includes(app.lifecycle)) {
            app.health = 'unknown';
            app.needs_attention = true;
          }
          app.operator_observation = {...app.operator_observation, health:'unknown'};
          (app.measured_metrics || []).forEach(m => { m.status = 'unknown'; });
          (app.kpi_contracts || []).forEach(k => { k.measurement = {...k.measurement, status:'unknown'}; });
          if (app.kpi_coverage) app.kpi_coverage.fresh = 0;
        });
        render();
      }
    } finally { pending = false; }
  }
  [search,account,attention,retired].forEach(el => el.addEventListener('input', render));
  reason?.addEventListener('input', render);
  document.getElementById('systems-refresh')?.addEventListener('click', refresh);
  document.addEventListener('visibilitychange', () => { if (!document.hidden) refresh(); });
  const timer = setInterval(() => { if (!document.hidden) refresh(); }, 60000);
  window.addEventListener('pagehide', () => clearInterval(timer), {once:true});
  refresh();
})();
