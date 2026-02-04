// connectors.js - dynamic connector management

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

let cachedConnectors = [];
let cachedBots = [];
let availableConnectorTypes = [];

document.addEventListener('DOMContentLoaded', () => {
  renderWebhookUrls();
  enableCopyButtons();
  loadConnectorTypes();
  fetchConnectorsAndRender();
  startStatusPolling();
  loadRoutingUI();

  const addForm = document.getElementById('add-connector-form');
  if (addForm) {
    addForm.addEventListener('submit', async (evt) => {
      evt.preventDefault();
      const nameInput = document.getElementById('connector-name');
      const typeInput = document.getElementById('connector-type');
      const configInput = document.getElementById('connector-config');
      clearError(nameInput);
      clearError(typeInput);
      clearError(configInput);

      const name = nameInput.value.trim();
      const type = typeInput.value.trim();
      let config = {};

      if (!name) {
        showError(nameInput, 'Name is required');
        return;
      }

      if (!type) {
        showError(typeInput, 'Type is required');
        return;
      }

      if (configInput.value.trim()) {
        try {
          config = JSON.parse(configInput.value);
        } catch (e) {
          showError(configInput, 'Config must be valid JSON');
          return;
        }
      }
      const connector = await createConnector({
        name,
        connector_type: type,
        config: config
      });
      document.querySelector('.connectors-container')
        .appendChild(createConnectorElement(connector));
      nameInput.value = '';
      typeInput.value = '';
      configInput.value = '';
    });
  }
});

async function fetchConnectorsAndRender() {
  const connectors = await getConnectors();
  cachedConnectors = connectors;
  renderRoutingConnectorOptions();
  const container = document.querySelector('.connectors-container');
  container.innerHTML = '';
  for (const connector of connectors) {
    const el = createConnectorElement(connector);
    container.appendChild(el);
    // fetch status for each connector
    try {
      const status = await getConnectorStatus(connector.id);
      el.querySelector('.connector-status').textContent = status.status;
    } catch (e) {
      el.querySelector('.connector-status').textContent = 'unknown';
    }
  }
  renderStatusTable(connectors);
}

async function loadConnectorTypes() {
  const select = document.getElementById('connector-type');
  if (!select) return;
  const resp = await fetch('/api/v1/connectors/available');
  if (!resp.ok) {
    select.innerHTML = '<option value="" disabled selected>Unable to load types</option>';
    return;
  }
  availableConnectorTypes = await resp.json();
  select.innerHTML = '<option value="" disabled selected>Select a type</option>';
  availableConnectorTypes.forEach((item) => {
    const opt = document.createElement('option');
    opt.value = item.id;
    opt.textContent = item.name;
    opt.dataset.fields = JSON.stringify(item.fields || []);
    select.appendChild(opt);
  });

  select.addEventListener('change', () => {
    const selected = select.options[select.selectedIndex];
    const fields = JSON.parse(selected.dataset.fields || '[]');
    if (!fields.length) return;
    const template = fields.reduce((acc, field) => {
      acc[field] = '';
      return acc;
    }, {});
    const configInput = document.getElementById('connector-config');
    if (configInput && !configInput.value) {
      configInput.value = JSON.stringify(template);
    }
  });
}

async function fetchBots() {
  const resp = await fetch('/api/bots');
  return await resp.json();
}

function renderRoutingConnectorOptions() {
  const select = document.getElementById('routing-rule-connector');
  if (!select) return;
  select.innerHTML = '';
  const anyOption = document.createElement('option');
  anyOption.value = '';
  anyOption.textContent = 'Any connector';
  select.appendChild(anyOption);
  cachedConnectors.forEach((connector) => {
    const opt = document.createElement('option');
    opt.value = connector.id;
    opt.textContent = `${connector.name} (${connector.connector_type})`;
    opt.dataset.connectorType = connector.connector_type;
    select.appendChild(opt);
  });
}

function renderRoutingBotOptions() {
  const select = document.getElementById('routing-rule-bot');
  if (!select) return;
  select.innerHTML = '';
  cachedBots.forEach((bot) => {
    const opt = document.createElement('option');
    opt.value = bot.id;
    opt.textContent = bot.name;
    select.appendChild(opt);
  });
}

