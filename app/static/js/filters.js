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

let activeFiltersMobilePane = 'list';
let filtersMobilePaneMedia = null;
const FILTERS_MOBILE_PANE_KEY = 'norman.mobile.filters.pane.v1';

function readStoredFiltersMobilePane() {
  try {
    const value = (localStorage.getItem(FILTERS_MOBILE_PANE_KEY) || '').trim();
    return ['list', 'setup'].includes(value) ? value : null;
  } catch (err) {
    return null;
  }
}

function writeStoredFiltersMobilePane(pane) {
  try {
    localStorage.setItem(FILTERS_MOBILE_PANE_KEY, pane);
  } catch (err) {
    // ignore storage errors
  }
}

function isCompactFiltersViewport() {
  return Boolean(filtersMobilePaneMedia?.matches);
}

function setFiltersMobilePane(pane) {
  const page = document.querySelector('.filters-page');
  if (!page) return;
  activeFiltersMobilePane = pane;
  writeStoredFiltersMobilePane(pane);
  page.dataset.mobilePane = pane;
  document.querySelectorAll('[data-filters-pane]').forEach((btn) => {
    btn.classList.toggle('is-active', btn.getAttribute('data-filters-pane') === pane);
  });
}

function initFiltersMobilePaneSwitcher() {
  const page = document.querySelector('.filters-page');
  const buttons = Array.from(document.querySelectorAll('[data-filters-pane]'));
  if (!page || !buttons.length) return;

  const savedPane = readStoredFiltersMobilePane();
  if (savedPane) {
    activeFiltersMobilePane = savedPane;
  }

  filtersMobilePaneMedia = window.matchMedia('(max-width: 991px)');
  setFiltersMobilePane(activeFiltersMobilePane);

  buttons.forEach((btn) => {
    btn.addEventListener('click', () => {
      setFiltersMobilePane(btn.getAttribute('data-filters-pane') || 'list');
    });
  });

  const syncPaneMode = () => {
    if (isCompactFiltersViewport()) {
      page.dataset.mobilePane = activeFiltersMobilePane;
      return;
    }
    page.removeAttribute('data-mobile-pane');
  };
  syncPaneMode();
  if (typeof filtersMobilePaneMedia.addEventListener === 'function') {
    filtersMobilePaneMedia.addEventListener('change', syncPaneMode);
  } else if (typeof filtersMobilePaneMedia.addListener === 'function') {
    filtersMobilePaneMedia.addListener(syncPaneMode);
  }
}

function hideCollapse(id) {
  const el = document.getElementById(id);
  if (!el || !window.bootstrap?.Collapse) return;
  const instance = window.bootstrap.Collapse.getOrCreateInstance(el, { toggle: false });
  instance.hide();
}

