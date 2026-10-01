const fs = require('fs');
const source = fs.readFileSync('app/static/js/bridge.js', 'utf8');
test('rapid search input renders once per frame with the latest query; clearing also refreshes', () => {
  const callbacks = [], previous = window.requestAnimationFrame;
  window.requestAnimationFrame = jest.fn(fn => { callbacks.push(fn); return callbacks.length; });
  try {
    const state = { search: '' }, nodes = { search: { value: '' } };
    const render = jest.fn(() => state.search);
    const code = source.slice(source.indexOf('  function scheduleDirectorySearch('), source.indexOf('  function bindEvents('));
    const search = new Function('state', 'nodes', 'renderQuickChats', 'renderDomains', 'renderWorkstreams', 'renderAgents', code + ';return scheduleDirectorySearch;')(state, nodes, render, render, render, render);
    for (const value of ['n', 'no', 'nor', 'norman']) { nodes.search.value = value; search(); }
    expect(callbacks).toHaveLength(1); expect(render).not.toHaveBeenCalled();
    callbacks[0](); expect(render.mock.results.map(r => r.value)).toEqual(Array(4).fill('norman'));
    nodes.search.value = ' Norman '; search(); expect(callbacks).toHaveLength(1);
    nodes.search.value = ''; search(); callbacks[1](); expect(render.mock.results.at(-1).value).toBe('');
  } finally { window.requestAnimationFrame = previous; }
});
test('repeated connection checks preserve live status nodes, while failures still update promptly', () => {
  document.body.innerHTML = '<div id="status"><span class="cockpit-transport__label"></span><span class="cockpit-transport__icon"></span></div><div id="menu"></div>';
  const previous = window.BridgeNavigation;
  window.eval(fs.readFileSync('app/static/js/bridge_navigation.js', 'utf8'));
  try {
    const nodes = { runtimeStatus: document.querySelector('#status'), menuTransport: document.querySelector('#menu') };
    const state = { connection: { connected: true, failed: false } };
    const code = source.slice(source.indexOf('  function renderConnection('), source.indexOf('  function conversationPreview('));
    const render = new Function('nodes', 'state', 'iconHtml', code + ';return renderConnection;')(nodes, state, icon => `<svg data-icon="${icon}"></svg>`);
    render(); const label = nodes.runtimeStatus.firstChild.firstChild, icon = nodes.runtimeStatus.querySelector('svg'), menuText = nodes.menuTransport.firstChild;
    for (let i = 0; i < 20; i++) render();
    expect(nodes.runtimeStatus.firstChild.firstChild).toBe(label); expect(nodes.runtimeStatus.querySelector('svg')).toBe(icon); expect(nodes.menuTransport.firstChild).toBe(menuText);
    state.connection.failed = true; render();
    expect(nodes.runtimeStatus.textContent).toBe('Reconnecting'); expect(nodes.runtimeStatus.querySelector('svg').dataset.icon).toBe('alert');
  } finally { window.BridgeNavigation = previous; }
});
