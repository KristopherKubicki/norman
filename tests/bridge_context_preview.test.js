const fs = require('fs');
const source = fs.readFileSync('app/static/js/bridge.js', 'utf8');
const code = source.slice(source.indexOf('  function conversationPreview('), source.indexOf('  function renderQuickChats('));
function harness({ history = {}, cached = null, job = null, authRequired = false } = {}) {
  return new Function('state', 'latestConversationJob', 'jobObjective', 'slugify', 'historyCache', 'truncate', code + ';return conversationPreview;')(
    { stationHistory: history, authRequired }, () => job, j => j.objective, x => x,
    { get: () => cached }, (text, max) => text.slice(0, max));
}
const chat = { kind: 'direct', direct_agent_slug: 'norman' };
test('recent context uses newest task even when history is out of order', () => {
  const preview = harness({ history: { norman: { items: [
    { prompt: 'Newest\n task', started_at: '2026-09-29' },
    { prompt: 'Old task', started_at: '2026-09-28' },
  ] } }, job: { objective: 'Older job', created_at: '2026-09-27' } });
  expect(preview(chat)).toBe('Newest task');
});
test('reload can show saved context before live history arrives, but live empty history replaces it', () => {
  const cached = { items: [{ prompt: 'Saved task', started_at: '2026-09-29' }] };
  expect(harness({ cached })(chat)).toBe('Saved task');
  expect(harness({ cached, history: { norman: { items: [] } } })(chat)).toBe('');
});
test('auth expiry hides previews and room previews never borrow station history', () => {
  const cached = { items: [{ prompt: 'Private task' }] };
  expect(harness({ cached, authRequired: true })(chat)).toBe('');
  expect(harness({ cached })({ kind: 'room' })).toBe('');
});
test('a restored current chat stays in recent chats without overriding search results', () => {
  document.body.innerHTML = '<div id="bridge-quick-chats"></div>';
  const state = { conversations: [], search: '', selectedConversationId: 'restored' };
  const current = { ...chat, conversation_id: 'restored', title: 'Norman', principal_slug: 'personal' };
  const renderCode = source.slice(source.indexOf('  function renderQuickChats('), source.indexOf('  function renderActivity('));
  const bindings = { state, el: id => document.getElementById(id), selectedConversation: () => current,
    chatNavigation: { list: () => [], pinned: () => false }, escapeHtml: x => x, displaySlug: x => x,
    conversationPreview: () => 'Resume previous task', updateNavigationMarkup: (node, html) => { node.innerHTML = html; } };
  const render = new Function(...Object.keys(bindings), renderCode + ';return renderQuickChats;')(...Object.values(bindings));
  render();
  expect(document.querySelector('[data-conversation-id="restored"]').textContent).toContain('Resume previous task');
  state.search = 'unrelated'; render();
  expect(document.querySelector('[data-conversation-id="restored"]')).toBeNull();
});