document.addEventListener('DOMContentLoaded', () => {
  initFiltersMobilePaneSwitcher();
  loadChannels();
  fetchFiltersAndRender();

  const form = document.getElementById('add-filter-form');
  if (form) {
    form.addEventListener('submit', onAddFilterSubmit);
  }

  const searchInput = document.getElementById('filterSearch');
  if (searchInput) {
    searchInput.addEventListener('input', (event) => {
      filterRenderedFilters(event.target.value || '');
    });
  }
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
  filterRenderedFilters(document.getElementById('filterSearch')?.value || '');
  updateCount('filters-count', filters.length);
  if (!filters.length) {
    setStatus('No filters yet. Add one above.', 'info');
    if (isCompactFiltersViewport()) {
      setFiltersMobilePane('setup');
    }
    return;
  }
  setStatus('');
}

function filterRenderedFilters(query) {
  const normalized = String(query || '').trim().toLowerCase();
  const rows = Array.from(document.querySelectorAll('.filters-container .list-group-item'));
  rows.forEach((row) => {
    const label = row.textContent?.toLowerCase() || '';
    row.classList.toggle('d-none', Boolean(normalized) && !label.includes(normalized));
  });
}

function createFilterElement(filter) {
  const filterElement = document.createElement('div');
  filterElement.classList.add('list-group-item');

  const header = document.createElement('div');
  header.className = 'd-flex align-items-center justify-content-between mb-2';

  const info = document.createElement('div');
  info.className = 'fw-semibold';
  info.textContent = `Channel ${filter.channel_id}`;

  const actions = document.createElement('div');
  actions.className = 'd-flex gap-2';

  const editButton = document.createElement('button');
  editButton.textContent = 'Edit';
  editButton.className = 'btn btn-sm btn-outline-secondary';

  const deleteButton = document.createElement('button');
  deleteButton.textContent = 'Delete';
  deleteButton.className = 'btn btn-sm btn-outline-danger';

  actions.appendChild(editButton);
  actions.appendChild(deleteButton);
  header.appendChild(info);
  header.appendChild(actions);
  filterElement.appendChild(header);

  const regex = document.createElement('div');
  regex.className = 'small text-muted';
  regex.textContent = filter.regex;
  filterElement.appendChild(regex);

  const desc = document.createElement('div');
  desc.classList.add('small');
  desc.textContent = filter.description || '';
  filterElement.appendChild(desc);

  const editForm = document.createElement('div');
  editForm.className = 'filter-edit-form d-none mt-2';
  editForm.innerHTML = `
    <div class="row g-2">
      <div class="col-12 col-md-4">
        <label class="form-label">Channel</label>
        <select class="form-select form-select-sm filter-edit-channel"></select>
      </div>
      <div class="col-12 col-md-4">
        <label class="form-label">Regex</label>
        <input type="text" class="form-control form-control-sm filter-edit-regex" value="${filter.regex}">
      </div>
      <div class="col-12 col-md-4">
        <label class="form-label">Description</label>
        <input type="text" class="form-control form-control-sm filter-edit-desc" value="${filter.description || ''}">
      </div>
    </div>
    <div class="d-flex gap-2 mt-2">
      <button type="button" class="btn btn-sm btn-primary filter-save">Save</button>
      <button type="button" class="btn btn-sm btn-outline-secondary filter-cancel">Cancel</button>
    </div>
  `;
  filterElement.appendChild(editForm);

  const channelSelect = editForm.querySelector('.filter-edit-channel');
  const regexInput = editForm.querySelector('.filter-edit-regex');
  const descInput = editForm.querySelector('.filter-edit-desc');

  editButton.addEventListener('click', async () => {
    document.querySelectorAll('.filter-edit-form').forEach(form => {
      if (form !== editForm) form.classList.add('d-none');
    });
    await populateChannelSelect(channelSelect, filter.channel_id);
    editForm.classList.toggle('d-none');
  });

  editForm.querySelector('.filter-cancel').addEventListener('click', () => {
    regexInput.value = filter.regex;
    descInput.value = filter.description || '';
    editForm.classList.add('d-none');
  });

  editForm.querySelector('.filter-save').addEventListener('click', async () => {
    const updatedChannel = Number.parseInt(channelSelect.value, 10);
    const newRegex = regexInput.value.trim();
    const newDesc = descInput.value.trim();
    if (!newRegex) {
      setStatus('Regex is required.', 'danger');
      return;
    }
    try {
      new RegExp(newRegex);
    } catch (e) {
      setStatus('Invalid regular expression.', 'danger');
      return;
    }
    try {
      const updated = await updateFilter(filter.id, {
        channel_id: updatedChannel,
        regex: newRegex,
        description: newDesc,
      });
      filter.channel_id = updated.channel_id;
      filter.regex = updated.regex;
      filter.description = updated.description;
      info.textContent = `Channel ${updated.channel_id}`;
      regex.textContent = updated.regex;
      desc.textContent = updated.description || '';
      editForm.classList.add('d-none');
      setStatus('Filter updated.', 'success');
    } catch (err) {
      setStatus(err.message || 'Failed to update filter.', 'danger');
    }
  });

  deleteButton.addEventListener('click', async () => {
    if (!confirm('Delete this filter?')) return;
    try {
      deleteButton.classList.add('btn-loading');
      deleteButton.textContent = 'Deleting';
      setStatus('Deleting filter...', 'info');
      await deleteFilter(filter.id);
      filterElement.remove();
      setStatus('Filter deleted.', 'success');
    } catch (err) {
      setStatus(err.message || 'Failed to delete filter.', 'danger');
    } finally {
      deleteButton.classList.remove('btn-loading');
      deleteButton.textContent = 'Delete';
    }
  });

  return filterElement;
}


async function getFilters() {
  const response = await fetch("/api/v1/filters/");
  const filters = await response.json();
  return filters;
}

async function populateChannelSelect(select, selectedId) {
  if (!select) return;
  const resp = await fetch('/api/v1/channels/');
  const channels = resp.ok ? await resp.json() : [];
  select.innerHTML = '';
  channels.forEach(c => {
    const opt = document.createElement('option');
    opt.value = c.id;
    opt.textContent = c.name;
    if (c.id === selectedId) opt.selected = true;
    select.appendChild(opt);
  });
}

async function createFilter(filterData) {
  const response = await fetch("/api/v1/filters/", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(filterData),
  });
  const filter = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(filter.detail || 'Failed to create filter');
  }
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

async function onAddFilterSubmit(event) {
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

  try {
    const newFilter = await createFilter(filterData);
    if (!newFilter || !newFilter.id) {
      setStatus('Failed to add filter. Check the channel selection and regex.', 'danger');
      return;
    }
    await fetchFiltersAndRender();
    hideCollapse('filters-add-panel');
    if (isCompactFiltersViewport()) {
      setFiltersMobilePane('list');
    }
    setStatus(`Filter added for channel ${newFilter.channel_id}.`, 'success');

    regexInput.value = '';
    descriptionInput.value = '';
  } catch (err) {
    setStatus(err.message || 'Failed to add filter.', 'danger');
  }
}