async function loadRoutingUI() {
  const form = document.getElementById('routing-rule-form');
  if (!form) return;
  cachedBots = await fetchBots();
  renderRoutingBotOptions();
  renderRoutingConnectorOptions();
  await loadRoutingRules();
  await loadRoutingEvents();
  setInterval(loadRoutingEvents, 10000);

  form.addEventListener('submit', async (evt) => {
    evt.preventDefault();
    const name = document.getElementById('routing-rule-name').value.trim();
    const connectorValue = document.getElementById('routing-rule-connector').value;
    const botValue = document.getElementById('routing-rule-bot').value;
    const matchType = document.getElementById('routing-rule-type').value;
    const matchValue = document.getElementById('routing-rule-value').value.trim();
    const priority = Number.parseInt(
      document.getElementById('routing-rule-priority').value,
      10
    );
    const isActive = document.getElementById('routing-rule-active').checked;

    if (!name || !botValue) return;

    const payload = {
      name,
      bot_id: Number.parseInt(botValue, 10),
      match_type: matchType,
      match_value: matchValue || null,
      priority: Number.isNaN(priority) ? 0 : priority,
      is_active: isActive
    };

    if (connectorValue) {
      const connector = cachedConnectors.find(c => c.id === Number.parseInt(connectorValue, 10));
      payload.connector_id = Number.parseInt(connectorValue, 10);
      payload.connector_type = connector ? connector.connector_type : null;
    }

    await createRoutingRule(payload);
    form.reset();
    document.getElementById('routing-rule-active').checked = true;
    await loadRoutingRules();
    await loadRoutingEvents();
  });
}

async function fetchRoutingRules() {
  const resp = await fetch('/api/v1/routing/rules');
  return await resp.json();
}

async function createRoutingRule(data) {
  const resp = await fetch('/api/v1/routing/rules', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data)
  });
  return await resp.json();
}

async function deleteRoutingRule(id) {
  await fetch(`/api/v1/routing/rules/${id}`, { method: 'DELETE' });
}

async function fetchRoutingEvents() {
  const resp = await fetch('/api/v1/routing/events?limit=50');
  return await resp.json();
}

async function loadRoutingRules() {
  const list = document.getElementById('routing-rules-list');
  if (!list) return;
  const rules = await fetchRoutingRules();
  list.innerHTML = '';
  rules.sort((a, b) => b.priority - a.priority);
  rules.forEach((rule) => {
    const item = document.createElement('div');
    item.className = 'list-group-item d-flex justify-content-between align-items-center';
    const connectorLabel = rule.connector_id
      ? (cachedConnectors.find(c => c.id === rule.connector_id)?.name || `Connector ${rule.connector_id}`)
      : (rule.connector_type || 'Any connector');
    const botLabel = cachedBots.find(b => b.id === rule.bot_id)?.name || `Bot ${rule.bot_id}`;
    item.innerHTML = `
      <div>
        <div class="fw-semibold">${rule.name}</div>
        <div class="text-muted">
          ${connectorLabel} • ${botLabel} • ${rule.match_type}${rule.match_value ? `:${rule.match_value}` : ''} • P${rule.priority}
        </div>
      </div>
      <button class="btn btn-sm btn-outline-danger">Delete</button>
    `;
    item.querySelector('button').addEventListener('click', async () => {
      await deleteRoutingRule(rule.id);
      await loadRoutingRules();
    });
    list.appendChild(item);
  });
}

async function loadRoutingEvents() {
  const tableBody = document.querySelector('#routing-events-table tbody');
  if (!tableBody) return;
  const events = await fetchRoutingEvents();
  tableBody.innerHTML = '';
  events.forEach((event) => {
    const row = document.createElement('tr');
    row.innerHTML = `
      <td>${event.created_at || ''}</td>
      <td>${event.connector_type || event.connector_id || ''}</td>
      <td>${event.bot_id || ''}</td>
      <td>${event.status}</td>
      <td>${event.delivery_status}</td>
    `;
    tableBody.appendChild(row);
  });
}

async function getConnectors() {
  const resp = await fetch('/api/connectors');
  return await resp.json();
}

async function createConnector(data) {
  const resp = await fetch('/api/connectors/create', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data)
  });
  const created = await resp.json();
  cachedConnectors = [...cachedConnectors, created];
  renderRoutingConnectorOptions();
  return created;
}

