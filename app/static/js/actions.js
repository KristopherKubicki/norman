function setStatus(message, type = 'info') {
  const status = document.getElementById('actions-status');
  if (!status) return;
  if (!message) {
    status.classList.add('d-none');
    status.textContent = '';
    return;
  }
  status.className = `alert alert-${type}`;
  status.textContent = message;
}

function updateCount(count) {
  const el = document.getElementById('actions-count');
  if (el) el.textContent = count;
}

let filtersCache = [];
let channelsCache = [];
let activeActionsMobilePane = 'list';
let actionsMobilePaneMedia = null;
const ACTIONS_MOBILE_PANE_KEY = 'norman.mobile.actions.pane.v1';

function readStoredActionsMobilePane() {
  try {
    const value = (localStorage.getItem(ACTIONS_MOBILE_PANE_KEY) || '').trim();
    return ['list', 'setup'].includes(value) ? value : null;
  } catch (err) {
    return null;
  }
}

function writeStoredActionsMobilePane(pane) {
  try {
    localStorage.setItem(ACTIONS_MOBILE_PANE_KEY, pane);
  } catch (err) {
    // ignore storage errors
  }
}

function isCompactActionsViewport() {
  return Boolean(actionsMobilePaneMedia?.matches);
}

function setActionsMobilePane(pane) {
  const page = document.querySelector('.actions-page');
  if (!page) return;
  activeActionsMobilePane = pane;
  writeStoredActionsMobilePane(pane);
  page.dataset.mobilePane = pane;
  document.querySelectorAll('[data-actions-pane]').forEach((btn) => {
    btn.classList.toggle('is-active', btn.getAttribute('data-actions-pane') === pane);
  });
}

function initActionsMobilePaneSwitcher() {
  const page = document.querySelector('.actions-page');
  const buttons = Array.from(document.querySelectorAll('[data-actions-pane]'));
  if (!page || !buttons.length) return;

  const savedPane = readStoredActionsMobilePane();
  if (savedPane) {
    activeActionsMobilePane = savedPane;
  }

  actionsMobilePaneMedia = window.matchMedia('(max-width: 991px)');
  setActionsMobilePane(activeActionsMobilePane);

  buttons.forEach((btn) => {
    btn.addEventListener('click', () => {
      setActionsMobilePane(btn.getAttribute('data-actions-pane') || 'list');
    });
  });

  const syncPaneMode = () => {
    if (isCompactActionsViewport()) {
      page.dataset.mobilePane = activeActionsMobilePane;
      return;
    }
    page.removeAttribute('data-mobile-pane');
  };
  syncPaneMode();
  if (typeof actionsMobilePaneMedia.addEventListener === 'function') {
    actionsMobilePaneMedia.addEventListener('change', syncPaneMode);
  } else if (typeof actionsMobilePaneMedia.addListener === 'function') {
    actionsMobilePaneMedia.addListener(syncPaneMode);
  }
}

function hideCollapse(id) {
  const el = document.getElementById(id);
  if (!el || !window.bootstrap?.Collapse) return;
  const instance = window.bootstrap.Collapse.getOrCreateInstance(el, { toggle: false });
  instance.hide();
}

document.addEventListener('DOMContentLoaded', () => {
  initActionsMobilePaneSwitcher();
  loadFilters();
  loadChannels();
  fetchActionsAndRender();

  const form = document.getElementById('add-action-form');
  if (form) {
    form.addEventListener('submit', async (event) => {
      event.preventDefault();
      const filterId = Number(document.getElementById('action-filter').value);
      const replyTo = Number(document.getElementById('action-reply-channel').value);
      const prompt = document.getElementById('action-prompt').value.trim();
      const order = Number(document.getElementById('action-order').value);

      if (!filterId || !replyTo || !prompt) {
        setStatus('Filter, reply channel, and prompt are required.', 'danger');
        return;
      }
      try {
        await createAction({
          channel_filter_id: filterId,
          reply_to: replyTo,
          prompt,
          execution_order: order || 1
        });
        document.getElementById('action-prompt').value = '';
        await fetchActionsAndRender();
        hideCollapse('actions-add-panel');
        if (isCompactActionsViewport()) {
          setActionsMobilePane('list');
        }
        setStatus('Action created.', 'success');
      } catch (err) {
        setStatus(err.message || 'Failed to create action.', 'danger');
      }
    });
  }
});

