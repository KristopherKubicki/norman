// Add a listener for DOMContentLoaded to make sure the page is fully loaded before running the script
function showError(input, message) {
  input.classList.add('is-invalid');
  let feedback = input.parentNode.querySelector('.invalid-feedback');
  if (!feedback) {
    feedback = document.createElement('div');
    feedback.className = 'invalid-feedback';
    input.parentNode.appendChild(feedback);
  }
  feedback.textContent = message;
}

function clearError(input) {
  input.classList.remove('is-invalid');
  const feedback = input.parentNode.querySelector('.invalid-feedback');
  if (feedback) feedback.textContent = '';
}

let connectorsCache = [];
let activeChannelsMobilePane = 'list';
let channelsMobilePaneMedia = null;
const CHANNELS_MOBILE_PANE_KEY = 'norman.mobile.channels.pane.v1';

function readStoredChannelsMobilePane() {
  try {
    const value = (localStorage.getItem(CHANNELS_MOBILE_PANE_KEY) || '').trim();
    return ['list', 'setup'].includes(value) ? value : null;
  } catch (err) {
    return null;
  }
}

function writeStoredChannelsMobilePane(pane) {
  try {
    localStorage.setItem(CHANNELS_MOBILE_PANE_KEY, pane);
  } catch (err) {
    // ignore storage errors
  }
}

function isCompactChannelsViewport() {
  return Boolean(channelsMobilePaneMedia?.matches);
}

function setChannelsMobilePane(pane) {
  const page = document.querySelector('.channels-page');
  if (!page) return;
  activeChannelsMobilePane = pane;
  writeStoredChannelsMobilePane(pane);
  page.dataset.mobilePane = pane;
  document.querySelectorAll('[data-channels-pane]').forEach((btn) => {
    btn.classList.toggle('is-active', btn.getAttribute('data-channels-pane') === pane);
  });
}

function initChannelsMobilePaneSwitcher() {
  const page = document.querySelector('.channels-page');
  const buttons = Array.from(document.querySelectorAll('[data-channels-pane]'));
  if (!page || !buttons.length) return;

  const savedPane = readStoredChannelsMobilePane();
  if (savedPane) {
    activeChannelsMobilePane = savedPane;
  }

  channelsMobilePaneMedia = window.matchMedia('(max-width: 991px)');
  setChannelsMobilePane(activeChannelsMobilePane);

  buttons.forEach((btn) => {
    btn.addEventListener('click', () => {
      setChannelsMobilePane(btn.getAttribute('data-channels-pane') || 'list');
    });
  });

  const syncPaneMode = () => {
    if (isCompactChannelsViewport()) {
      page.dataset.mobilePane = activeChannelsMobilePane;
      return;
    }
    page.removeAttribute('data-mobile-pane');
  };
  syncPaneMode();
  if (typeof channelsMobilePaneMedia.addEventListener === 'function') {
    channelsMobilePaneMedia.addEventListener('change', syncPaneMode);
  } else if (typeof channelsMobilePaneMedia.addListener === 'function') {
    channelsMobilePaneMedia.addListener(syncPaneMode);
  }
}

function hideCollapse(id) {
  const el = document.getElementById(id);
  if (!el || !window.bootstrap?.Collapse) return;
  const instance = window.bootstrap.Collapse.getOrCreateInstance(el, { toggle: false });
  instance.hide();
}

document.addEventListener('DOMContentLoaded', () => {
  initChannelsMobilePaneSwitcher();
  loadConnectors();
  fetchChannelsAndRender();
  initSidebarState();

  const createStarterBtn = document.getElementById('create-starter-channels');
  if (createStarterBtn) {
    createStarterBtn.addEventListener('click', createStarterChannels);
  }

  const form = document.getElementById('add-channel-form');
  if (form) {
    form.addEventListener('submit', onAddChannelSubmit);
  }

  const searchInput = document.getElementById('channelSearch');
  if (searchInput) {
    searchInput.addEventListener('input', (event) => {
      filterRenderedChannels(event.target.value || '');
    });
  }
});

