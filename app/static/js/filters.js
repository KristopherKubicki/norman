document.addEventListener('DOMContentLoaded', () => {
  // Fetch filters and render them in the filters container
  fetchFiltersAndRender();
});

function fetchFiltersAndRender() {
  // Replace this with the actual API call to fetch filters
  const fakeFilters = [
    { id: 1, name: 'Filter 1', description: 'Filter 1 description' },
    { id: 2, name: 'Filter 2', description: 'Filter 2 description' },
  ];

  const filtersContainer = document.querySelector('.filters-container');
  filtersContainer.innerHTML = '';

  for (const filter of fakeFilters) {
    const filterElement = createFilterElement(filter);
    filtersContainer.appendChild(filterElement);
  }
}

function createFilterElement(filter) {
  const filterElement = document.createElement('div');
  filterElement.classList.add('filter');

  const nameElement = document.createElement('p');
  nameElement.textContent = filter.name;
  filterElement.appendChild(nameElement);

  const descriptionElement = document.createElement('p');
  descriptionElement.classList.add('description');
  descriptionElement.textContent = filter.description;
  filterElement.appendChild(descriptionElement);

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
    method: "PUT",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(filterData),

 });
  const filter = await response.json();
  return filter;
}

function createFilterElement(filter) {
  const filterElement = document.createElement("div");
  filterElement.classList.add("filter");

  const nameElement = document.createElement("p");
  nameElement.textContent = `Name: ${filter.name}`;

  const descriptionElement = document.createElement("p");
  descriptionElement.textContent = `Description: ${filter.description}`;

  const editButton = document.createElement("button");
  editButton.textContent = "Edit";
  editButton.addEventListener("click", async () => {
    const newName = prompt("Enter the new filter name:", filter.name);
    const newDescription = prompt("Enter the new filter description:", filter.description);

    if (newName && newDescription) {
      const updatedFilter = await updateFilter(filter.id, { name: newName, description: newDescription });
      nameElement.textContent = `Name: ${updatedFilter.name}`;
      descriptionElement.textContent = `Description: ${updatedFilter.description}`;
    }
  });

  const deleteButton = document.createElement("button");
  deleteButton.textContent = "Delete";
  deleteButton.addEventListener("click", async () => {
    await deleteFilter(filter.id);
    filterElement.remove();
  });

  filterElement.appendChild(nameElement);
  filterElement.appendChild(descriptionElement);
  filterElement.appendChild(editButton);
  filterElement.appendChild(deleteButton);

  return filterElement;
}

document.getElementById("add-filter-form").addEventListener("submit", async (event) => {
  event.preventDefault();

  const nameInput = document.getElementById("filter-name");
  const descriptionInput = document.getElementById("filter-description");

  const filterData = {
    name: nameInput.value,
    description: descriptionInput.value,
  };

  const newFilter = await createFilter(filterData);
  document.querySelector(".filters-container").appendChild(createFilterElement(newFilter));

  nameInput.value = "";
  descriptionInput.value = "";
});

(async () => {
  const filters = await getFilters();
  const filtersContainer = document.querySelector(".filters-container");

  for (const filter of filters) {
    filtersContainer.appendChild(createFilterElement(filter));
  }
})();
