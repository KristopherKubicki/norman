const fs = require('fs');
const path = require('path');

function loadDirectory() {
  document.body.innerHTML = '<div id="norman-bridge"></div>';
  const source = fs.readFileSync(path.join(__dirname, '../app/static/js/bridge.js'), 'utf8');
  const boot = source.lastIndexOf('\n  loadPreferences();');
  window.eval(`${source.slice(0, boot)}\nwindow.bridgeTest = { state, normalizeAgents, filteredAgents, directoryGroup, shouldAnimateTexture, mergeCatalogAgents, provisionalAgents, fetchEstateDirectory };\n})();`);
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
    { slug: 'finance-reader', display_name: 'Finance Reader' },
  ], services: [
    { slug: 'finance-reader', bot_name: 'Finance Reader', display_name: 'Finance Reader', web_url: '/finance/' },
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


test('phone and reduced-motion views do not run a continuous texture animation', () => {
  const api = loadDirectory();
  const original = window.matchMedia;
  window.matchMedia = () => ({ matches: true });
  expect(api.shouldAnimateTexture()).toBe(false);
  window.matchMedia = () => ({ matches: false });
  expect(api.shouldAnimateTexture()).toBe(true);
  window.matchMedia = original;
});


test('artwork and provisional identities never create phantom conversations', () => {
  const api = loadDirectory();
  api.state.textureCatalog = [{ slug: 'null-agent' }, { slug: 'retired-console' }];
  const discovered = [{ slug: 'uplink', principal_id: 'personal' }];
  expect(api.mergeCatalogAgents(discovered).map(a => a.slug)).toEqual(['norman', 'uplink']);
  expect(api.provisionalAgents().map(a => a.slug)).toEqual(['norman']);
});


test('directory recovers from a transient first-load failure without retrying denied access', async () => {
  const api = loadDirectory();
  const original = window.fetch;
  const estate = { principals: [{ slug: 'personal' }] };
  window.fetch = jest.fn()
    .mockRejectedValueOnce(new Error('timed out'))
    .mockResolvedValueOnce({ ok: true, json: async () => estate });
  await expect(api.fetchEstateDirectory()).resolves.toEqual(estate);
  expect(window.fetch).toHaveBeenCalledTimes(2);
  window.fetch = jest.fn().mockResolvedValue({ ok: false, status: 403, text: async () => '' });
  await expect(api.fetchEstateDirectory()).rejects.toMatchObject({ status: 403 });
  expect(window.fetch).toHaveBeenCalledTimes(1);
  window.fetch = original;
});
