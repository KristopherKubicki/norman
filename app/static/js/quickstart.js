let quickstartBotId = null;

function setStatus(el, message, isError = false) {
  el.textContent = message;
  el.classList.toggle('text-danger', isError);
}

document.addEventListener('DOMContentLoaded', () => {
  const botForm = document.getElementById('quickstart-bot-form');
  const botName = document.getElementById('quickstart-bot-name');
  const botDescription = document.getElementById('quickstart-bot-description');
  const botSummary = document.getElementById('quickstart-bot-summary');
  const sendButton = document.getElementById('quickstart-send');
  const messageForm = document.getElementById('quickstart-message-form');
  const messageText = document.getElementById('quickstart-message-text');
  const responseBox = document.getElementById('quickstart-response');
  const errorBox = document.getElementById('quickstart-error');
  const statusBox = document.getElementById('quickstart-message-status');
  const modelBadge = document.getElementById('quickstart-model');

  botForm.addEventListener('submit', async (event) => {
    event.preventDefault();
    errorBox.textContent = '';
    setStatus(statusBox, '');

    const payload = {
      name: botName.value.trim(),
      description: botDescription.value.trim(),
      gpt_model: 'gpt-5-mini',
    };

    if (!payload.name) {
      setStatus(statusBox, 'Bot name is required.', true);
      return;
    }

    try {
      const res = await fetch('/api/bots/create', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      if (!res.ok) {
        throw new Error('Failed to create bot');
      }
      const data = await res.json();
      quickstartBotId = data.id;
      botSummary.textContent = `${data.name} (id ${data.id})`;
      sendButton.disabled = false;
      setStatus(statusBox, 'Bot created. You can send a message.');
    } catch (err) {
      setStatus(statusBox, 'Could not create bot.', true);
    }
  });

  messageForm.addEventListener('submit', async (event) => {
    event.preventDefault();
    errorBox.textContent = '';
    if (!quickstartBotId) {
      setStatus(statusBox, 'Create a bot first.', true);
      return;
    }
    const content = messageText.value.trim();
    if (!content) {
      setStatus(statusBox, 'Message is required.', true);
      return;
    }

    sendButton.disabled = true;
    responseBox.textContent = 'Thinking...';
    setStatus(statusBox, 'Sending message...');

    try {
      const res = await fetch(`/api/bots/${quickstartBotId}/messages`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ content }),
      });
      if (!res.ok) {
        throw new Error('Failed to send message');
      }
      const data = await res.json();
      if (data.status !== 'success') {
        throw new Error(data.message || 'Message failed');
      }
      const interaction = data.data?.interaction;
      const message = data.data?.message;
      responseBox.textContent = message?.text || 'No response available.';
      modelBadge.textContent = interaction?.gpt_model || '';
      setStatus(statusBox, 'Message sent.');
    } catch (err) {
      responseBox.textContent = 'No response available.';
      errorBox.textContent = 'Failed to get a response. Check your OpenAI API key.';
      setStatus(statusBox, 'Message failed.', true);
    } finally {
      sendButton.disabled = false;
    }
  });
});