function initSidebarState() {
  // Persist accordion state across navigations so unused panels stay collapsed.
  const addEl = document.getElementById('channels-add-collapse');
  const tilesEl = document.getElementById('channels-tiles-collapse');
  if (!addEl || !tilesEl || typeof bootstrap === 'undefined') return;

  const addOpen = localStorage.getItem('channels_sidebar_add_open');
  const tilesOpen = localStorage.getItem('channels_sidebar_tiles_open');
  const addCollapse = bootstrap.Collapse.getOrCreateInstance(addEl, { toggle: false });
  const tilesCollapse = bootstrap.Collapse.getOrCreateInstance(tilesEl, { toggle: false });

  if (addOpen === '0') addCollapse.hide();
  if (tilesOpen === '1') tilesCollapse.show();

  addEl.addEventListener('shown.bs.collapse', () => localStorage.setItem('channels_sidebar_add_open', '1'));
  addEl.addEventListener('hidden.bs.collapse', () => localStorage.setItem('channels_sidebar_add_open', '0'));
  tilesEl.addEventListener('shown.bs.collapse', () => localStorage.setItem('channels_sidebar_tiles_open', '1'));
  tilesEl.addEventListener('hidden.bs.collapse', () => localStorage.setItem('channels_sidebar_tiles_open', '0'));
}

function updateCount(id, count) {
  const el = document.getElementById(id);
  if (el) el.textContent = count;
}

function setStatus(message, type = 'info') {
  const status = document.getElementById('channels-status');
  if (!status) return;
  if (!message) {
    status.classList.add('d-none');
    status.textContent = '';
    return;
  }
  status.className = `alert alert-${type}`;
  status.textContent = message;
}

async function loadConnectors() {
  const resp = await fetch('/api/connectors', { cache: 'default' });
  const select = document.getElementById('channel-connector');
  const addButton = document.getElementById('addChannelBtn');
  select.innerHTML = '';

  if (!resp.ok) {
    const opt = document.createElement('option');
    opt.value = '';
    opt.textContent = 'Unable to load connectors';
    opt.disabled = true;
    opt.selected = true;
    select.appendChild(opt);
    if (addButton) addButton.disabled = true;
    setStatus('Unable to load connectors. Please refresh or log in again.', 'danger');
    renderStarterChannels();
    return;
  }

  const connectors = await resp.json();
  if (!connectors.length) {
    const opt = document.createElement('option');
    opt.value = '';
    opt.textContent = 'No connectors yet';
    opt.disabled = true;
    opt.selected = true;
    select.appendChild(opt);
    if (addButton) addButton.disabled = true;
    setStatus('Add a connector first, then create a channel.', 'warning');
    renderStarterChannels();
    return;
  }

  // Bulk status fetch to avoid N per-connector /status calls.
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
    // ignore
  }

  const enriched = connectors.map((connector) => {
    const id = Number.parseInt(connector.id, 10);
    const status = Number.isFinite(id) && statusById.has(id)
      ? statusById.get(id)
      : 'unknown';
    return { ...connector, status };
  });
  connectorsCache = enriched;

  const READY_STATUSES = new Set(['up', 'ok', 'healthy', 'active']);
  const ready = enriched.filter((connector) => READY_STATUSES.has(String(connector.status || '').toLowerCase()));

  if (!ready.length) {
    const opt = document.createElement('option');
    opt.value = '';
    opt.textContent = 'No configured connectors';
    opt.disabled = true;
    opt.selected = true;
    select.appendChild(opt);
    if (addButton) addButton.disabled = true;
    setStatus('Configure a connector before creating channels.', 'warning');
    renderStarterChannels();
    return;
  }

  ready.forEach((connector) => {
    const opt = document.createElement('option');
    opt.value = connector.id;
    opt.textContent = `${connector.name} (${connector.connector_type})`;
    select.appendChild(opt);
  });
  if (addButton) addButton.disabled = false;
  setStatus('');
  renderStarterChannels();
}

