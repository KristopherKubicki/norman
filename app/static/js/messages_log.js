let selectedChannelId = null;

async function loadChannels() {
  const resp = await fetch('/api/v1/channels');
  if (!resp.ok) return;
  const channels = await resp.json();
  const container = document.querySelector('.channels-container');
  container.innerHTML = '';
  channels.forEach(ch => {
    const item = document.createElement('a');
    item.classList.add('list-group-item', 'list-group-item-action');
    item.textContent = ch.name;
    item.dataset.channelId = ch.id;
    item.addEventListener('click', () => {
      selectedChannelId = ch.id;
      document.querySelectorAll('.channels-container a').forEach(el => el.classList.remove('active'));
      item.classList.add('active');
      loadMessages(ch.id);
    });
    container.appendChild(item);
  });
  if (channels.length) {
    selectedChannelId = channels[0].id;
    container.firstChild.classList.add('active');
    loadMessages(selectedChannelId);
  }
}

async function loadMessages(channelId) {
  const resp = await fetch(`/api/v1/channels/${channelId}/messages`);
  if (!resp.ok) return;
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
  if (!selectedChannelId || !input.value.trim()) return;
  await fetch(`/api/v1/channels/${selectedChannelId}/messages`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ content: input.value.trim() })
  });
  input.value = '';
  loadMessages(selectedChannelId);
}

document.addEventListener('DOMContentLoaded', () => {
  loadChannels();
  document.getElementById('sendButton').addEventListener('click', sendMessage);
});
