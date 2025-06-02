function timeAgo(dateStr) {
  const date = new Date(dateStr);
  const seconds = Math.floor((Date.now() - date.getTime()) / 1000);
  const rtf = new Intl.RelativeTimeFormat('en', { numeric: 'auto' });
  const ranges = {
    year: 31536000,
    month: 2592000,
    day: 86400,
    hour: 3600,
    minute: 60,
    second: 1,
  };
  for (const [unit, value] of Object.entries(ranges)) {
    if (Math.abs(seconds) >= value || unit === 'second') {
      const delta = Math.floor(seconds / value);
      return rtf.format(-delta, unit);
    }
  }
}

async function fetchCaptions() {
  const resp = await fetch('/api/captions');
  if (!resp.ok) return;
  const captions = await resp.json();
  const tbody = document.querySelector('#captions-table tbody');
  tbody.innerHTML = '';
  captions.forEach(cap => {
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td><img src="${cap.thumbnail_url}" class="caption-thumb"></td>
      <td>${cap.text}</td>
      <td data-time="${cap.created_at}">${timeAgo(cap.created_at)}</td>`;
    tbody.appendChild(tr);
  });
}

function sortTable(th) {
  const table = th.closest('table');
  const tbody = table.querySelector('tbody');
  const index = Array.from(th.parentNode.children).indexOf(th);
  const type = th.dataset.type || 'string';
  const asc = !(th.dataset.sort === 'asc');
  th.dataset.sort = asc ? 'asc' : 'desc';
  const rows = Array.from(tbody.querySelectorAll('tr'));
  rows.sort((a, b) => {
    let aVal = a.children[index].textContent.trim();
    let bVal = b.children[index].textContent.trim();
    if (type === 'time') {
      aVal = new Date(a.children[index].dataset.time).getTime();
      bVal = new Date(b.children[index].dataset.time).getTime();
    }
    return (aVal > bVal ? 1 : aVal < bVal ? -1 : 0) * (asc ? 1 : -1);
  });
  tbody.innerHTML = '';
  rows.forEach(r => tbody.appendChild(r));
}

document.addEventListener('DOMContentLoaded', () => {
  fetchCaptions();
  document.querySelectorAll('#captions-table th').forEach(th => {
    th.addEventListener('click', () => sortTable(th));
  });
});
