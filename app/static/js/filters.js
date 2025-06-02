document.addEventListener('DOMContentLoaded', () => {
  loadChannels();
  fetchFiltersAndRender();
});

async function loadChannels() {
  const resp = await fetch('/api/v1/channels');
  const channels = await resp.json();
  const select = document.getElementById('filter-channel');
  select.innerHTML = '';
  channels.forEach(c => {
    const opt = document.createElement('option');
    opt.value = c.id;
    opt.textContent = c.name;
    select.appendChild(opt);
  });
}

async function fetchFiltersAndRender() {
  const filters = await getFilters();
  const filtersContainer = document.querySelector('.filters-container');
  filtersContainer.innerHTML = '';
  for (const filter of filters) {
    const filterElement = createFilterElement(filter);
    filtersContainer.appendChild(filterElement);
  }
}

function createFilterElement(filter) {
  const filterElement = document.createElement('div');
  filterElement.classList.add('filter');

  const info = document.createElement('p');
  info.textContent = `Channel: ${filter.channel_id} | Regex: ${filter.regex}`;
  filterElement.appendChild(info);

  if (filter.description) {
    const desc = document.createElement('p');
    desc.classList.add('description');
    desc.textContent = filter.description;
    filterElement.appendChild(desc);
  }

  const editButton = document.createElement('button');
  editButton.textContent = 'Edit';
  editButton.addEventListener('click', async () => {
    const newRegex = prompt('Regex', filter.regex);
    const newDesc = prompt('Description', filter.description || '');
    if (newRegex) {
      const updated = await updateFilter(filter.id, {
        channel_id: filter.channel_id,
        regex: newRegex,
        description: newDesc,
      });
      info.textContent = `Channel: ${updated.channel_id} | Regex: ${updated.regex}`;
      desc && (desc.textContent = updated.description);
    }
  });

  const deleteButton = document.createElement('button');
  deleteButton.textContent = 'Delete';
  deleteButton.addEventListener('click', async () => {
    await deleteFilter(filter.id);
    filterElement.remove();
  });

  filterElement.appendChild(editButton);
  filterElement.appendChild(deleteButton);
  return filterElement;
}


async function getFilters() {
  const response = await fetch("/api/v1/filters");
  const filters = await response.json();
  return filters;
}

async function createFilter(filterData) {
  const response = await fetch("/api/v1/filters", {
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
  await fetch(`/api/v1/filters/${filterId}`, {
    method: "DELETE",
  });
}

async function updateFilter(filterId, filterData) {
  const response = await fetch(`/api/v1/filters/${filterId}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(filterData),
  });
  const filter = await response.json();
  return filter;
}

document.getElementById('add-filter-form').addEventListener('submit', async (event) => {
  event.preventDefault();

  const channelSelect = document.getElementById('filter-channel');
  const regexInput = document.getElementById('filter-regex');
  const descriptionInput = document.getElementById('filter-description');

  const filterData = {
    channel_id: parseInt(channelSelect.value, 10),
    regex: regexInput.value,
    description: descriptionInput.value,
  };

  const newFilter = await createFilter(filterData);
  document.querySelector('.filters-container').appendChild(createFilterElement(newFilter));

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
