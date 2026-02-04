let selectedChannelId = null;
let channelsCache = [];

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
    item.textContent = ch.name;
    item.dataset.channelId = ch.id;
    item.addEventListener('click', () => selectChannel(ch.id));
    container.appendChild(item);
  });
  if (!filtered.length) {
    const empty = document.createElement('div');
    empty.className = 'text-muted small';
    empty.textContent = 'No channels match your search.';
    container.appendChild(empty);
  }
}

function renderChannelSelects(channels) {
  const messageSelect = document.getElementById('message-channel-select');
  const filterSelect = document.getElementById('filter-channel');
  messageSelect.innerHTML = '<option value="" disabled selected>Choose a channel...</option>';
  filterSelect.innerHTML = '<option value="" disabled selected>Choose channel...</option>';
  channels.forEach(ch => {
    const opt1 = document.createElement('option');
    opt1.value = ch.id;
    opt1.textContent = ch.name;
    messageSelect.appendChild(opt1);
    const opt2 = opt1.cloneNode(true);
    filterSelect.appendChild(opt2);
  });
  messageSelect.disabled = channels.length === 0;
  filterSelect.disabled = channels.length === 0;
}

async function loadConnectors() {
  const select = document.getElementById('channel-connector');
  const addButton = document.getElementById('addChannelBtn');
  select.innerHTML = '';
  const resp = await fetch('/api/connectors');
  if (!resp.ok) {
    select.innerHTML = '<option value="" disabled selected>Unable to load connectors</option>';
    if (addButton) addButton.disabled = true;
    setStatus('channels-status', 'Unable to load connectors. Please refresh or log in again.', 'danger');
    return;
  }
  const connectors = await resp.json();
  if (!connectors.length) {
    select.innerHTML = '<option value="" disabled selected>No connectors yet</option>';
    if (addButton) addButton.disabled = true;
    setStatus('channels-status', 'Create a connector before adding channels.', 'warning');
    return;
  }
  connectors.forEach(connector => {
    const opt = document.createElement('option');
    opt.value = connector.id;
    opt.textContent = `${connector.name} (${connector.connector_type})`;
    select.appendChild(opt);
  });
  if (addButton) addButton.disabled = false;
}

async function loadChannels() {
  const resp = await fetch('/api/v1/channels/');
  if (!resp.ok) {
    setStatus('channels-status', 'Unable to load channels.', 'danger');
    return;
  }
  channelsCache = await resp.json();
  updateCount('channels-count', channelsCache.length);
  renderChannelsList(channelsCache, document.getElementById('channelSearch').value);
  renderChannelSelects(channelsCache);
  if (channelsCache.length && !selectedChannelId) {
    selectChannel(channelsCache[0].id);
  }
  if (!channelsCache.length) {
    setStatus('channels-status', 'No channels yet. Create one on the left.', 'info');
  } else {
    setStatus('channels-status', '');
  }
}

function selectChannel(channelId) {
  selectedChannelId = channelId;
  const channel = channelsCache.find(ch => ch.id === channelId);
  const activeName = document.getElementById('active-channel-name');
  if (activeName) activeName.textContent = channel ? channel.name : 'None';
  const messageSelect = document.getElementById('message-channel-select');
  if (messageSelect) messageSelect.value = String(channelId);
  document.querySelectorAll('.channels-container .list-group-item').forEach(el => {
    el.classList.toggle('active', Number(el.dataset.channelId) === channelId);
  });
  loadMessages(channelId);
}

async function loadMessages(channelId) {
  const resp = await fetch(`/api/v1/channels/${channelId}/messages`);
  if (!resp.ok) {
    setStatus('channels-status', 'Messages are not available for this channel yet.', 'warning');
    return;
  }
  const messages = await resp.json();
  const log = document.getElementById('messages-log');
  log.innerHTML = '';
  messages.forEach(msg => {
    const div = document.createElement('div');
    div.classList.add('message');
    div.textContent = msg.content || msg.text;
    log.appendChild(div);
  });
  log.scrollTop = log.scrollHeight;
}

