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
  loadConnectors();
  fetchChannelsAndRender();

  const sampleBtn = document.getElementById('add-sample-channels');
  if (sampleBtn) {
    sampleBtn.addEventListener('click', seedSampleChannels);
  }
});

function updateCount(id, count) {
  const el = document.getElementById(id);
  if (el) el.textContent = count;
}

function setStatus(message, type = 'info') {
  const status = document.getElementById('channels-status');
  if (!status) return;
  if (!message) {
    status.classList.add('d-none');
    status.textContent = '';
    return;
  }
  status.className = `alert alert-${type}`;
  status.textContent = message;
}

async function loadConnectors() {
  const resp = await fetch('/api/connectors');
  const select = document.getElementById('channel-connector');
  const addButton = document.getElementById('addChannelBtn');
  select.innerHTML = '';
  if (!resp.ok) {
    const opt = document.createElement('option');
    opt.value = '';
    opt.textContent = 'Unable to load connectors';
    opt.disabled = true;
    opt.selected = true;
    select.appendChild(opt);
    if (addButton) addButton.disabled = true;
    setStatus('Unable to load connectors. Please refresh or log in again.', 'danger');
    return;
  }
  const connectors = await resp.json();
  if (!connectors.length) {
    const opt = document.createElement('option');
    opt.value = '';
    opt.textContent = 'No connectors yet';
    opt.disabled = true;
    opt.selected = true;
    select.appendChild(opt);
    if (addButton) addButton.disabled = true;
    setStatus('Add a connector first, then create a channel.', 'warning');
    return;
  }
  connectors.forEach(connector => {
    const opt = document.createElement('option');
    opt.value = connector.id;
    opt.textContent = `${connector.name} (${connector.connector_type})`;
    select.appendChild(opt);
  });
  if (addButton) addButton.disabled = false;
  setStatus('');
}

async function fetchChannelsAndRender() {
  const response = await fetch('/api/v1/channels/');
  if (!response.ok) {
    setStatus('Unable to load channels.', 'danger');
    return;
  }
  const channels = await response.json();
  updateCount('channels-count', channels.length);

  const channelsContainer = document.querySelector('.channels-container');
  channelsContainer.innerHTML = '';

  if (!channels.length) {
    setStatus('No channels yet. Create one above.', 'info');
  } else {
    setStatus('');
    for (const channel of channels) {
      const channelElement = createChannelElement(channel);
      channelsContainer.appendChild(channelElement);
    }
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
  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.detail || 'Failed to update channel');
  }
  return response.json();
}

async function deleteChannel(id) {
  const response = await fetch(`/api/v1/channels/${id}`, {
    method: "DELETE",
  });
  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.detail || 'Failed to delete channel');
  }
}

async function ensureSampleConnector() {
  const resp = await fetch('/api/connectors');
  if (!resp.ok) {
    throw new Error('Unable to load connectors');
  }
  const connectors = await resp.json();
  let sample = connectors.find(c => c.connector_type === 'sample');
  if (sample) {
    return sample;
  }
  const created = await fetch('/api/connectors/create', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      name: 'Sample Connector',
      connector_type: 'sample',
      config: {},
    }),
  });
  if (!created.ok) {
    const error = await created.json();
    throw new Error(error.detail || 'Failed to create sample connector');
  }
  return created.json();
}

async function seedSampleChannels() {
  try {
    const sampleConnector = await ensureSampleConnector();
    const channelResp = await fetch('/api/v1/channels/');
    const channels = channelResp.ok ? await channelResp.json() : [];
    const samples = [
      'Random Data',
      'Time Signals (NIST)',
      'System Events',
    ];
    for (const name of samples) {
      if (channels.find(c => c.name === name)) continue;
      await createChannel({ name, connector_id: sampleConnector.id });
    }
    await fetchChannelsAndRender();
    setStatus('Sample channels created.', 'success');
  } catch (err) {
    setStatus(err.message || 'Failed to create sample channels.', 'danger');
  }
}

function createChannelElement(channel) {
  const channelElement = document.createElement("div");
  channelElement.classList.add("list-group-item");

  const nameElement = document.createElement('div');
  nameElement.className = 'fw-semibold';
  nameElement.textContent = channel.name;

  const connectorElement = document.createElement('div');
  connectorElement.className = 'small text-muted';
  connectorElement.textContent = `Connector ID: ${channel.connector_id}`;

  const editForm = document.createElement('div');
  editForm.className = 'd-none mt-2';
  editForm.innerHTML = `
    <input type="text" class="form-control form-control-sm mb-2" value="${channel.name}">
    <input type="number" class="form-control form-control-sm mb-2" value="${channel.connector_id}">
    <div class="d-flex gap-2">
      <button class="btn btn-sm btn-primary" type="button">Save</button>
      <button class="btn btn-sm btn-outline-secondary" type="button">Cancel</button>
    </div>
  `;

  const editButton = document.createElement("button");
  editButton.textContent = "Edit";
  editButton.className = 'btn btn-sm btn-outline-secondary me-2';
  editButton.addEventListener("click", async () => {
    editForm.classList.remove('d-none');
  });

  const deleteButton = document.createElement("button");
  deleteButton.textContent = "Delete";
  deleteButton.className = 'btn btn-sm btn-outline-danger';
  deleteButton.addEventListener("click", async () => {
    if (!confirm(`Delete channel "${channel.name}"?`)) return;
    try {
      await deleteChannel(channel.id);
      channelElement.remove();
      updateCount('channels-count', document.querySelectorAll('.channels-container .list-group-item').length);
    } catch (err) {
      setStatus(err.message, 'danger');
    }
  });

  const actions = document.createElement('div');
  actions.className = 'd-flex mt-2';
  actions.appendChild(editButton);
  actions.appendChild(deleteButton);

  channelElement.appendChild(nameElement);
  channelElement.appendChild(connectorElement);
  channelElement.appendChild(actions);
  channelElement.appendChild(editForm);

  const [nameInput, connectorInput] = editForm.querySelectorAll('input');
  const [saveBtn, cancelBtn] = editForm.querySelectorAll('button');
  saveBtn.addEventListener('click', async () => {
    const newName = nameInput.value.trim();
    const newConnector = Number(connectorInput.value);
    if (!newName || !newConnector) {
      setStatus('Name and connector are required.', 'danger');
      return;
    }
    try {
      const updatedChannel = await updateChannel(channel.id, { name: newName, connector_id: newConnector });
      channel.name = updatedChannel.name;
      channel.connector_id = updatedChannel.connector_id;
      nameElement.textContent = updatedChannel.name;
      connectorElement.textContent = `Connector ID: ${updatedChannel.connector_id}`;
      editForm.classList.add('d-none');
      setStatus('Channel updated.', 'success');
    } catch (err) {
      setStatus(err.message, 'danger');
    }
  });
  cancelBtn.addEventListener('click', () => {
    nameInput.value = channel.name;
    connectorInput.value = channel.connector_id;
    editForm.classList.add('d-none');
  });

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
    connector_id: parseInt(connector, 10),
  };

  const newChannel = await createChannel(channelData);
  if (!newChannel || !newChannel.id) {
    setStatus('Failed to add channel. Make sure a connector is selected.', 'danger');
    return;
  }
  document.querySelector('.channels-container').appendChild(createChannelElement(newChannel));
  setStatus(`Channel "${newChannel.name}" created.`, 'success');

  nameInput.value = '';
});

(async () => {
  const channels = await getChannels();
  const channelsContainer = document.querySelector(".channels-container");

  for (const channel of channels) {
    channelsContainer.appendChild(createChannelElement(channel));
  }
})();
