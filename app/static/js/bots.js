
let selectedBotId = null;
const sendButton = document.getElementById('send-message');
let botsCache = [];

function setStatus(message, type = 'info') {
  const status = document.getElementById('bots-status');
  if (!status) return;
  if (!message) {
    status.classList.add('d-none');
    status.textContent = '';
    return;
  }
  status.className = `alert alert-${type}`;
  status.textContent = message;
}

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

function updateCount(count) {
  const el = document.getElementById('bots-count');
  if (el) el.textContent = count;
}

function filterBots(query) {
  const filtered = botsCache.filter(bot =>
    bot.name.toLowerCase().includes(query.toLowerCase())
  );
  renderBots(filtered);
}

document.addEventListener('DOMContentLoaded', () => {
  const sendButton = document.getElementById('send-message');
  // Fetch bots and render them in the bots container
  fetchBotsAndRender();

  // Set up handler for saving edits
  const saveBtn = document.getElementById('save-bot-changes');
  if (saveBtn) {
    saveBtn.addEventListener('click', async () => {
      if (!selectedBotId) return;
      const nameInput = document.getElementById('edit-bot-name');
      clearError(nameInput);
      const descriptionValue = document.getElementById('edit-bot-description').value.trim();
      const modelValue = document.getElementById('edit-bot-model').value.trim();
      const data = {
        name: nameInput.value.trim(),
        description: descriptionValue
      };
      if (modelValue) {
        data.gpt_model = modelValue;
      }
      if (!data.name) {
        showError(nameInput, 'Name is required');
        return;
      }
      const updated = await updateBot(selectedBotId, data);
      if (updated) {
        fetchBotsAndRender();
        const modal = bootstrap.Modal.getInstance(document.getElementById('editBotModal'));
        modal.hide();
      }
    });
  }

  // Add event listener for the add-bot-form
  const addBotForm = document.getElementById("add-bot-form");
  if (addBotForm) {
    addBotForm.addEventListener("submit", async (event) => {
      event.preventDefault();

      const nameInput = document.getElementById("bot-name");
      const descriptionInput = document.getElementById("bot-description");

      clearError(nameInput);

      const name = nameInput.value.trim();
      const description = descriptionInput.value.trim();

      if (!name) {
        showError(nameInput, 'Name is required');
        return;
      }

      try {
        let bot;
        try {
          bot = await addBot(name, description, "gpt-5-mini");
        } catch (err) {
          if (String(err.message || '').includes('Invalid GPT model')) {
            bot = await addBot(name, description, null);
          } else {
            throw err;
          }
        }
        if (!bot || !bot.id) {
          setStatus('Failed to add bot. Check your session or required fields.', 'danger');
          return;
        }
        await fetchBotsAndRender(bot.id);
        setStatus(`Bot "${bot.name}" created.`, 'success');
      } catch (err) {
        setStatus(err.message || 'Failed to add bot.', 'danger');
        return;
      }

      nameInput.value = "";
      descriptionInput.value = "";
    });
  }
  sendButton.addEventListener("click", async (event) => {
    event.preventDefault();

    // Disable the button
    sendButton.disabled = true;

    // reset the enter dialog
    const textarea = document.querySelector('textarea');
    textarea.style.height = 'auto';

    const spinner = document.getElementById('spinner');
    const selectedBotNameElement = document.getElementById('selected-bot-name');
    const content = textarea.value.trim();

    spinner.style.display = 'inline-block';

    if (selectedBotNameElement.innerText !== 'None' && content) {
      const messagesContainer = document.querySelector('.messages-container');
      const placeholder = document.createElement('div');
      placeholder.className = 'message assistant placeholder-message';
      placeholder.textContent = 'Thinking...';
      placeholder.style.height = textarea.scrollHeight + 'px';
      messagesContainer.appendChild(placeholder);
      messagesContainer.scrollTop = messagesContainer.scrollHeight;
      const bot_id = selectedBotNameElement.dataset.botId;
      await sendMessage(bot_id, content);
      textarea.value = '';
      textarea.style.height = "auto";
      fetchMessagesAndRender(bot_id);
    }

    // Re-enable the button
    sendButton.disabled = false;
    spinner.style.display = 'none';
  });

  const botSearch = document.getElementById('botSearch');
  if (botSearch) {
    botSearch.addEventListener('input', (event) => {
      filterBots(event.target.value);
    });
  }

  const textarea = document.getElementById('input-message');
  if (textarea) {
    textarea.addEventListener('input', () => {
      textarea.style.height = 'auto';
      textarea.style.height = Math.min(textarea.scrollHeight, 300) + 'px';
    });
    textarea.dispatchEvent(new Event('input'));

    textarea.addEventListener('keydown', function (e) {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        sendButton.click();
      }
    });
  }
});

