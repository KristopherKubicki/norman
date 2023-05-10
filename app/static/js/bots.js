document.addEventListener('DOMContentLoaded', () => {
  // Fetch bots and render them in the bots container
  fetchBotsAndRender();

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

});

function selectBot(bot) {
  const selectedBotNameElement = document.getElementById('selected-bot-name');
  selectedBotNameElement.innerText = bot.name;
  selectedBotNameElement.dataset.botId = bot.id; // Set the bot_id as a data attribute
}

sendButton.addEventListener("click", async (event) => {
  event.preventDefault();

  // Disable the button
  sendButton.disabled = true;

  const selectedBotNameElement = document.getElementById('selected-bot-name');
  const content = textarea.value.trim();

  if (selectedBotNameElement.innerText !== 'None' && content) {
    const bot_id = selectedBotNameElement.dataset.botId; // Get the bot_id from the selected bot
    await sendMessage(bot_id, content);
    textarea.value = '';
    textarea.style.height = "auto";
    fetchMessagesAndRender(bot_id);
  }

  // Re-enable the button
  sendButton.disabled = false;
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
  editButton.addEventListener("click", async () => {
    const newName = prompt("Enter the new bot name:", bot.name);
    const newDescription = prompt("Enter the new bot description:", bot.description);

    if (newName && newDescription) {
      const updatedBot = await updateBot(bot.id, { name: newName, description: newDescription });
      nameElement.textContent = `Name: ${updatedBot.name}`;
      descriptionElement.textContent = `Description: ${updatedBot.description}`;
    }
  });

  const deleteButton = document.createElement("button");
  deleteButton.textContent = "Delete";
  deleteButton.addEventListener("click", async () => {
    await deleteBot(bot.id);
    botElement.remove();
  });

  const lastTriggeredElement = document.createElement('p');
  lastTriggeredElement.classList.add('last-triggered');
  lastTriggeredElement.textContent = `Last triggered: ${bot.lastTriggered}`;

  botElement.appendChild(lastTriggeredElement);
  botElement.appendChild(nameElement);
  botElement.appendChild(descriptionElement);
  botElement.appendChild(deleteButton);

  // Add click event listener to fetch and display messages
  botElement.addEventListener('click', () => {
    const selectedBotNameElement = document.getElementById('selected-bot-name');
    selectedBotNameElement.innerText = bot.name;
    selectedBotNameElement.setAttribute('data-bot-id', bot.id);
    fetchMessagesAndRender(bot.id);
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

  console.log('Messages:', messages); // Add this line to debug

  const messagesContainer = document.querySelector('.messages-container');
  messagesContainer.innerHTML = '';

  for (const message of messages) {
    const messageElement = createMessageElement(message);
    messagesContainer.appendChild(messageElement);
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
  messageElement.className = 'message';

  const contentElement = document.createElement('p');
  contentElement.className = 'message-content';
  contentElement.innerText = message.text; // Changed from 'content' to 'text'
  messageElement.appendChild(contentElement);

  const timestampElement = document.createElement('p');
  timestampElement.className = 'message-timestamp';
  timestampElement.innerText = message.created_at; // Changed from 'timestamp' to 'created_at'
  messageElement.appendChild(timestampElement);

  return messageElement;
}
