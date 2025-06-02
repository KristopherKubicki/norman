// Add a listener for DOMContentLoaded to make sure the page is fully loaded before running the script
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

document.addEventListener('DOMContentLoaded', () => {
  fetchChannelsAndRender();
});


async function fetchChannelsAndRender() {
  const response = await fetch('/api/v1/channels/');
  const channels = await response.json();

  const channelsContainer = document.querySelector('.channels-container');
  channelsContainer.innerHTML = '';

  for (const channel of channels) {
    const channelElement = createChannelElement(channel);
    channelsContainer.appendChild(channelElement);
  }
}


async function getChannels() {
  const response = await fetch('/api/v1/channels/');
  const channels = await response.json();
  return channels;
}

async function createChannel(data) {
  const response = await fetch('/api/v1/channels/', {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(data),
  });
  const channel = await response.json();
  return channel;
}

async function updateChannel(id, data) {
  const response = await fetch(`/api/v1/channels/${id}`, {
    method: "PUT",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(data),
  });
  const channel = await response.json();
  return channel;
}

async function deleteChannel(id) {
  await fetch(`/api/v1/channels/${id}`, {
    method: "DELETE",
  });
}

function createChannelElement(channel) {
  const channelElement = document.createElement("div");
  channelElement.classList.add("channel");

  const nameElement = document.createElement('p');
  nameElement.textContent = `Name: ${channel.name}`;

  const connectorElement = document.createElement('p');
  connectorElement.textContent = `Connector ID: ${channel.connector_id}`;

  const editButton = document.createElement("button");
  editButton.textContent = "Edit";
  editButton.addEventListener("click", async () => {
    const newName = prompt('Enter the new channel name:', channel.name);
    const newConnector = prompt('Connector ID:', channel.connector_id);

    if (newName && newConnector) {
      const updatedChannel = await updateChannel(channel.id, { name: newName, connector_id: parseInt(newConnector, 10) });
      nameElement.textContent = `Name: ${updatedChannel.name}`;
      connectorElement.textContent = `Connector ID: ${updatedChannel.connector_id}`;
    }
  });

  const deleteButton = document.createElement("button");
  deleteButton.textContent = "Delete";
  deleteButton.addEventListener("click", async () => {
    await deleteChannel(channel.id);
    channelElement.remove();
  });

  channelElement.appendChild(nameElement);
  channelElement.appendChild(connectorElement);
  channelElement.appendChild(editButton);
  channelElement.appendChild(deleteButton);

  return channelElement;
}

document.getElementById('add-channel-form').addEventListener('submit', async (event) => {
  event.preventDefault();

  const nameInput = document.getElementById('channel-name');
  const connectorInput = document.getElementById('channel-connector');

  clearError(nameInput);
  clearError(connectorInput);

  const name = nameInput.value.trim();
  const connector = connectorInput.value;

  if (!name) {
    showError(nameInput, 'Name is required');
    return;
  }

  if (!connector) {
    showError(connectorInput, 'Connector is required');
    return;
  }

  const channelData = {
    name,
    connector_id: connector,
  };

  const newChannel = await createChannel(channelData);
  document.querySelector('.channels-container').appendChild(createChannelElement(newChannel));

  nameInput.value = '';
});

(async () => {
  const channels = await getChannels();
  const channelsContainer = document.querySelector(".channels-container");

  for (const channel of channels) {
    channelsContainer.appendChild(createChannelElement(channel));
  }
})();