function getRequestedBotId() {
  const params = new URLSearchParams(window.location.search);
  const value = params.get('bot_id');
  if (!value) return null;
  const parsed = Number.parseInt(value, 10);
  return Number.isNaN(parsed) ? null : parsed;
}

function isDemoView() {
  const params = new URLSearchParams(window.location.search);
  return params.get('demo') === '1';
}

function highlightLatestAssistant(messagesContainer) {
  const assistantMessages = messagesContainer.querySelectorAll('.message.assistant');
  if (!assistantMessages.length) return;
  const latest = assistantMessages[assistantMessages.length - 1];
  latest.classList.add('message-highlight');
  latest.scrollIntoView({ behavior: 'smooth', block: 'end' });
  setTimeout(() => {
    latest.classList.remove('message-highlight');
  }, 2400);
}

function selectBotById(botId) {
  const botElement = document.querySelector(`.bot-item[data-bot-id="${botId}"]`);
  if (botElement) {
    botElement.click();
  }
}



async function fetchBotsAndRender(preselectId = null) {
  const response = await fetch("/api/bots");
  if (!response.ok) {
    setStatus('Unable to load bots. Please refresh or log in again.', 'danger');
    return;
  }
  const bots = await response.json();
  botsCache = bots;
  updateCount(bots.length);

  if (!bots.length) {
    setStatus('No bots yet. Create one on the left.', 'info');
    renderBots([]);
  } else {
    setStatus('');
    renderBots(bots);
  }
  const requestedBotId = preselectId ?? getRequestedBotId();
  if (requestedBotId) {
    selectBotById(requestedBotId);
  }
}

function renderBots(bots) {
  const botsContainer = document.querySelector('.bots-container');
  botsContainer.innerHTML = '';
  if (!bots.length) {
    const empty = document.createElement('div');
    empty.className = 'list-group-item text-muted';
    empty.textContent = 'No bots created yet.';
    botsContainer.appendChild(empty);
    return;
  }
  for (const bot of bots) {
    const botElement = createBotElement(bot);
    botsContainer.appendChild(botElement);
  }
}

function createBotElement(bot) {
  const botElement = document.createElement('div');
  botElement.classList.add('list-group-item', 'bot-item');
  botElement.dataset.botId = bot.id;
  botElement.setAttribute('role', 'button');
  botElement.setAttribute('tabindex', '0');

  const nameElement = document.createElement('span');
  nameElement.className = 'bot-name';
  nameElement.textContent = bot.name;

  const metaElement = document.createElement('span');
  metaElement.className = 'small text-muted';
  metaElement.textContent = bot.gpt_model || 'model not set';

  const actions = document.createElement('div');
  actions.className = 'bot-actions';

  const editButton = document.createElement('button');
  editButton.className = 'btn btn-sm btn-secondary';
  editButton.type = 'button';
  editButton.textContent = 'Edit';
  editButton.addEventListener('click', (e) => {
    e.stopPropagation();
    openEditModal(bot);
  });

  const deleteButton = document.createElement('button');
  deleteButton.className = 'btn btn-sm btn-danger';
  deleteButton.type = 'button';
  deleteButton.textContent = 'Delete';
  deleteButton.addEventListener('click', async (e) => {
    e.stopPropagation();
    if (!confirm(`Delete bot "${bot.name}"?`)) return;
    try {
      await deleteBot(bot.id);
      botElement.remove();
      botsCache = botsCache.filter(item => item.id !== bot.id);
      updateCount(botsCache.length);
      setStatus('Bot deleted.', 'success');
    } catch (err) {
      setStatus(err.message || 'Failed to delete bot.', 'danger');
    }
  });

  actions.appendChild(editButton);
  actions.appendChild(deleteButton);

  botElement.appendChild(nameElement);
  botElement.appendChild(metaElement);
  botElement.appendChild(actions);

  const activate = () => {
    const selectedBotNameElement = document.getElementById('selected-bot-name');
    const selectedBotMeta = document.getElementById('selected-bot-meta');
    selectedBotId = bot.id;
    selectedBotNameElement.innerText = bot.name;
    selectedBotNameElement.setAttribute('data-bot-id', bot.id);
    if (selectedBotMeta) {
      selectedBotMeta.textContent = bot.description || bot.gpt_model || 'No description';
    }
    fetchMessagesAndRender(bot.id);
    document.getElementById('send-message').removeAttribute('disabled');
    document.getElementById('input-message').removeAttribute('disabled');
    document.getElementById('input-message').placeholder = 'Enter to send, Shift+Enter for newline';

    document.querySelectorAll('.bot-item').forEach(item => item.classList.remove('active'));
    botElement.classList.add('active');
  };

  // Add click event listener to fetch and display messages
  botElement.addEventListener('click', activate);
  botElement.addEventListener('keydown', (event) => {
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault();
      activate();
    }
  });


  return botElement;
}