async function fetchChannelsAndRender() {
  const response = await fetch('/api/v1/channels/', { cache: "no-store" });
  if (!response.ok) {
    setStatus('Unable to load channels.', 'danger');
    return;
  }
  const channels = await response.json();
  updateCount('channels-count', channels.length);

  const channelsContainer = document.querySelector('.channels-container');
  channelsContainer.innerHTML = '';

  if (!channels.length) {
    setStatus('No channels yet. Create one above.', 'info');
    if (isCompactChannelsViewport()) {
      setChannelsMobilePane('setup');
    }
    // When there are no channels, keep the Add section open and surface starter tiles.
    try {
      const addEl = document.getElementById('channels-add-collapse');
      const tilesEl = document.getElementById('channels-tiles-collapse');
      if (addEl && tilesEl && typeof bootstrap !== 'undefined') {
        bootstrap.Collapse.getOrCreateInstance(addEl, { toggle: false }).show();
        bootstrap.Collapse.getOrCreateInstance(tilesEl, { toggle: false }).show();
      }
    } catch (err) {
      // ignore
    }
  } else {
    setStatus('');
    for (const channel of channels) {
      const channelElement = createChannelElement(channel);
      channelsContainer.appendChild(channelElement);
    }
    filterRenderedChannels(document.getElementById('channelSearch')?.value || '');
    // If the user has channels, default to collapsing the tiles panel unless they explicitly opened it.
    if (localStorage.getItem('channels_sidebar_tiles_open') === null) {
      localStorage.setItem('channels_sidebar_tiles_open', '0');
      try {
        const tilesEl = document.getElementById('channels-tiles-collapse');
        if (tilesEl && typeof bootstrap !== 'undefined') {
          bootstrap.Collapse.getOrCreateInstance(tilesEl, { toggle: false }).hide();
        }
      } catch (err) {
        // ignore
      }
    }
  }
}

function filterRenderedChannels(query) {
  const normalized = String(query || '').trim().toLowerCase();
  const tiles = Array.from(document.querySelectorAll('.channels-container .channel-tile'));
  if (!tiles.length) return;
  tiles.forEach((tile) => {
    const name = tile.querySelector('.channel-name')?.textContent?.toLowerCase() || '';
    tile.classList.toggle('d-none', Boolean(normalized) && !name.includes(normalized));
  });
}


async function getChannels() {
  const response = await fetch('/api/v1/channels/', { cache: "no-store" });
  const channels = await response.json();
  return channels;
}

async function createChannel(data) {
  const response = await fetch('/api/v1/channels/', {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(data),
  });
  const channel = await response.json().catch(() => ({}));
  if (!response.ok) {
    if (response.status === 429) {
      throw new Error('Rate limited. Please wait a moment and try again.');
    }
    throw new Error(channel.detail || 'Failed to create channel');
  }
  return channel;
}

async function updateChannel(id, data) {
  const response = await fetch(`/api/v1/channels/${id}`, {
    method: "PUT",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(data),
  });
  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.detail || 'Failed to update channel');
  }
  return response.json();
}

async function deleteChannel(id, force = false) {
  const url = force ? `/api/v1/channels/${id}?force=true` : `/api/v1/channels/${id}`;
  const response = await fetch(url, {
    method: "DELETE",
  });
  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    const detail = error.detail || 'Failed to delete channel';
    const err = new Error(detail);
    err.status = response.status;
    throw err;
  }
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
  });
  if (!created.ok) {
    const error = await created.json();
    throw new Error(error.detail || 'Failed to create sample connector');
  }
  return created.json();
}

