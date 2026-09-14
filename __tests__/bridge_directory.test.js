const fs = require('fs');
const path = require('path');

function loadDirectory() {
  document.body.innerHTML = '<div id="norman-bridge"></div>';
  const source = fs.readFileSync(path.join(__dirname, '../app/static/js/bridge.js'), 'utf8');
  const boot = source.lastIndexOf('\n  loadPreferences();');
  window.eval(`${source.slice(0, boot)}\nwindow.bridgeTest = { state, normalizeAgents, filteredAgents, directoryGroup };\n})();`);
  const api = window.bridgeTest;
  api.state.groups = [{ id: 'personal', slug: 'personal' }];
  api.state.group = 'personal';
  return api;
}

test('directory shows distinct consoles under their own names and excludes organizational roles', () => {
  const api = loadDirectory();
  const agents = api.normalizeAgents({ principals: [{ slug: 'personal', bots: [
    { slug: 'norman', display_name: 'Norman' },
    { slug: 'communications', display_name: 'Communications' },
    { slug: 'archivist', display_name: 'Archivist' },
  ], services: [
    { slug: 'norman-service', bot_name: 'Norman', display_name: 'Norman Service', console_url: '/bot/norman/' },
    { slug: 'uplink', bot_name: 'Communications', display_name: 'Uplink', console_url: '/bot/uplink/' },
    { slug: 'phone-ops', bot_name: 'Communications', display_name: 'Phone Ops', console_url: '/bot/phone-ops/' },
  ] }] });
  expect(agents.map(a => a.slug).sort()).toEqual(['norman', 'phone-ops', 'uplink']);
  expect(agents.find(a => a.slug === 'uplink').display_name).toBe('Uplink');
});

test('Norman stays in the first directory group when a different lane is selected', () => {
  const api = loadDirectory();
  api.state.domain = 'radio';
  api.state.agents = [
    { slug: 'norman', principal_id: 'personal', domain_slug: 'coordination' },
    { slug: 'uplink', principal_id: 'personal', domain_slug: 'radio' },
    { slug: 'work-agent', principal_id: 'work', domain_slug: 'radio' },
  ];
  expect(api.filteredAgents().map(a => a.slug)).toEqual(['norman', 'uplink']);
  expect(api.directoryGroup(api.state.agents[0])).toEqual({ key: 'norman', label: 'Coordinator', rank: 0 });
});
