const fs = require('fs');
const source = fs.readFileSync('app/static/js/bridge.js', 'utf8');
test('clear search restores all results and returns focus without touching a draft', () => {
  document.body.innerHTML = '<input value="missing"><textarea>Unsent draft</textarea><button>Clear search</button>';
  const nodes = { search: document.querySelector('input') };
  document.querySelector('button').focus();
  const schedule = jest.fn(() => expect(nodes.search.value).toBe(''));
  const code = source.slice(source.indexOf('  function clearDirectorySearch('), source.indexOf('  function scheduleDirectorySearch('));
  const clear = new Function('nodes', 'scheduleDirectorySearch', code + ';return clearDirectorySearch;')(nodes, schedule);
  clear(); expect(schedule).toHaveBeenCalledTimes(1);
  expect(document.activeElement).toBe(nodes.search);
  expect(document.querySelector('textarea').value).toBe('Unsent draft');
});