async function loadFilters() {
  const select = document.getElementById('action-filter');
  const resp = await fetch('/api/v1/filters/');
  filtersCache = resp.ok ? await resp.json() : [];
  if (!select) return;
  select.innerHTML = '';
  if (!filtersCache.length) {
    select.innerHTML = '<option value="" disabled selected>No filters yet</option>';
    return;
  }
  filtersCache.forEach(f => {
    const opt = document.createElement('option');
    opt.value = f.id;
    opt.textContent = `Filter ${f.id} • ${f.regex}`;
    select.appendChild(opt);
  });
}

async function loadChannels() {
  const select = document.getElementById('action-reply-channel');
  const resp = await fetch('/api/v1/channels/');
  channelsCache = resp.ok ? await resp.json() : [];
  if (!select) return;
  select.innerHTML = '';
  if (!channelsCache.length) {
    select.innerHTML = '<option value="" disabled selected>No channels yet</option>';
    return;
  }
  channelsCache.forEach(c => {
    const opt = document.createElement('option');
    opt.value = c.id;
    opt.textContent = c.name;
    select.appendChild(opt);
  });
}

async function fetchActionsAndRender() {
  const actions = await getActions();
  updateCount(actions.length);
  const container = document.querySelector('.actions-container');
  container.innerHTML = '';
  if (!actions.length) {
    const empty = document.createElement('div');
    empty.className = 'text-muted small';
    empty.textContent = 'No actions yet. Create one on the right.';
    container.appendChild(empty);
    if (isCompactActionsViewport()) {
      setActionsMobilePane('setup');
    }
    return;
  }
  actions.forEach(action => {
    container.appendChild(createActionElement(action));
  });
}