const starterChannelTemplates = [
  {
    id: 'nist_time',
    title: 'Time Signals (NIST)',
    description: 'Pull UTC time from time.gov and post updates.',
    type: 'local',
    defaults: { interval_seconds: 15, jitter_seconds: 2 },
    fields: [
      { id: 'channel_name', label: 'Channel name', type: 'text', placeholder: 'Time Signals (NIST)' },
      { id: 'interval_seconds', label: 'Interval (sec)', type: 'number', min: 1, max: 3600, placeholder: '15' },
      { id: 'jitter_seconds', label: 'Jitter (sec)', type: 'number', min: 0, max: 300, placeholder: '2' },
    ],
  },
  {
    id: 'random_data',
    title: 'Random Data',
    description: 'Generate synthetic signals for testing filters.',
    type: 'local',
    defaults: { interval_seconds: 10, jitter_seconds: 0 },
    fields: [
      { id: 'channel_name', label: 'Channel name', type: 'text', placeholder: 'Random Data' },
      { id: 'interval_seconds', label: 'Interval (sec)', type: 'number', min: 1, max: 3600, placeholder: '10' },
      { id: 'jitter_seconds', label: 'Jitter (sec)', type: 'number', min: 0, max: 300, placeholder: '0' },
      { id: 'random_kind', label: 'Randomness', type: 'select', options: ['uniform', 'gaussian', 'uuid', 'choice'] },
      { id: 'random_min', label: 'Min', type: 'number', placeholder: '0' },
      { id: 'random_max', label: 'Max', type: 'number', placeholder: '100' },
      { id: 'random_sigma', label: 'Sigma', type: 'number', placeholder: '1.0' },
      { id: 'random_choices', label: 'Choices (comma)', type: 'text', placeholder: 'alpha,beta,gamma' },
    ],
  },
  {
    id: 'system_monitor',
    title: 'System Monitor',
    description: 'Emit load, disk, and memory stats from this host.',
    type: 'local',
    defaults: { interval_seconds: 20, jitter_seconds: 3 },
    fields: [
      { id: 'channel_name', label: 'Channel name', type: 'text', placeholder: 'System Monitor' },
      { id: 'interval_seconds', label: 'Interval (sec)', type: 'number', min: 1, max: 3600, placeholder: '20' },
      { id: 'jitter_seconds', label: 'Jitter (sec)', type: 'number', min: 0, max: 300, placeholder: '3' },
      { id: 'metrics', label: 'Metrics', type: 'multiselect', options: ['load', 'disk', 'memory'] },
    ],
  },
  {
    id: 'http_poll',
    title: 'HTTP Poll',
    description: 'Poll an HTTP endpoint and emit status + a short response preview.',
    type: 'local',
    defaults: { interval_seconds: 30, jitter_seconds: 2 },
    fields: [
      { id: 'channel_name', label: 'Channel name', type: 'text', placeholder: 'HTTP Poll' },
      { id: 'url', label: 'URL', type: 'text', placeholder: 'https://example.com/health' },
      { id: 'interval_seconds', label: 'Interval (sec)', type: 'number', min: 3, max: 3600, placeholder: '30' },
      { id: 'jitter_seconds', label: 'Jitter (sec)', type: 'number', min: 0, max: 300, placeholder: '2' },
    ],
  },
  {
    id: 'rss_feed',
    title: 'RSS/Atom Feed',
    description: 'Poll a feed URL and emit the newest entry.',
    type: 'local',
    defaults: { interval_seconds: 300, jitter_seconds: 10 },
    fields: [
      { id: 'channel_name', label: 'Channel name', type: 'text', placeholder: 'RSS Feed' },
      { id: 'url', label: 'Feed URL', type: 'text', placeholder: 'https://example.com/rss.xml' },
      { id: 'interval_seconds', label: 'Interval (sec)', type: 'number', min: 10, max: 86400, placeholder: '300' },
      { id: 'jitter_seconds', label: 'Jitter (sec)', type: 'number', min: 0, max: 300, placeholder: '10' },
    ],
  },
  {
    id: 'slack_channel',
    title: 'Slack Channel',
    description: 'Use an existing Slack connector and map a channel.',
    type: 'connector',
    connectorType: 'slack',
    fields: [
      { id: 'channel_name', label: 'Channel name', type: 'text', placeholder: '#alerts' },
      { id: 'connector_id', label: 'Slack connector', type: 'connector' },
    ],
  },
];