async function updateConnector(id, data) {
  const resp = await fetch(`/api/connectors/${id}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data)
  });
  const updated = await resp.json();
  cachedConnectors = cachedConnectors.map(connector =>
    connector.id === id ? updated : connector
  );
  renderRoutingConnectorOptions();
  return updated;
}

async function deleteConnector(id) {
  const resp = await fetch(`/api/connectors/${id}`, { method: 'DELETE' });
  if (!resp.ok) {
    const error = await resp.json();
    throw new Error(error.detail || 'Failed to delete connector');
  }
  cachedConnectors = cachedConnectors.filter(connector => connector.id !== id);
  renderRoutingConnectorOptions();
}

async function testConnector(id) {
  const resp = await fetch(`/api/connectors/${id}/test`, { method: 'POST' });
  return await resp.json();
}

async function getConnectorStatus(id) {
  const resp = await fetch(`/api/connectors/${id}/status`);
  return await resp.json();
}

async function setConnectorWebhook(id, url) {
  const resp = await fetch(`/api/connectors/${id}/webhook`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ url })
  });
  return await resp.json();
}

function createConnectorElement(connector) {
  const card = document.createElement('div');
  card.className = 'card mb-3';
  const body = document.createElement('div');
  body.className = 'card-body';
  const header = document.createElement('h5');
  header.textContent = `${connector.name} (${connector.connector_type})`;
  const statusSpan = document.createElement('span');
  statusSpan.className = 'badge bg-secondary ms-2 connector-status';
  statusSpan.textContent = '...';
  header.appendChild(statusSpan);
  const idBadge = document.createElement('span');
  idBadge.className = 'badge bg-light text-dark ms-2';
  idBadge.textContent = `id ${connector.id}`;
  header.appendChild(idBadge);
  body.appendChild(header);

  const editBtn = document.createElement('button');
  editBtn.className = 'btn btn-sm btn-outline-secondary me-2';
  editBtn.textContent = 'Edit';
  editBtn.addEventListener('click', async () => {
    const newName = prompt('Connector name', connector.name);
    const newType = prompt('Connector type', connector.connector_type);
    let newConfig = prompt('Config (JSON)', JSON.stringify(connector.config || {}));
    if (newName && newType && newConfig != null) {
      try {
        newConfig = JSON.parse(newConfig);
      } catch (e) {
        alert('Config must be valid JSON');
        return;
      }
      const updated = await updateConnector(connector.id, {
        name: newName,
        connector_type: newType,
        config: newConfig
      });
      connector.name = updated.name;
      connector.connector_type = updated.connector_type;
      connector.config = updated.config;
      header.childNodes[0].nodeValue = `${updated.name} (${updated.connector_type})`;
    }
  });

  const deleteBtn = document.createElement('button');
  deleteBtn.className = 'btn btn-sm btn-danger me-2';
  deleteBtn.textContent = 'Delete';
  deleteBtn.addEventListener('click', async () => {
    if (!confirm(`Delete connector "${connector.name}"?`)) return;
    try {
      await deleteConnector(connector.id);
      card.remove();
      renderStatusTable(cachedConnectors);
    } catch (err) {
      alert(err.message);
    }
  });

  const testBtn = document.createElement('button');
  testBtn.className = 'btn btn-sm btn-outline-primary';
  testBtn.textContent = 'Test';
  testBtn.addEventListener('click', async () => {
    const result = await testConnector(connector.id);
    statusSpan.textContent = result.status;
  });

  const webhookBtn = document.createElement('button');
  webhookBtn.className = 'btn btn-sm btn-outline-success ms-2';
  webhookBtn.textContent = 'Set Webhook';
  webhookBtn.addEventListener('click', async () => {
    const url = prompt('Webhook URL');
    if (!url) return;
    const result = await setConnectorWebhook(connector.id, url);
    alert(result.status === 'success' ? 'Webhook set' : 'Webhook not set');
  });

  body.appendChild(editBtn);
  body.appendChild(deleteBtn);
  body.appendChild(testBtn);
  body.appendChild(webhookBtn);
  card.appendChild(body);
  return card;
}

function startStatusPolling() {
  fetchStatuses();
  setInterval(fetchStatuses, 10000);
}

async function fetchStatuses() {
  const connectors = await getConnectors();
  renderStatusTable(connectors);
  const cards = document.querySelectorAll('.connector-status');
  for (const connector of connectors) {
    try {
      const status = await getConnectorStatus(connector.id);
      const card = Array.from(cards).find(c => c.closest('.card').querySelector('h5').textContent.startsWith(connector.name));
      if (card) {
        card.textContent = status.status;
      }
    } catch (e) {
      const card = Array.from(cards).find(c => c.closest('.card').querySelector('h5').textContent.startsWith(connector.name));
      if (card) {
        card.textContent = 'unknown';
      }
    }
  }
}

function renderStatusTable(connectors) {
  const tbody = document.querySelector('#connector-status-table tbody');
  if (!tbody) return;
  tbody.innerHTML = '';
  connectors.forEach(async (c) => {
    let status;
    try {
      status = await getConnectorStatus(c.id);
    } catch (e) {
      status = { status: 'unknown' };
    }
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td>${c.name} (${c.connector_type})</td>
      <td>${status.status}</td>
      <td>${status.last_message_sent || ''}</td>
      <td>${status.last_message_received || ''}</td>
    `;
    tbody.appendChild(tr);
  });
}

