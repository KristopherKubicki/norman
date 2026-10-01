const fs = require('fs');
const cacheSource = fs.readFileSync('app/static/js/bridge_cache.js', 'utf8');
const source = fs.readFileSync('app/static/js/bridge.js', 'utf8');
const historySource = source.slice(source.indexOf('  async function loadStationHistory('), source.indexOf('  async function waitForStationResponse('));
const deferred = () => {
  let resolve, reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
};

beforeEach(() => {
  sessionStorage.clear();
  window.eval(cacheSource);
});

test('snapshots survive a reload but expire and never cross accounts', () => {
  const cache = window.createBridgeCache('alice');
  cache.set('history:housebot', { items: [{ response: 'saved' }] });
  expect(window.createBridgeCache('alice').get('history:housebot').items).toHaveLength(1);
  const now = jest.spyOn(Date, 'now').mockReturnValue(Date.now() + 31 * 60000);
  expect(cache.get('history:housebot')).toBeNull();
  now.mockRestore();
  expect(window.createBridgeCache('bob').get('history:housebot')).toBeNull();
  expect(window.createBridgeCache('alice').get('history:housebot')).toBeNull();
});

test('cache is bounded and storage failures do not prevent use', () => {
  const cache = window.createBridgeCache('alice');
  for (let i = 0; i < 12; i++) cache.set(`history:${i}`, { items: [i] });
  expect(Object.keys(JSON.parse(sessionStorage.getItem('norman-bridge-snapshots-v1')).entries)).toHaveLength(8);
  const broken = window.createBridgeCache('alice', { getItem() { throw Error(); }, setItem() { throw Error(); }, removeItem() { throw Error(); } });
  expect(() => broken.set('x', { items: [] })).not.toThrow();
  expect(broken.get('x')).toEqual({ items: [] });
  broken.clear();
  expect(broken.get('x')).toBeNull();
});

function harness() {
  const state = { authRequired: false, stationHistory: {}, stationHistoryLoaded: {}, stationHistoryLoading: new Set(), stationHistoryRequests: {}, stationHistoryUpdated: {}, stationHistoryErrors: {} };
  const cache = window.createBridgeCache('alice');
  const fetchJson = jest.fn();
  const render = jest.fn();
  const load = new Function('state', 'historyCache', 'fetchJson', 'renderFeed', 'updateComposerState', 'slugify', 'selectedConversation', 'API', 'renderRoom', 'renderQuickChats', `${historySource}; return loadStationHistory;`)(state, cache, fetchJson, render, () => {}, x => x || '', () => ({ direct_agent_slug: 'housebot' }), '/api/v1', jest.fn(), jest.fn());
  return { state, cache, fetchJson, render, load };
}

test('cached messages render before the network resolves, then update', async () => {
  const h = harness(), request = deferred();
  h.cache.set('history:housebot', { items: [{ response: 'cached' }] });
  h.fetchJson.mockReturnValue(request.promise);
  const load = h.load('housebot');
  expect(h.state.stationHistory.housebot.items[0].response).toBe('cached');
  expect(h.state.stationHistoryLoading.has('housebot')).toBe(true);
  expect(h.render).toHaveBeenCalled();
  request.resolve({ items: [{ response: 'fresh' }] });
  await load;
  expect(h.state.stationHistory.housebot.items[0].response).toBe('fresh');
  expect(h.state.stationHistoryLoading.size).toBe(0);
  await h.load('housebot');
  expect(h.fetchJson).toHaveBeenCalledTimes(1);
});

test('switching stations deduplicates requests and tracks each pending load', async () => {
  const h = harness(), first = deferred(), second = deferred();
  h.fetchJson.mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise);
  const a = h.load('housebot'), b = h.load('castle'), again = h.load('housebot', { force: true });
  expect(h.fetchJson).toHaveBeenCalledTimes(2);
  expect(h.state.stationHistoryLoading.size).toBe(2);
  first.resolve({ items: [] });
  await a;
  expect(h.state.stationHistoryLoading.has('castle')).toBe(true);
  second.resolve({ items: [] });
  await Promise.all([b, again]);
  expect(h.state.stationHistoryLoading.size).toBe(0);
});

test('failed refresh retains cached messages and retry can recover', async () => {
  const h = harness();
  h.cache.set('history:housebot', { items: [{ response: 'cached' }] });
  h.fetchJson.mockRejectedValueOnce(Error('offline')).mockResolvedValueOnce({ items: [{ response: 'recovered' }] });
  await h.load('housebot');
  expect(h.state.stationHistory.housebot.items[0].response).toBe('cached');
  expect(h.state.stationHistoryErrors.housebot).toBe('offline');
  await h.load('housebot', { force: true });
  expect(h.state.stationHistory.housebot.items[0].response).toBe('recovered');
  expect(h.state.stationHistoryErrors.housebot).toBeUndefined();
});

test('authorization failure removes saved messages', async () => {
  const h = harness();
  h.cache.set('history:housebot', { items: [{ response: 'cached' }] });
  h.fetchJson.mockRejectedValue(Object.assign(Error('sign in'), { status: 401 }));
  await h.load('housebot');
  expect(h.state.stationHistory.housebot).toBeUndefined();
  expect(h.cache.get('history:housebot')).toBeNull();
});
