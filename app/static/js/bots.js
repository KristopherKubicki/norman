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
  
      const bot = await addBot(name, description);
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
  botElement.appendChild(descriptionElement);

  botElement.addEventListener("click", () => {
    window.location.href = `/bot_detail/${bot.id}`;
  });

  return botElement;
}

/*
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

  return botElement;
}
*/


// Add this function to the file
async function addBot(name, description) {
  const response = await fetch("/api/v1/bots", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ name, description }),
  });
  const bot = await response.json();
  return bot;
}

async function deleteBot(botId) {
  const response = await fetch(`/api/v1/bots/${botId}`, {
    method: "DELETE",
  });
  const bot = await response.json();
  return bot;
}


async function updateBot(botId, botData) {
  const response = await fetch(`/api/v1/bots/${botId}`, {
    method: "PUT",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(botData),
  });
  const bot = await response.json();
  return bot;
}
