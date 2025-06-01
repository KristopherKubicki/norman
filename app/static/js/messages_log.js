document.addEventListener('DOMContentLoaded', () => {
  // Fetch messages and render them in the messages container
  fetchMessagesAndRender();
  populateChannels();
});

function fetchMessagesAndRender() {
  // Replace this with the actual API call to fetch messages
  const fakeMessages = [
    { id: 1, content: 'Message 1', timestamp: '2023-01-01 10:00:00' },
    { id: 2, content: 'Message 2', timestamp: '2023-01-01 10:05:00' },
  ];

  const messagesContainer = document.getElementById('messages-log');
  messagesContainer.innerHTML = '';

  for (const message of fakeMessages) {
    const messageElement = createMessageElement(message);
    messagesContainer.appendChild(messageElement);
  }
}

async function populateChannels() {
  try {
    const resp = await fetch('/api/v1/channels/');
    if (!resp.ok) {
      throw new Error('Failed to fetch channels');
    }
    const channels = await resp.json();
    const select = document.getElementById('channelSelect');
    select.innerHTML = '';
    for (const channel of channels) {
      const option = document.createElement('option');
      option.value = channel.id;
      option.textContent = channel.name;
      select.appendChild(option);
    }
  } catch (err) {
    console.error('Error loading channels', err);
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

