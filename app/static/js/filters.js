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
  loadChannels();
  fetchFiltersAndRender();
});

function updateCount(id, count) {
  const el = document.getElementById(id);
  if (el) el.textContent = count;
}

function setStatus(message, type = 'info') {
  const status = document.getElementById('filters-status');
  if (!status) return;
  if (!message) {
    status.classList.add('d-none');
    status.textContent = '';
    return;
  }
  status.className = `alert alert-${type}`;
  status.textContent = message;
}

async function loadChannels() {
  const resp = await fetch('/api/v1/channels/');
  const select = document.getElementById('filter-channel');
  const addButton = document.querySelector('#add-filter-form button[type="submit"]');
  select.innerHTML = '';
  if (!resp.ok) {
    const opt = document.createElement('option');
    opt.value = '';
    opt.textContent = 'Unable to load channels';
    opt.disabled = true;
    opt.selected = true;
    select.appendChild(opt);
    if (addButton) addButton.disabled = true;
    setStatus('Unable to load channels. Please refresh or log in again.', 'danger');
    return;
  }
  const channels = await resp.json();
  if (!channels.length) {
    const opt = document.createElement('option');
    opt.value = '';
    opt.textContent = 'No channels yet';
    opt.disabled = true;
    opt.selected = true;
    select.appendChild(opt);
    if (addButton) addButton.disabled = true;
    setStatus('Create a channel before adding filters.', 'warning');
    return;
  }
  channels.forEach(c => {
    const opt = document.createElement('option');
    opt.value = c.id;
    opt.textContent = c.name;
    select.appendChild(opt);
  });
  if (addButton) addButton.disabled = false;
  setStatus('');
}

async function fetchFiltersAndRender() {
  const filters = await getFilters();
  const filtersContainer = document.querySelector('.filters-container');
  filtersContainer.innerHTML = '';
  for (const filter of filters) {
    const filterElement = createFilterElement(filter);
    filtersContainer.appendChild(filterElement);
  }
  updateCount('filters-count', filters.length);
  if (!filters.length) {
    setStatus('No filters yet. Add one above.', 'info');
  }
}

function createFilterElement(filter) {
  const filterElement = document.createElement('div');
  filterElement.classList.add('list-group-item');

  const info = document.createElement('div');
  info.className = 'fw-semibold';
  info.textContent = `Channel ${filter.channel_id}`;
  filterElement.appendChild(info);

  const regex = document.createElement('div');
  regex.className = 'small text-muted';
  regex.textContent = filter.regex;
  filterElement.appendChild(regex);

  if (filter.description) {
    const desc = document.createElement('div');
    desc.classList.add('small');
    desc.textContent = filter.description;
    filterElement.appendChild(desc);
  }

  const editButton = document.createElement('button');
  editButton.textContent = 'Edit';
  editButton.className = 'btn btn-sm btn-outline-secondary me-2';
  editButton.addEventListener('click', async () => {
    const newRegex = prompt('Regex', filter.regex);
    const newDesc = prompt('Description', filter.description || '');
    if (newRegex) {
      try {
        const updated = await updateFilter(filter.id, {
          channel_id: filter.channel_id,
          regex: newRegex,
          description: newDesc,
        });
        info.textContent = `Channel ${updated.channel_id}`;
        regex.textContent = updated.regex;
        desc && (desc.textContent = updated.description);
        setStatus('Filter updated.', 'success');
      } catch (err) {
        setStatus(err.message || 'Failed to update filter.', 'danger');
      }
    }
  });

  const deleteButton = document.createElement('button');
  deleteButton.textContent = 'Delete';
  deleteButton.className = 'btn btn-sm btn-outline-danger';
  deleteButton.addEventListener('click', async () => {
    if (!confirm('Delete this filter?')) return;
    try {
      await deleteFilter(filter.id);
      filterElement.remove();
      setStatus('Filter deleted.', 'success');
    } catch (err) {
      setStatus(err.message || 'Failed to delete filter.', 'danger');
    }
  });

  const actions = document.createElement('div');
  actions.className = 'd-flex mt-2';
  actions.appendChild(editButton);
  actions.appendChild(deleteButton);
  filterElement.appendChild(actions);
  return filterElement;
}


async function getFilters() {
  const response = await fetch("/api/v1/filters/");
  const filters = await response.json();
  return filters;
}

async function createFilter(filterData) {
  const response = await fetch("/api/v1/filters/", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(filterData),
  });
  const filter = await response.json();
  return filter;
}

async function deleteFilter(filterId) {
  const response = await fetch(`/api/v1/filters/${filterId}`, {
    method: "DELETE",
  });
  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.detail || 'Failed to delete filter');
  }
}

async function updateFilter(filterId, filterData) {
  const response = await fetch(`/api/v1/filters/${filterId}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(filterData),
  });
  const filter = await response.json();
  if (!response.ok) {
    throw new Error(filter.detail || 'Failed to update filter');
  }
  return filter;
}

document.getElementById('add-filter-form').addEventListener('submit', async (event) => {
  event.preventDefault();

  const channelSelect = document.getElementById('filter-channel');
  const regexInput = document.getElementById('filter-regex');
  const descriptionInput = document.getElementById('filter-description');

  clearError(regexInput);

  const regexValue = regexInput.value.trim();

  if (!regexValue) {
    showError(regexInput, 'Regex is required');
    return;
  }

  try {
    new RegExp(regexValue);
  } catch (e) {
    showError(regexInput, 'Invalid regular expression');
    return;
  }

  const filterData = {
    channel_id: parseInt(channelSelect.value, 10),
    regex: regexValue,
    description: descriptionInput.value,
  };

  const newFilter = await createFilter(filterData);
  if (!newFilter || !newFilter.id) {
    setStatus('Failed to add filter. Check the channel selection and regex.', 'danger');
    return;
  }
  document.querySelector('.filters-container').appendChild(createFilterElement(newFilter));
  setStatus(`Filter added for channel ${newFilter.channel_id}.`, 'success');

  regexInput.value = '';
  descriptionInput.value = '';
});

(async () => {
  const filters = await getFilters();
  const filtersContainer = document.querySelector(".filters-container");

  for (const filter of filters) {
    filtersContainer.appendChild(createFilterElement(filter));
  }
})();