function renderWebhookUrls() {
  const origin = window.location.origin;
  const slackInput = document.getElementById('slack-webhook-url');
  const googleInput = document.getElementById('google-chat-webhook-url');
  const webhookInput = document.getElementById('generic-webhook-url');
  if (slackInput) {
    slackInput.value = `${origin}/api/v1/connectors/webhooks/slack/{connector_id}`;
  }
  if (googleInput) {
    googleInput.value = `${origin}/api/v1/connectors/webhooks/google_chat/{connector_id}`;
  }
  if (webhookInput) {
    webhookInput.value = `${origin}/api/v1/connectors/webhooks/webhook/{connector_id}`;
  }
  const discordInput = document.getElementById('discord-webhook-url');
  const teamsInput = document.getElementById('teams-webhook-url');
  const telegramInput = document.getElementById('telegram-webhook-url');
  if (discordInput) {
    discordInput.value = `${origin}/api/v1/connectors/webhooks/discord/{connector_id}`;
  }
  if (teamsInput) {
    teamsInput.value = `${origin}/api/v1/connectors/webhooks/teams/{connector_id}`;
  }
  if (telegramInput) {
    telegramInput.value = `${origin}/api/v1/connectors/webhooks/telegram/{connector_id}`;
  }
  const whatsappInput = document.getElementById('whatsapp-webhook-url');
  if (whatsappInput) {
    whatsappInput.value = `${origin}/api/v1/connectors/webhooks/whatsapp/{connector_id}`;
  }
  const jiraInput = document.getElementById('jira-webhook-url');
  if (jiraInput) {
    jiraInput.value = `${origin}/api/v1/connectors/webhooks/jira/{connector_id}`;
  }
  const facebookInput = document.getElementById('facebook-webhook-url');
  if (facebookInput) {
    facebookInput.value = `${origin}/api/v1/connectors/webhooks/facebook/{connector_id}`;
  }
  const pinterestInput = document.getElementById('pinterest-webhook-url');
  if (pinterestInput) {
    pinterestInput.value = `${origin}/api/v1/connectors/webhooks/pinterest/{connector_id}`;
  }
  const linkedinInput = document.getElementById('linkedin-webhook-url');
  if (linkedinInput) {
    linkedinInput.value = `${origin}/api/v1/connectors/webhooks/linkedin/{connector_id}`;
  }
  const redditInput = document.getElementById('reddit-webhook-url');
  if (redditInput) {
    redditInput.value = `${origin}/api/v1/connectors/webhooks/reddit/{connector_id}`;
  }
  const twitterInput = document.getElementById('twitter-webhook-url');
  if (twitterInput) {
    twitterInput.value = `${origin}/api/v1/connectors/webhooks/twitter/{connector_id}`;
  }
  const instagramInput = document.getElementById('instagram-webhook-url');
  if (instagramInput) {
    instagramInput.value = `${origin}/api/v1/connectors/webhooks/instagram/{connector_id}`;
  }
}

function enableCopyButtons() {
  document.querySelectorAll('[data-copy-target]').forEach((btn) => {
    btn.addEventListener('click', () => {
      const targetId = btn.getAttribute('data-copy-target');
      const input = document.getElementById(targetId);
      if (!input) return;
      input.select();
      input.setSelectionRange(0, 99999);
      navigator.clipboard.writeText(input.value);
    });
  });
}
