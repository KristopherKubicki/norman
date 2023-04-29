// Add a listener for DOMContentLoaded to make sure the page is fully loaded before running the script
document.addEventListener("DOMContentLoaded", function () {
  // Fetch channels and messages from the API
  fetchChannels();
  fetchMessages();

  // Add event listeners for channel list items and message form
  setupChannelList();
  setupMessageForm();
});

function fetchChannels() {
  // Fetch the channels from the API and update the UI
  // ...
}

function fetchMessages() {
  // Fetch the messages for the selected channel from the API and update the UI
  // ...
}

function setupChannelList() {
  // Add click event listeners to the channel list items to load messages for the selected channel
  // ...
}

function setupMessageForm() {
  // Add a submit event listener to the message form to send messages through the API
  // ...
}

async function fetchChannelsAndRender() {
  const response = await fetch('/api/v1/channels');
  const channels = await response.json();

  const channelsContainer = document.querySelector('.channels-container');
  channelsContainer.innerHTML = '';

  for (const channel of channels) {
    const channelElement = createChannelElement(channel);
    channelsContainer.appendChild(channelElement);
  }
}


async function getChannels() {
  const response = await fetch("/api/v1/channels");
  const channels = await response.json();
  return channels;
}

async function createChannel(data) {
  const response = await fetch("/api/v1/channels", {
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

  const nameElement = document.createElement("p");
  nameElement.textContent = `Name: ${channel.name}`;

  const descriptionElement = document.createElement("p");
  descriptionElement.textContent = `Description: ${channel.description}`;

  const editButton = document.createElement("button");
  editButton.textContent = "Edit";
  editButton.addEventListener("click", async () => {
    const newName = prompt("Enter the new channel name:", channel.name);
    const newDescription = prompt("Enter the new channel description:", channel.description);

    if (newName && newDescription) {
      const updatedChannel = await updateChannel(channel.id, { name: newName, description: newDescription });
      nameElement.textContent = `Name: ${updatedChannel.name}`;
      descriptionElement.textContent = `Description: ${updatedChannel.description}`;
    }
  });

  const deleteButton = document.createElement("button");
  deleteButton.textContent = "Delete";
  deleteButton.addEventListener("click", async () => {
    await deleteChannel(channel.id);
    channelElement.remove();
  });

  channelElement.appendChild(nameElement);
  channelElement.appendChild(descriptionElement);
  channelElement.appendChild(editButton);
  channelElement.appendChild(deleteButton);

  return channelElement;
}

document.getElementById("add-channel-form").addEventListener("submit", async (event) => {
  event.preventDefault();

  const nameInput = document.getElementById("channel-name");
  const descriptionInput = document.getElementById("channel-description");

  const channelData = {
    name: nameInput.value,
    description: descriptionInput.value,
  };

  const newChannel = await createChannel(channelData);
  document.querySelector(".channels-container").appendChild(createChannelElement(newChannel));

  nameInput.value = "";
  descriptionInput.value = "";
});

(async () => {
  const channels = await getChannels();
  const channelsContainer = document.querySelector(".channels-container");

  for (const channel of channels) {
    channelsContainer.appendChild(createChannelElement(channel));
  }
})();

