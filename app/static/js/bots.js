
let selectedBotId = null;
const sendButton = document.getElementById('send-message');

document.addEventListener('DOMContentLoaded', () => {
  const sendButton = document.getElementById('send-message');
  // Fetch bots and render them in the bots container
  fetchBotsAndRender();

  // Set up handler for saving edits
  const saveBtn = document.getElementById('save-bot-changes');
  if (saveBtn) {
    saveBtn.addEventListener('click', async () => {
      if (!selectedBotId) return;
      const data = {
        name: document.getElementById('edit-bot-name').value.trim(),
        description: document.getElementById('edit-bot-description').value.trim(),
        gpt_model: document.getElementById('edit-bot-model').value.trim(),
        enabled: document.getElementById('edit-bot-enabled').checked
      };
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
  const botElement = document.createElement('a');
  botElement.classList.add('list-group-item', 'list-group-item-action', 'bot-item');
  botElement.dataset.botId = bot.id;
  botElement.textContent = bot.name;

  const editButton = document.createElement('button');
  editButton.className = 'btn btn-sm btn-secondary float-end ms-2';
  editButton.textContent = 'Edit';
  editButton.addEventListener('click', (e) => {
    e.stopPropagation();
    openEditModal(bot);
  });

  const deleteButton = document.createElement('button');
  deleteButton.className = 'btn btn-sm btn-danger float-end';
  deleteButton.textContent = 'Delete';
  deleteButton.addEventListener('click', async (e) => {
    e.stopPropagation();
    await deleteBot(bot.id);
    botElement.remove();
  });

  botElement.appendChild(deleteButton);
  botElement.appendChild(editButton);

  // Add click event listener to fetch and display messages
  botElement.addEventListener('click', () => {
    const selectedBotNameElement = document.getElementById('selected-bot-name');
    selectedBotId = bot.id;
    selectedBotNameElement.innerText = bot.name;
    selectedBotNameElement.setAttribute('data-bot-id', bot.id);
    fetchMessagesAndRender(bot.id);
    document.getElementById('send-message').removeAttribute('disabled');
    document.getElementById('input-message').removeAttribute('disabled');
    document.getElementById('input-message').placeholder = 'Enter your message...';
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