function renderStarterChannels() {
  const container = document.getElementById('starter-channels-list');
  if (!container) return;
  container.innerHTML = '';
  starterChannelTemplates.forEach(template => {
    const card = document.createElement('div');
    card.className = 'starter-channel starter-channel--inactive';
    const requires = template.connectorType;
    const availableConnectors = requires
      ? connectorsCache.filter(c => c.connector_type === requires && c.status === 'up')
      : connectorsCache.filter(c => c.status === 'up');
    const disabled = template.type === 'connector' && !availableConnectors.length;
    card.innerHTML = `
      <label class="starter-channel__header">
        <input type="checkbox" class="starter-channel__toggle" data-template="${template.id}" ${disabled ? 'disabled' : ''}>
        <div>
          <div class="starter-channel__title">${template.title}</div>
          <div class="starter-channel__desc">${template.description}</div>
        </div>
        ${disabled ? '<span class="badge bg-light text-muted">Connector missing</span>' : ''}
      </label>
      <div class="starter-channel__fields" data-fields="${template.id}">
        ${template.fields.map(field => renderStarterField(field, availableConnectors)).join('')}
      </div>
    `;
    container.appendChild(card);

    const toggle = card.querySelector('.starter-channel__toggle');
    const fields = card.querySelector('.starter-channel__fields');
    if (toggle && fields) {
      fields.style.display = 'none';
      toggle.addEventListener('change', () => {
        const active = toggle.checked;
        card.classList.toggle('starter-channel--inactive', !active);
        fields.style.display = active ? '' : 'none';
      });
    }
  });
}

function renderStarterField(field, connectors) {
  if (field.type === 'select') {
    return `
      <div class="starter-field">
        <label>${field.label}</label>
        <select data-field="${field.id}">
          ${field.options.map(opt => `<option value="${opt}">${opt}</option>`).join('')}
        </select>
      </div>
    `;
  }
  if (field.type === 'multiselect') {
    return `
      <div class="starter-field">
        <label>${field.label}</label>
        <div class="starter-field__checks">
          ${field.options
            .map(
              opt =>
                `<label><input type="checkbox" data-field="${field.id}" value="${opt}" checked> ${opt}</label>`
            )
            .join('')}
        </div>
      </div>
    `;
  }
  if (field.type === 'connector') {
    return `
      <div class="starter-field">
        <label>${field.label}</label>
        <select data-field="${field.id}">
          ${connectors.map(conn => `<option value="${conn.id}">${conn.name}</option>`).join('')}
        </select>
      </div>
    `;
  }
  return `
    <div class="starter-field">
      <label>${field.label}</label>
      <input data-field="${field.id}" type="${field.type}" placeholder="${field.placeholder || ''}" ${field.min ? `min="${field.min}"` : ''} ${field.max ? `max="${field.max}"` : ''}>
    </div>
  `;
}

async function createStarterChannels() {
  const container = document.getElementById('starter-channels-list');
  if (!container) return;
  const selected = Array.from(container.querySelectorAll('.starter-channel__toggle'))
    .filter(toggle => toggle.checked)
    .map(toggle => toggle.dataset.template);
  if (!selected.length) {
    setStatus('Select at least one starter channel.', 'warning');
    return;
  }
  try {
    const sampleConnector = await ensureSampleConnector();
    const existing = await getChannels();
    for (const templateId of selected) {
      const template = starterChannelTemplates.find(t => t.id === templateId);
      if (!template) continue;
      const fieldsRoot = container.querySelector(`[data-fields="${templateId}"]`);
      const fieldValues = collectStarterFields(fieldsRoot);
      const name = fieldValues.channel_name || template.title;
      if (existing.find(c => c.name === name)) continue;
      const connectorId = template.type === 'connector'
        ? Number(fieldValues.connector_id || 0)
        : sampleConnector.id;
      if (template.type === 'connector' && !connectorId) {
        throw new Error(`Connector required for ${template.title}`);
      }
      const channel = await createChannel({ name, connector_id: connectorId });
      if (template.type === 'local') {
        await startChannelFeed(channel.id, template.id, fieldValues);
      }
    }
    await fetchChannelsAndRender();
    setStatus('Starter channels created.', 'success');
  } catch (err) {
    setStatus(err.message || 'Failed to create starter channels.', 'danger');
  }
}

