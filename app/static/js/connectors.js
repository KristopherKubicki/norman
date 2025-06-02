// connectors.js - dynamic connector management

document.addEventListener('DOMContentLoaded', () => {
  fetchConnectorsAndRender();

  const addForm = document.getElementById('add-connector-form');
  if (addForm) {
    addForm.addEventListener('submit', async (evt) => {
      evt.preventDefault();
      const nameInput = document.getElementById('connector-name');
      const typeInput = document.getElementById('connector-type');
      const configInput = document.getElementById('connector-config');
      const feedback = document.getElementById('connector-feedback');
      feedback.innerHTML = '';
      feedback.className = '';
      let config = {};
      if (configInput.value.trim()) {
        try {
          config = JSON.parse(configInput.value);
        } catch (e) {
          showFeedback('Config must be valid JSON', true);
          return;
        }
      }
      try {
        const connector = await createConnector({
          name: nameInput.value.trim(),
          connector_type: typeInput.value.trim(),
          config: config
        });
        document.querySelector('.connectors-container')
          .appendChild(createConnectorElement(connector));
        nameInput.value = '';
        typeInput.value = '';
        configInput.value = '';
        showFeedback('Connector added successfully', false);
      } catch (err) {
        showFeedback(err.message || 'Failed to add connector', true);
      }
    });
  }
});

async function fetchConnectorsAndRender() {
  const connectors = await getConnectors();
  const container = document.querySelector('.connectors-container');
  container.innerHTML = '';
  for (const connector of connectors) {
    const el = createConnectorElement(connector);
    container.appendChild(el);
    // fetch status for each connector
    try {
      const status = await getConnectorStatus(connector.id);
      el.querySelector('.connector-status').textContent = status.status;
    } catch (e) {
      el.querySelector('.connector-status').textContent = 'unknown';
    }
  }
}

async function getConnectors() {
  const resp = await fetch('/api/connectors');
  return await resp.json();
}

async function createConnector(data) {
  const resp = await fetch('/api/connectors/create', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data)
  });
  const result = await resp.json();
  if (!resp.ok) {
    throw new Error(result.detail || 'Error creating connector');
  }
  return result;
}

async function updateConnector(id, data) {
  const resp = await fetch(`/api/connectors/${id}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data)
  });
  const result = await resp.json();
  if (!resp.ok) {
    throw new Error(result.detail || 'Error updating connector');
  }
  return result;
}

async function deleteConnector(id) {
  const resp = await fetch(`/api/connectors/${id}`, { method: 'DELETE' });
  if (!resp.ok) {
    const result = await resp.json();
    throw new Error(result.detail || 'Error deleting connector');
  }
}

async function testConnector(id) {
  const resp = await fetch(`/api/connectors/${id}/test`, { method: 'POST' });
  const result = await resp.json();
  if (!resp.ok) {
    throw new Error(result.detail || 'Error testing connector');
  }
  return result;
}

async function getConnectorStatus(id) {
  const resp = await fetch(`/api/connectors/${id}/status`);
  const result = await resp.json();
  if (!resp.ok) {
    throw new Error(result.detail || 'Error fetching status');
  }
  return result;
}

function createConnectorElement(connector) {
  const card = document.createElement('div');
  card.className = 'card mb-3';
  const body = document.createElement('div');
  body.className = 'card-body';
  const header = document.createElement('h5');
  header.textContent = `${connector.name} (${connector.connector_type})`;
  const statusSpan = document.createElement('span');
  statusSpan.className = 'badge bg-secondary ms-2 connector-status';
  statusSpan.textContent = '...';
  header.appendChild(statusSpan);
  body.appendChild(header);

  const editBtn = document.createElement('button');
  editBtn.className = 'btn btn-sm btn-outline-secondary me-2';
  editBtn.textContent = 'Edit';
  editBtn.addEventListener('click', async () => {
    const newName = prompt('Connector name', connector.name);
    const newType = prompt('Connector type', connector.connector_type);
    let newConfig = prompt('Config (JSON)', JSON.stringify(connector.config || {}));
    if (newName && newType && newConfig != null) {
      try {
        newConfig = JSON.parse(newConfig);
      } catch (e) {
        showFeedback('Config must be valid JSON', true);
        return;
      }
      try {
        const updated = await updateConnector(connector.id, {
          name: newName,
          connector_type: newType,
          config: newConfig
        });
        connector.name = updated.name;
        connector.connector_type = updated.connector_type;
        connector.config = updated.config;
        header.childNodes[0].nodeValue = `${updated.name} (${updated.connector_type})`;
        showFeedback('Connector updated successfully', false);
      } catch (err) {
        showFeedback(err.message || 'Failed to update connector', true);
      }
    }
  });

  const deleteBtn = document.createElement('button');
  deleteBtn.className = 'btn btn-sm btn-danger me-2';
  deleteBtn.textContent = 'Delete';
  deleteBtn.addEventListener('click', async () => {
    try {
      await deleteConnector(connector.id);
      card.remove();
      showFeedback('Connector deleted', false);
    } catch (err) {
      showFeedback(err.message || 'Failed to delete connector', true);
    }
  });

  const testBtn = document.createElement('button');
  testBtn.className = 'btn btn-sm btn-outline-primary';
  testBtn.textContent = 'Test';
  testBtn.addEventListener('click', async () => {
    try {
      const result = await testConnector(connector.id);
      statusSpan.textContent = result.status;
      showFeedback('Test completed: ' + result.status, false);
    } catch (err) {
      showFeedback(err.message || 'Failed to test connector', true);
    }
  });

  body.appendChild(editBtn);
  body.appendChild(deleteBtn);
  body.appendChild(testBtn);
  card.appendChild(body);
  return card;
}

function showFeedback(message, isError) {
  const feedback = document.getElementById('connector-feedback');
  if (!feedback) return;
  feedback.textContent = message;
  feedback.className = isError ? 'alert alert-danger' : 'alert alert-success';
}