async function sendMessage() {
  const input = document.getElementById('messageInput');
  const messageSelect = document.getElementById('message-channel-select');
  const targetChannel = Number(messageSelect.value || selectedChannelId);
  if (!targetChannel || !input.value.trim()) return;
  const resp = await fetch(`/api/v1/channels/${targetChannel}/messages`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ content: input.value.trim() }),
  });
  if (!resp.ok) {
    setStatus('channels-status', 'Unable to send message for this channel.', 'danger');
    return;
  }
  input.value = '';
  selectChannel(targetChannel);
}

async function createChannel(data) {
  const resp = await fetch('/api/v1/channels/', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  });
  return resp.json();
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

async function seedSampleChannels() {
  try {
    const sampleConnector = await ensureSampleConnector();
    const channelResp = await fetch('/api/v1/channels/');
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
    setStatus('channels-status', 'Sample channels created.', 'success');
  } catch (err) {
    setStatus('channels-status', err.message || 'Failed to create sample channels.', 'danger');
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
  const resp = await fetch('/api/bots');
  if (!resp.ok) {
    setStatus('bots-status', 'Unable to load bots.', 'danger');
    return;
  }
  const bots = await resp.json();
  updateCount('bots-count', bots.length);
  const list = document.getElementById('bots-list');
  list.innerHTML = '';
  if (!bots.length) {
    setStatus('bots-status', 'No bots yet. Create one below.', 'info');
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
    const channelName = channelsCache.find(ch => ch.id === filter.channel_id)?.name || `Channel ${filter.channel_id}`;
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

document.addEventListener('DOMContentLoaded', () => {
  loadConnectors();
  loadChannels();
  loadBots();
  loadFilters();

  document.getElementById('sendButton').addEventListener('click', sendMessage);
  document.getElementById('message-channel-select').addEventListener('change', (event) => {
    const value = Number(event.target.value);
    if (value) selectChannel(value);
  });

  document.getElementById('channelSearch').addEventListener('input', (event) => {
    renderChannelsList(channelsCache, event.target.value);
  });

  document.getElementById('messages-add-channel-form').addEventListener('submit', async (event) => {
    event.preventDefault();
    const name = document.getElementById('channel-name').value.trim();
    const connectorId = Number(document.getElementById('channel-connector').value);
    if (!name || !connectorId) {
      setStatus('channels-status', 'Channel name and connector are required.', 'danger');
      return;
    }
    const channel = await createChannel({ name, connector_id: connectorId });
    if (!channel?.id) {
      setStatus('channels-status', 'Failed to create channel.', 'danger');
      return;
    }
    document.getElementById('channel-name').value = '';
    await loadChannels();
    selectChannel(channel.id);
    setStatus('channels-status', `Channel "${channel.name}" created.`, 'success');
  });

  document.getElementById('messages-add-bot-form').addEventListener('submit', async (event) => {
    event.preventDefault();
    const nameInput = document.getElementById('bot-name');
    const descInput = document.getElementById('bot-description');
    const name = nameInput.value.trim();
    if (!name) {
      setStatus('bots-status', 'Bot name is required.', 'danger');
      return;
    }
    const bot = await createBot({ name, description: descInput.value.trim(), gpt_model: 'gpt-5-mini' });
    if (!bot?.id) {
      setStatus('bots-status', 'Failed to create bot.', 'danger');
      return;
    }
    nameInput.value = '';
    descInput.value = '';
    await loadBots();
    setStatus('bots-status', `Bot "${bot.name}" created.`, 'success');
  });

  document.getElementById('messages-add-filter-form').addEventListener('submit', async (event) => {
    event.preventDefault();
    const channelId = Number(document.getElementById('filter-channel').value);
    const regexInput = document.getElementById('filter-regex');
    const descInput = document.getElementById('filter-description');
    const regexValue = regexInput.value.trim();
    if (!channelId || !regexValue) {
      setStatus('filters-status', 'Channel and regex are required.', 'danger');
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
    setStatus('filters-status', 'Filter created.', 'success');
  });

  const sampleBtn = document.getElementById('add-sample-channels');
  if (sampleBtn) {
    sampleBtn.addEventListener('click', seedSampleChannels);
  }
});
