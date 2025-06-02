
let editModal;
let editState = {};
let sendButton;
let textarea;

document.addEventListener('DOMContentLoaded', () => {
  // Fetch bots and render them in the bots container
  fetchBotsAndRender();

  editModal = new bootstrap.Modal(document.getElementById('editBotModal'));
  document.getElementById('save-edit-bot').addEventListener('click', saveEditBot);

  sendButton = document.getElementById('send-message');
  textarea = document.getElementById('input-message');

  sendButton.addEventListener('click', async (event) => {
    event.preventDefault();
    sendButton.disabled = true;

    textarea.style.height = 'auto';

    const spinner = document.getElementById('spinner');
    const selectedBotNameElement = document.getElementById('selected-bot-name');
    const content = textarea.value.trim();
    const historyDepth = document.getElementById('history-depth').value;
    const responseLength = document.getElementById('response-length').value;

    spinner.style.display = 'inline-block';

    if (selectedBotNameElement.innerText !== 'None' && content) {
      const bot_id = selectedBotNameElement.dataset.botId;
      await sendMessage(bot_id, content, historyDepth, responseLength);
      textarea.value = '';
      textarea.style.height = 'auto';
      fetchMessagesAndRender(bot_id);
    }

    sendButton.disabled = false;
    spinner.style.display = 'none';
  });

  textarea.addEventListener('input', () => {
    textarea.style.height = 'auto';
    textarea.style.height = Math.min(textarea.scrollHeight, 300) + 'px';
  });

  textarea.addEventListener('keydown', function (e) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendButton.click();
    }
  });

  textarea.dispatchEvent(new Event('input'));

  const historySlider = document.getElementById('history-depth');
  const historyValue = document.getElementById('history-depth-value');
  const responseSlider = document.getElementById('response-length');
  const responseValue = document.getElementById('response-length-value');

  historySlider.addEventListener('input', () => {
    historyValue.innerText = historySlider.value;
  });

  responseSlider.addEventListener('input', () => {
    responseValue.innerText = responseSlider.value;
  });

  // Add event listener for the add-bot-form
  const addBotForm = document.getElementById('add-bot-form');
  if (addBotForm) {
    addBotForm.addEventListener('submit', async (event) => {
      event.preventDefault();

      const nameInput = document.getElementById("bot-name");
      const descriptionInput = document.getElementById("bot-description");

      const name = nameInput.value.trim();
      const description = descriptionInput.value.trim();

      if (!name) {
        alert("Please enter a bot name.");
        return;
      }

      const bot = await addBot(name, description, "gpt4");
      const botElement = createBotElement(bot);
      const botsContainer = document.querySelector('.bots-container');
      botsContainer.appendChild(botElement);

      nameInput.value = "";
      descriptionInput.value = "";
    });
  }

});

async function fetchBotsAndRender() {
  const response = await fetch("/api/bots");
  const bots = await response.json();

  const botsContainer = document.querySelector('.bots-container');
  botsContainer.innerHTML = '';

  for (const bot of bots) {
    const botElement = createBotElement(bot);
    botsContainer.appendChild(botElement);
  }
}

function createBotElement(bot) {
  const botElement = document.createElement('div');
  botElement.classList.add('bot');

  const nameElement = document.createElement('p');
  nameElement.textContent = bot.name;
  botElement.appendChild(nameElement);

  const descriptionElement = document.createElement("p");
  descriptionElement.textContent = `Description: ${bot.description}`;

  const editButton = document.createElement("button");
  editButton.textContent = "Edit";
  editButton.addEventListener("click", () => {
    openEditModal(bot, nameElement, descriptionElement);
  });

  const deleteButton = document.createElement("button");
  deleteButton.textContent = "Delete";
  deleteButton.addEventListener("click", async () => {
    if (confirm("Delete this bot?")) {
      await deleteBot(bot.id);
      botElement.remove();
    }
  });

  const lastTriggeredElement = document.createElement('p');
  lastTriggeredElement.classList.add('last-triggered');
  lastTriggeredElement.textContent = `Last triggered: ${bot.lastTriggered}`;

  botElement.appendChild(lastTriggeredElement);
  botElement.appendChild(nameElement);
  botElement.appendChild(descriptionElement);
  botElement.appendChild(editButton);
  botElement.appendChild(deleteButton);

  // Add click event listener to fetch and display messages
  botElement.addEventListener('click', () => {
    const selectedBotNameElement = document.getElementById('selected-bot-name');
    selectedBotNameElement.innerText = bot.name;
    selectedBotNameElement.setAttribute('data-bot-id', bot.id);
    fetchMessagesAndRender(bot.id);
  document.getElementById('send-message').removeAttribute('disabled');
  document.getElementById('input-message').removeAttribute('disabled');
  document.getElementById('input-message').placeholder = 'Enter your message...'
  });


  return botElement;
}


async function addBot(name, description, model) {
  const response = await fetch("/api/bots/create", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ name, description, model }),
  });
  const bot = await response.json();
  return bot;
}

async function deleteBot(botId) {
  const response = await fetch(`/api/bots/${botId}`, {
    method: "DELETE",
  });
  const bot = await response.json();
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

function openEditModal(bot, nameEl, descEl) {
  editState = { id: bot.id, nameEl, descEl };
  document.getElementById("edit-bot-name").value = bot.name;
  document.getElementById("edit-bot-description").value = bot.description || "";
  editModal.show();
}

async function saveEditBot() {
  const newName = document.getElementById("edit-bot-name").value.trim();
  const newDesc = document.getElementById("edit-bot-description").value.trim();
  const updatedBot = await updateBot(editState.id, { name: newName, description: newDesc });
  if (editState.nameEl) editState.nameEl.textContent = updatedBot.name;
  if (editState.descEl) editState.descEl.textContent = `Description: ${updatedBot.description}`;
  editModal.hide();
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


}

async function sendMessage(bot_id, content, historyDepth, responseLength) {
  const response = await fetch(`/api/bots/${bot_id}/messages?history_limit=${historyDepth}&response_tokens=${responseLength}`, {
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