function createActionElement(action) {
  const item = document.createElement('div');
  item.className = 'list-group-item';

  const header = document.createElement('div');
  header.className = 'd-flex align-items-center justify-content-between mb-2';

  const title = document.createElement('div');
  title.className = 'fw-semibold';
  title.textContent = `Filter ${action.channel_filter_id} → Channel ${action.reply_to}`;

  const actions = document.createElement('div');
  actions.className = 'd-flex gap-2';
  const editBtn = document.createElement('button');
  editBtn.className = 'btn btn-sm btn-outline-secondary';
  editBtn.textContent = 'Edit';
  const deleteBtn = document.createElement('button');
  deleteBtn.className = 'btn btn-sm btn-outline-danger';
  deleteBtn.textContent = 'Delete';
  actions.appendChild(editBtn);
  actions.appendChild(deleteBtn);

  header.appendChild(title);
  header.appendChild(actions);
  item.appendChild(header);

  const meta = document.createElement('div');
  meta.className = 'small text-muted';
  meta.textContent = `Order ${action.execution_order}`;
  item.appendChild(meta);

  const prompt = document.createElement('div');
  prompt.className = 'small';
  prompt.textContent = action.prompt;
  item.appendChild(prompt);

  const editForm = document.createElement('div');
  editForm.className = 'filter-edit-form d-none mt-2';
  editForm.innerHTML = `
    <div class="row g-2">
      <div class="col-12 col-md-4">
        <label class="form-label">Filter</label>
        <select class="form-select form-select-sm action-edit-filter"></select>
      </div>
      <div class="col-12 col-md-4">
        <label class="form-label">Reply Channel</label>
        <select class="form-select form-select-sm action-edit-channel"></select>
      </div>
      <div class="col-12 col-md-4">
        <label class="form-label">Order</label>
        <input type="number" class="form-control form-control-sm action-edit-order" value="${action.execution_order}">
      </div>
      <div class="col-12">
        <label class="form-label">Prompt</label>
        <textarea class="form-control form-control-sm action-edit-prompt" rows="2">${action.prompt}</textarea>
      </div>
    </div>
    <div class="d-flex gap-2 mt-2">
      <button type="button" class="btn btn-sm btn-primary action-save">Save</button>
      <button type="button" class="btn btn-sm btn-outline-secondary action-cancel">Cancel</button>
    </div>
  `;
  item.appendChild(editForm);

  const filterSelect = editForm.querySelector('.action-edit-filter');
  const channelSelect = editForm.querySelector('.action-edit-channel');
  const orderInput = editForm.querySelector('.action-edit-order');
  const promptInput = editForm.querySelector('.action-edit-prompt');

  editBtn.addEventListener('click', async () => {
    document.querySelectorAll('.actions-container .filter-edit-form').forEach(form => {
      if (form !== editForm) form.classList.add('d-none');
    });
    populateFilterSelect(filterSelect, action.channel_filter_id);
    populateChannelSelect(channelSelect, action.reply_to);
    editForm.classList.toggle('d-none');
  });

  editForm.querySelector('.action-cancel').addEventListener('click', () => {
    editForm.classList.add('d-none');
  });

  editForm.querySelector('.action-save').addEventListener('click', async () => {
    const payload = {
      channel_filter_id: Number(filterSelect.value),
      reply_to: Number(channelSelect.value),
      execution_order: Number(orderInput.value) || 1,
      prompt: promptInput.value.trim()
    };
    if (!payload.channel_filter_id || !payload.reply_to || !payload.prompt) {
      setStatus('Filter, channel, and prompt are required.', 'danger');
      return;
    }
    try {
      const updated = await updateAction(action.id, payload);
      action.channel_filter_id = updated.channel_filter_id;
      action.reply_to = updated.reply_to;
      action.execution_order = updated.execution_order;
      action.prompt = updated.prompt;
      title.textContent = `Filter ${action.channel_filter_id} → Channel ${action.reply_to}`;
      meta.textContent = `Order ${action.execution_order}`;
      prompt.textContent = action.prompt;
      editForm.classList.add('d-none');
      setStatus('Action updated.', 'success');
    } catch (err) {
      setStatus(err.message || 'Failed to update action.', 'danger');
    }
  });

  deleteBtn.addEventListener('click', async () => {
    if (!confirm('Delete this action?')) return;
    try {
      await deleteAction(action.id);
      item.remove();
      setStatus('Action deleted.', 'success');
    } catch (err) {
      setStatus(err.message || 'Failed to delete action.', 'danger');
    }
  });

  return item;
}

function populateFilterSelect(select, selectedId) {
  select.innerHTML = '';
  filtersCache.forEach(f => {
    const opt = document.createElement('option');
    opt.value = f.id;
    opt.textContent = `Filter ${f.id} • ${f.regex}`;
    if (f.id === selectedId) opt.selected = true;
    select.appendChild(opt);
  });
}

function populateChannelSelect(select, selectedId) {
  select.innerHTML = '';
  channelsCache.forEach(c => {
    const opt = document.createElement('option');
    opt.value = c.id;
    opt.textContent = c.name;
    if (c.id === selectedId) opt.selected = true;
    select.appendChild(opt);
  });
}

async function getActions() {
  const resp = await fetch('/api/v1/actions/');
  return resp.ok ? await resp.json() : [];
}

async function createAction(payload) {
  const resp = await fetch('/api/v1/actions/', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload)
  });
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) {
    throw new Error(data.detail || 'Failed to create action');
  }
  return data;
}

async function updateAction(id, payload) {
  const resp = await fetch(`/api/v1/actions/${id}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload)
  });
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) {
    throw new Error(data.detail || 'Failed to update action');
  }
  return data;
}

async function deleteAction(id) {
  const resp = await fetch(`/api/v1/actions/${id}`, { method: 'DELETE' });
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) {
    throw new Error(data.detail || 'Failed to delete action');
  }
  return data;
}