function collectStarterFields(root) {
  if (!root) return {};
  const values = {};
  const inputs = root.querySelectorAll('input, select');
  inputs.forEach(input => {
    if (input.type === 'checkbox' && input.hasAttribute('value')) {
      if (!values[input.dataset.field]) values[input.dataset.field] = [];
      if (input.checked) values[input.dataset.field].push(input.value);
      return;
    }
    values[input.dataset.field] = input.value;
  });
  return values;
}

async function startChannelFeed(channelId, source, fields) {
  const interval = parseInt(fields.interval_seconds || 10, 10);
  const jitter = parseInt(fields.jitter_seconds || 0, 10);
  const config = {};
  if (source === 'random_data') {
    config.kind = fields.random_kind || 'uniform';
    if (fields.random_min) config.min = parseFloat(fields.random_min);
    if (fields.random_max) config.max = parseFloat(fields.random_max);
    if (fields.random_sigma) config.sigma = parseFloat(fields.random_sigma);
    if (fields.random_choices) {
      config.choices = fields.random_choices.split(',').map(v => v.trim()).filter(Boolean);
    }
  }
  if (source === 'system_monitor') {
    config.metrics = fields.metrics && fields.metrics.length ? fields.metrics : ['load', 'disk', 'memory'];
  }
  if (source === 'http_poll' || source === 'rss_feed') {
    config.url = (fields.url || '').trim();
  }
  const payload = {
    source,
    interval_seconds: Number.isNaN(interval) ? 10 : interval,
    jitter_seconds: Number.isNaN(jitter) ? 0 : jitter,
    config,
  };
  const resp = await fetch(`/api/v1/channels/${channelId}/feeds/start`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({}));
    throw new Error(err.detail || 'Failed to start feed');
  }
}

