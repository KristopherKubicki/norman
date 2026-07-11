
let selectedBotId = null;
const sendButton = document.getElementById('send-message');
let botsCache = [];
let activeBotsMobilePane = 'roster';
let botsMobilePaneMedia = null;
const BOTS_MOBILE_PANE_KEY = 'norman.mobile.bots.pane.v1';

function updateSelectedBotSummary(bot = null) {
  const selectedBotNameElement = document.getElementById('selected-bot-name');
  const selectedBotMeta = document.getElementById('selected-bot-meta');
  const selectedBotState = document.getElementById('selected-bot-state');
  const textarea = document.getElementById('input-message');
  const send = document.getElementById('send-message');

  if (!selectedBotNameElement || !selectedBotMeta || !selectedBotState) return;

  if (!bot) {
    selectedBotNameElement.innerText = 'No session selected';
    selectedBotNameElement.removeAttribute('data-bot-id');
    selectedBotMeta.textContent = 'Choose a session from the left to continue the thread.';
    selectedBotState.textContent = 'Idle';
    if (textarea) {
      textarea.setAttribute('disabled', 'disabled');
      textarea.placeholder = 'Choose a session to start writing…';
    }
    if (send) {
      send.setAttribute('disabled', 'disabled');
    }
    return;
  }

  const details = [
    bot.description,
    bot.gpt_model ? `Model ${bot.gpt_model}` : '',
    bot.enabled === false ? 'Disabled' : 'Ready',
  ].filter(Boolean);

  selectedBotNameElement.innerText = bot.name;
  selectedBotNameElement.setAttribute('data-bot-id', bot.id);
  selectedBotMeta.textContent = details.join(' · ') || 'Ready for the next turn.';
  selectedBotState.textContent = bot.enabled === false ? 'Paused' : 'Live';
  if (textarea) {
    textarea.removeAttribute('disabled');
    textarea.placeholder = 'Enter to send, Shift+Enter for newline';
  }
  if (send) {
    send.removeAttribute('disabled');
  }
}

function readStoredBotsMobilePane() {
  try {
    const value = (localStorage.getItem(BOTS_MOBILE_PANE_KEY) || '').trim();
    return ['chat', 'roster'].includes(value) ? value : null;
  } catch (err) {
    return null;
  }
}

function writeStoredBotsMobilePane(pane) {
  try {
    localStorage.setItem(BOTS_MOBILE_PANE_KEY, pane);
  } catch (err) {
    // ignore storage errors
  }
}

function isCompactBotsViewport() {
  return Boolean(botsMobilePaneMedia?.matches);
}

function setBotsMobilePane(pane) {
  const page = document.querySelector('.bots-page');
  if (!page) return;
  activeBotsMobilePane = pane;
  writeStoredBotsMobilePane(pane);
  page.dataset.mobilePane = pane;
  document.querySelectorAll('[data-bots-pane]').forEach((btn) => {
    btn.classList.toggle('is-active', btn.getAttribute('data-bots-pane') === pane);
  });
}