async function addBot(name, description, model) {
  const payload = { name, description };
  if (model) {
    payload.gpt_model = model;
  }
  const response = await fetch("/api/bots/create", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  });
  const bot = await response.json();
  if (!response.ok) {
    throw new Error(bot.detail || bot.message || 'Failed to create bot');
  }
  return bot;
}

async function deleteBot(botId) {
  const response = await fetch(`/api/bots/${botId}`, {
    method: "DELETE",
  });
  const bot = await response.json();
  if (!response.ok) {
    throw new Error(bot.detail || bot.message || "Failed to delete bot");
  }
  return bot;
}


async function updateBot(botId, botData) {
  const response = await fetch(`/api/bots/${botId}`, {
    method: "PUT",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(botData),
  });
  const bot = await response.json();
  return bot;
}


async function fetchMessagesAndRender(bot_id) {
  const response = await fetch(`/api/bots/${bot_id}/messages`);
  const messages = await response.json();

  const messagesContainer = document.querySelector('.messages-container');
  messagesContainer.innerHTML = '';

  for (const message of messages) {
    const messageElement = createMessageElement(message);
    messagesContainer.appendChild(messageElement);
  }
  messagesContainer.scrollTop = messagesContainer.scrollHeight;
  if (isDemoView()) {
    highlightLatestAssistant(messagesContainer);
  }


}

async function sendMessage(bot_id, content) {
  const response = await fetch(`/api/bots/${bot_id}/messages`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ content }),
  });
  const message = await response.json();
  return message;
}


function createMessageElement(message) {
  const messageElement = document.createElement('div');
  messageElement.className = 'message ' + message.source;
  marked.setOptions({ mangle: false, headerIds: false });

  const contentElement = document.createElement('p');
  contentElement.className = 'message-content';
  const messageWithTabsAndNewlinesReplaced = message.text.replace(/\t/g, "&nbsp;&nbsp;&nbsp;&nbsp;").replace(/\n/g, "<br/>");
  const messageHTML = marked.marked(messageWithTabsAndNewlinesReplaced);
  contentElement.innerHTML = messageHTML;
  messageElement.appendChild(contentElement);

  const timestampElement = document.createElement('p');
  timestampElement.className = 'message-timestamp';
  timestampElement.innerText = message.created_at; // Changed from 'timestamp' to 'created_at'

  const copyButton = document.createElement('button');
  copyButton.className = 'copy-button';
  copyButton.textContent = 'Copy';
  copyButton.addEventListener('click', function() {
    navigator.clipboard.writeText(message.text);
  });

  messageElement.appendChild(timestampElement);
  messageElement.appendChild(copyButton);
  messageElement.appendChild(document.createElement('hr'));

  return messageElement;
}

function openEditModal(bot) {
  selectedBotId = bot.id;
  document.getElementById('edit-bot-name').value = bot.name;
  document.getElementById('edit-bot-description').value = bot.description || '';
  document.getElementById('edit-bot-model').value = bot.gpt_model || '';
  document.getElementById('edit-bot-enabled').checked = bot.enabled;
  const modalEl = document.getElementById('editBotModal');
  const modal = new bootstrap.Modal(modalEl);
  modal.show();
}