function createChannelElement(channel) {
  const channelElement = document.createElement("div");
  channelElement.classList.add("channel-tile");
  channelElement.title = 'Open channel details';

  const headerRow = document.createElement('div');
  headerRow.className = 'channel-row';

  const nameElement = document.createElement('div');
  nameElement.className = 'channel-name';
  nameElement.textContent = channel.name;

  const actions = document.createElement('div');
  actions.className = 'channel-actions';

  headerRow.appendChild(nameElement);
  headerRow.appendChild(actions);

  const connectorElement = document.createElement('div');
  connectorElement.className = 'channel-meta';
  connectorElement.textContent = `Connector ${channel.connector_id}`;

  const editForm = document.createElement('div');
  editForm.className = 'd-none mt-2 channel-edit-form';
  editForm.innerHTML = `
    <input type="text" class="form-control form-control-sm mb-2" value="${channel.name}">
    <input type="number" class="form-control form-control-sm mb-2" value="${channel.connector_id}">
    <div class="d-flex gap-2">
      <button class="btn btn-sm btn-primary" type="button">Save</button>
      <button class="btn btn-sm btn-outline-secondary" type="button">Cancel</button>
    </div>
  `;

  const editButton = document.createElement("button");
  editButton.textContent = "Edit";
  editButton.className = 'btn btn-sm btn-outline-secondary';
  editButton.addEventListener("click", async () => {
    document.querySelectorAll('.channel-tile.editing').forEach(item => {
      if (item !== channelElement) {
        item.classList.remove('editing');
        item.querySelector('.channel-edit-form')?.classList.add('d-none');
      }
    });
    const nowHidden = !editForm.classList.contains('d-none');
    editForm.classList.toggle('d-none', nowHidden);
    channelElement.classList.toggle('editing', !nowHidden);
    if (!nowHidden) {
      nameInput.focus();
      nameInput.select();
    }
  });

  const deleteButton = document.createElement("button");
  deleteButton.textContent = "Delete";
  deleteButton.className = 'btn btn-sm btn-outline-danger';
  deleteButton.addEventListener("click", async () => {
    if (!confirm(`Delete channel "${channel.name}"?`)) return;
    try {
      await deleteChannel(channel.id);
      await fetchChannelsAndRender();
      setStatus('Channel deleted.', 'success');
    } catch (err) {
      if (err.status === 409) {
        const confirmed = confirm('This channel has related records. Delete them and remove the channel?');
        if (!confirmed) {
          setStatus('Delete cancelled.', 'info');
          return;
        }
        try {
          await deleteChannel(channel.id, true);
          await fetchChannelsAndRender();
          setStatus('Channel deleted (with related records).', 'success');
          return;
        } catch (forceErr) {
          setStatus(forceErr.message || 'Failed to delete channel.', 'danger');
          return;
        }
      }
      setStatus(err.message || 'Failed to delete channel.', 'danger');
    }
  });

  actions.appendChild(editButton);
  actions.appendChild(deleteButton);

  channelElement.appendChild(headerRow);
  channelElement.appendChild(connectorElement);
  channelElement.appendChild(editForm);

  const [nameInput, connectorInput] = editForm.querySelectorAll('input');
  const [saveBtn, cancelBtn] = editForm.querySelectorAll('button');
  saveBtn.addEventListener('click', async () => {
    const newName = nameInput.value.trim();
    const newConnector = Number(connectorInput.value);
    if (!newName || !newConnector) {
      setStatus('Name and connector are required.', 'danger');
      return;
    }
    try {
      const updatedChannel = await updateChannel(channel.id, { name: newName, connector_id: newConnector });
      channel.name = updatedChannel.name;
      channel.connector_id = updatedChannel.connector_id;
      nameElement.textContent = updatedChannel.name;
      connectorElement.textContent = `Connector ${updatedChannel.connector_id}`;
      editForm.classList.add('d-none');
      setStatus('Channel updated.', 'success');
    } catch (err) {
      setStatus(err.message, 'danger');
    }
  });
  cancelBtn.addEventListener('click', () => {
    nameInput.value = channel.name;
    connectorInput.value = channel.connector_id;
    editForm.classList.add('d-none');
  });

  return channelElement;
}

async function onAddChannelSubmit(event) {
  event.preventDefault();

  const nameInput = document.getElementById('channel-name');
  const connectorInput = document.getElementById('channel-connector');

  clearError(nameInput);
  clearError(connectorInput);

  const name = nameInput.value.trim();
  const connector = connectorInput.value;

  if (!name) {
    showError(nameInput, 'Name is required');
    return;
  }

  if (!connector) {
    showError(connectorInput, 'Connector is required');
    return;
  }

  const channelData = {
    name,
    connector_id: parseInt(connector, 10),
  };

  try {
    const newChannel = await createChannel(channelData);
    if (!newChannel || !newChannel.id) {
      setStatus('Failed to add channel. Make sure a connector is selected.', 'danger');
      return;
    }
    await fetchChannelsAndRender();
    hideCollapse('channels-add-collapse');
    if (isCompactChannelsViewport()) {
      setChannelsMobilePane('list');
    }
    setStatus(`Channel "${newChannel.name}" created.`, 'success');
    nameInput.value = '';
  } catch (err) {
    setStatus(err.message || 'Failed to add channel.', 'danger');
  }
}