function initBotsMobilePaneSwitcher() {
  const page = document.querySelector('.bots-page');
  const buttons = Array.from(document.querySelectorAll('[data-bots-pane]'));
  if (!page || !buttons.length) return;

  const savedPane = readStoredBotsMobilePane();
  if (savedPane) {
    activeBotsMobilePane = savedPane;
  }

  botsMobilePaneMedia = window.matchMedia('(max-width: 991px)');
  setBotsMobilePane(activeBotsMobilePane);

  buttons.forEach((btn) => {
    btn.addEventListener('click', () => {
      setBotsMobilePane(btn.getAttribute('data-bots-pane') || 'chat');
    });
  });

  const syncPaneMode = () => {
    if (isCompactBotsViewport()) {
      page.dataset.mobilePane = activeBotsMobilePane;
      return;
    }
    page.removeAttribute('data-mobile-pane');
  };
  syncPaneMode();
  if (typeof botsMobilePaneMedia.addEventListener === 'function') {
    botsMobilePaneMedia.addEventListener('change', syncPaneMode);
  } else if (typeof botsMobilePaneMedia.addListener === 'function') {
    botsMobilePaneMedia.addListener(syncPaneMode);
  }
}

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
  initBotsMobilePaneSwitcher();
  updateSelectedBotSummary(null);
  // Fetch bots and render them in the bots container
  fetchBotsAndRender();

  const mobileSelect = document.getElementById('bots-mobile-select');
  if (mobileSelect) {
    mobileSelect.addEventListener('change', (event) => {
      const value = event.target.value;
      if (value) selectBotById(value);
    });
  }

  // Set up handler for saving edits
  const saveBtn = document.getElementById('save-bot-changes');
  if (saveBtn) {
    saveBtn.addEventListener('click', async () => {
      if (!selectedBotId) return;
      const nameInput = document.getElementById('edit-bot-name');
      clearError(nameInput);
      const descriptionValue = document.getElementById('edit-bot-description').value.trim();
      const modelValue = document.getElementById('edit-bot-model').value.trim();
      const enabledValue = document.getElementById('edit-bot-enabled').checked;
      const data = {
        name: nameInput.value.trim(),
        description: descriptionValue,
        enabled: enabledValue
      };
      if (modelValue) {
        data.gpt_model = modelValue;
      }
      if (!data.name) {
        showError(nameInput, 'Name is required');
        return;
      }
      try {
        const updated = await updateBot(selectedBotId, data);
        if (updated) {
          fetchBotsAndRender();
          const modal = bootstrap.Modal.getInstance(document.getElementById('editBotModal'));
          modal.hide();
          setStatus(`Bot "${updated.name || data.name}" updated.`, 'success');
        }
      } catch (err) {
        setStatus(err.message || 'Failed to update bot.', 'danger');
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
          bot = await addBot(name, description, "gpt-5.5");
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

    const textarea = document.getElementById('input-message');
    if (!textarea) {
      sendButton.disabled = false;
      return;
    }
    textarea.style.height = 'auto';

    const spinner = document.getElementById('spinner');
    const selectedBotNameElement = document.getElementById('selected-bot-name');
    const content = textarea.value.trim();

    spinner.style.display = 'inline-block';

    const bot_id = selectedBotNameElement?.dataset?.botId;
    if (bot_id && content) {
      const messagesContainer = document.querySelector('.messages-container');
      const placeholder = document.createElement('div');
      placeholder.className = 'message assistant placeholder-message';
      const placeholderSource = document.createElement('span');
      placeholderSource.className = 'message-source';
      placeholderSource.textContent = 'Bot';
      const placeholderContent = document.createElement('span');
      placeholderContent.className = 'message-content';
      placeholderContent.textContent = 'Thinking...';
      const placeholderTime = document.createElement('span');
      placeholderTime.className = 'message-timestamp';
      placeholderTime.textContent = '...';
      const placeholderMeta = document.createElement('span');
      placeholderMeta.className = 'message-meta';
      placeholderMeta.appendChild(placeholderTime);
      placeholder.appendChild(placeholderSource);
      placeholder.appendChild(placeholderContent);
      placeholder.appendChild(placeholderMeta);
      placeholder.style.height = textarea.scrollHeight + 'px';
      messagesContainer.appendChild(placeholder);
      messagesContainer.scrollTop = messagesContainer.scrollHeight;
      try {
        const result = await sendMessage(bot_id, content);
        if (result?.data?.message) {
          const assistantMessage = createMessageElement(result.data.message);
          messagesContainer.appendChild(assistantMessage);
          messagesContainer.scrollTop = messagesContainer.scrollHeight;
        }
      } catch (err) {
        const messageText = err.message || 'Failed to send message.';
        setStatus(messageText, 'danger');
        placeholder.textContent = messageText;
        placeholder.classList.add('message-error');
        fetchMessagesAndRender(bot_id);
        sendButton.disabled = false;
        spinner.style.display = 'none';
        return;
      }
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
  const response = await fetch("/api/bots", { cache: "no-store" });
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
    if (isCompactBotsViewport()) {
      setBotsMobilePane('roster');
    }
  } else {
    setStatus('');
    renderBots(bots);
    if (isCompactBotsViewport() && !selectedBotId && !preselectId) {
      setBotsMobilePane('roster');
    }
  }
  const requestedBotId = preselectId ?? getRequestedBotId();
  if (requestedBotId) {
    selectBotById(requestedBotId);
  }
}

function renderBots(bots) {
  const botsContainer = document.querySelector('.bots-container');
  botsContainer.innerHTML = '';
  renderBotsMobileSelect(botsCache);
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

function renderBotsMobileSelect(bots) {
  const select = document.getElementById('bots-mobile-select');
  if (!select) return;
  select.innerHTML = '';

  const placeholder = document.createElement('option');
  placeholder.value = '';
  placeholder.textContent = bots.length ? 'Select bot...' : 'No bots yet';
  placeholder.disabled = true;
  placeholder.selected = !selectedBotId;
  select.appendChild(placeholder);

  for (const bot of bots) {
    const opt = document.createElement('option');
    opt.value = bot.id;
    opt.textContent = bot.name;
    select.appendChild(opt);
  }

  if (selectedBotId) {
    select.value = String(selectedBotId);
  }
}

function createBotElement(bot) {
  const botElement = document.createElement('div');
  botElement.classList.add('list-group-item', 'bot-item');
  botElement.dataset.botId = bot.id;
  botElement.setAttribute('role', 'button');
  botElement.setAttribute('tabindex', '0');

  const info = document.createElement('div');
  info.className = 'bot-info';

  const nameElement = document.createElement('span');
  nameElement.className = 'bot-name';
  nameElement.textContent = bot.name;

  const metaElement = document.createElement('span');
  metaElement.className = 'bot-meta';
  metaElement.textContent = bot.description || bot.gpt_model || 'Ready for the next turn';

  const modelElement = document.createElement('span');
  modelElement.className = 'bot-model';
  modelElement.textContent = bot.gpt_model || (bot.enabled === false ? 'paused' : 'session');

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
      if (selectedBotId === bot.id) {
        selectedBotId = null;
        const mobileSelect = document.getElementById('bots-mobile-select');
        if (mobileSelect) mobileSelect.value = '';
        updateSelectedBotSummary(null);
        const messagesContainer = document.querySelector('.messages-container');
        if (messagesContainer) messagesContainer.innerHTML = '';
      }
      await fetchBotsAndRender();
      setStatus('Bot deleted.', 'success');
    } catch (err) {
      setStatus(err.message || 'Failed to delete bot.', 'danger');
    }
  });

  actions.appendChild(editButton);
  actions.appendChild(deleteButton);

  info.appendChild(nameElement);
  info.appendChild(metaElement);
  info.appendChild(modelElement);
  botElement.appendChild(info);
  botElement.appendChild(actions);

  const activate = () => {
    selectedBotId = bot.id;
    const mobileSelect = document.getElementById('bots-mobile-select');
    if (mobileSelect) mobileSelect.value = String(bot.id);
    updateSelectedBotSummary(bot);
    fetchMessagesAndRender(bot.id);

    document.querySelectorAll('.bot-item').forEach(item => item.classList.remove('active'));
    botElement.classList.add('active');
    if (isCompactBotsViewport()) {
      setBotsMobilePane('chat');
    }
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
  let bot = {};
  try {
    bot = await response.json();
  } catch (err) {
    // non-JSON error (e.g., rate limit HTML/text)
  }
  if (!response.ok) {
    if (response.status === 429) {
      throw new Error('Too many requests. Please wait a moment and try again.');
    }
    throw new Error(bot.detail || bot.message || 'Failed to create bot');
  }
  return bot;
}

async function deleteBot(botId) {
  const response = await fetch(`/api/bots/${botId}`, {
    method: "DELETE",
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(payload.detail || payload.message || "Failed to delete bot");
  }
  if (payload.status && payload.status !== 'success') {
    throw new Error(payload.message || "Failed to delete bot");
  }
  return payload;
}


async function updateBot(botId, botData) {
  const response = await fetch(`/api/bots/${botId}`, {
    method: "PUT",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(botData),
  });
  const bot = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(bot.detail || bot.message || 'Failed to update bot');
  }
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
  const message = await response.json().catch(() => ({}));
  if (!response.ok) {
    if (response.status === 429) {
      throw new Error('Rate limited. Try again in a few seconds.');
    }
    throw new Error(message.detail || message.message || 'Failed to send message');
  }
  if (message.status && message.status !== 'success') {
    throw new Error(message.message || 'Failed to send message');
  }
  return message;
}


function createMessageElement(message) {
  const messageElement = document.createElement('div');
  const sourceLabel = message.source === 'user' ? 'You' : message.source === 'assistant' ? 'Bot' : (message.source || 'System');
  messageElement.className = `message ${message.source || 'assistant'}`;
  marked.setOptions({ mangle: false, headerIds: false });

  const sourceElement = document.createElement('span');
  sourceElement.className = 'message-source';
  sourceElement.textContent = sourceLabel;

  const contentElement = document.createElement('span');
  contentElement.className = 'message-content';
  const text = message.text || message.content || '';
  const messageWithTabsAndNewlinesReplaced = text.replace(/\t/g, "&nbsp;&nbsp;&nbsp;&nbsp;").replace(/\n/g, "<br/>");
  const messageHTML = marked.marked(messageWithTabsAndNewlinesReplaced);
  contentElement.innerHTML = messageHTML;

  const timestampElement = document.createElement('span');
  timestampElement.className = 'message-timestamp';
  timestampElement.innerText = message.created_at; // Changed from 'timestamp' to 'created_at'

  const copyButton = document.createElement('button');
  copyButton.className = 'copy-button';
  copyButton.textContent = 'Copy';
  copyButton.addEventListener('click', function() {
    navigator.clipboard.writeText(text);
  });

  const metaWrap = document.createElement('span');
  metaWrap.className = 'message-meta';
  metaWrap.appendChild(timestampElement);
  metaWrap.appendChild(copyButton);

  messageElement.appendChild(sourceElement);
  messageElement.appendChild(contentElement);
  messageElement.appendChild(metaWrap);

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
