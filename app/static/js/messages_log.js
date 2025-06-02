document.addEventListener('DOMContentLoaded', () => {
  populateSelects();
  document.getElementById('applyFilters').addEventListener('click', fetchMessagesAndRender);
  document.getElementById('searchFilter').addEventListener('input', fetchMessagesAndRender);
  fetchMessagesAndRender();
});

async function fetchMessagesAndRender() {
  const params = new URLSearchParams();
  const connector = document.getElementById('connectorFilter').value;
  const channel = document.getElementById('channelFilter').value;
  const bot = document.getElementById('botFilter').value;
  const q = document.getElementById('searchFilter').value;
  const start = document.getElementById('startTime').value;
  const end = document.getElementById('endTime').value;

  if (connector) params.append('connector_id', connector);
  if (channel) params.append('channel_id', channel);
  if (bot) params.append('bot_id', bot);
  if (q) params.append('q', q);
  if (start) params.append('start', start);
  if (end) params.append('end', end);

  const resp = await fetch('/api/v1/messages?' + params.toString());
  if (!resp.ok) {
    console.error('Failed to fetch messages');
    return;
  }
  const messages = await resp.json();

  const messagesContainer = document.getElementById('messages-log');
  messagesContainer.innerHTML = '';
  for (const message of messages) {
    const messageElement = createMessageElement(message);
    messagesContainer.appendChild(messageElement);
  }
}

function createMessageElement(message) {
  const messageElement = document.createElement('div');
  messageElement.classList.add('message');

  const contentElement = document.createElement('p');
  contentElement.textContent = message.content;
  messageElement.appendChild(contentElement);

  const timestampElement = document.createElement('p');
  timestampElement.classList.add('timestamp');
  timestampElement.textContent = message.timestamp;
  messageElement.appendChild(timestampElement);

  return messageElement;
}

async function populateSelects() {
  await Promise.all([
    populateGenericSelect('/api/v1/channels/', 'channelFilter'),
    populateGenericSelect('/api/v1/connectors/', 'connectorFilter'),
    populateGenericSelect('/api/v1/bots/', 'botFilter'),
  ]);
}

async function populateGenericSelect(url, elementId) {
  try {
    const resp = await fetch(url);
    if (!resp.ok) {
      return;
    }
    const items = await resp.json();
    const select = document.getElementById(elementId);
    if (!select) return;
    select.innerHTML = '<option value="">All</option>';
    for (const item of items) {
      const opt = document.createElement('option');
      opt.value = item.id;
      opt.textContent = item.name;
      select.appendChild(opt);
    }
  } catch (e) {
    console.error('Failed to load ' + elementId, e);
  }
}

