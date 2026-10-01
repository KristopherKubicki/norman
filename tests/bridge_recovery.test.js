const fs = require('fs');
const source = fs.readFileSync('app/static/js/bridge.js', 'utf8');
const section = (a, b) => source.slice(source.indexOf(a), source.indexOf(b));
function harness(owner = 'alice') {
  const conversation = {kind: 'direct', direct_agent_slug: 'norman', conversation_id: 'c'};
  const prompt = {phase: 'idle'};
  const state = {prompt, stationHistory: {}, stationHistoryUpdated: {}};
  const fetch = jest.fn().mockResolvedValue({items: []});
  const bindings = {state, root: {dataset: {cacheOwner: owner}}, conversationPrompt: () => prompt,
    selectedConversation: () => conversation, composerDraftKey: () => 'c', slugify: x => x,
    fetchJson: fetch, API: '/api', historyCache: null, renderFeed: () => {}, updateComposerState: () => {},
    setConversationPromptPhase: (_c, phase, patch) => Object.assign(prompt, patch, {phase})};
  const code = section('  function stationRequestFeedback(', '  function renderJobFeed(')
    + section('  // Keep unresolved IDs across reloads;', '  function restoreFailedDraft(');
  const api = new Function(...Object.keys(bindings), code + ';return {saveStationRequest,resumeStationRequest,savedStationRequest,stationRequestFeedback};')(...Object.values(bindings));
  return {prompt,state,fetch,conversation,...api};
}
beforeEach(() => {sessionStorage.clear();jest.useFakeTimers();Object.defineProperty(navigator,'onLine',{configurable:true,value:true});});
afterEach(() => {jest.clearAllTimers();jest.useRealTimers();});
const receipt = () => ({id:'original-id',message:'Check HAL',slug:'norman',acceptedAt:Date.now(),knownTurnIds:[],queued:false});
test('reload restores accepted work using only history reads, scoped to the account', async () => {
  const first=harness();first.saveStationRequest(first.conversation,receipt());
  const resumed=harness();resumed.resumeStationRequest(resumed.conversation);await jest.advanceTimersByTimeAsync(1);
  expect(resumed.prompt.jobId).toBe('station:original-id');expect(resumed.fetch.mock.calls[0][0]).toContain('/history?');
  expect(harness('bob').savedStationRequest(resumed.conversation)).toBeNull();
});
test('five minutes without a response is still pending, never a fabricated failure', async () => {
  const h=harness();h.saveStationRequest(h.conversation,receipt());h.resumeStationRequest(h.conversation);
  await jest.advanceTimersByTimeAsync(360000);
  expect(h.prompt.phase).toBe('running');expect(h.savedStationRequest(h.conversation)).not.toBeNull();
  expect(h.stationRequestFeedback(h.prompt)).toContain('6 min ago');expect(h.fetch.mock.calls.length).toBeLessThan(50);
});
test('lost connectivity retains the receipt and resumes read-only checks', async () => {
  const h=harness();h.saveStationRequest(h.conversation,receipt());
  Object.defineProperty(navigator,'onLine',{configurable:true,value:false});h.resumeStationRequest(h.conversation);
  await jest.advanceTimersByTimeAsync(1);expect(h.fetch).not.toHaveBeenCalled();expect(h.stationRequestFeedback(h.prompt)).toContain('offline');
  Object.defineProperty(navigator,'onLine',{configurable:true,value:true});
  h.fetch.mockResolvedValue({items:[{submission_id:'original-id',response:'HAL is reachable'}]});
  await jest.advanceTimersByTimeAsync(30000);expect(h.prompt.phase).toBe('complete');expect(h.savedStationRequest(h.conversation)).toBeNull();
});
test('status errors do not convert accepted work to failure; a real task error does', async () => {
  const h=harness();h.saveStationRequest(h.conversation,receipt());h.fetch.mockRejectedValueOnce(Error('gateway timeout'));h.resumeStationRequest(h.conversation);
  await jest.advanceTimersByTimeAsync(1);expect(h.prompt.phase).toBe('running');expect(h.stationRequestFeedback(h.prompt)).toContain('Status is temporarily unavailable');
  h.fetch.mockResolvedValue({items:[{submission_id:'original-id',error:'SSH access denied'}]});
  await jest.advanceTimersByTimeAsync(30000);expect(h.prompt.phase).toBe('failed');expect(h.prompt.error).toBe('SSH access denied');
});
test('an old identical prompt cannot falsely complete newly accepted work', async () => {
  const h=harness();h.saveStationRequest(h.conversation,receipt());
  h.fetch.mockResolvedValue({items:[{prompt:'Check HAL',response:'Old response',started_at:(Date.now()-3600000)/1000}]});
  h.resumeStationRequest(h.conversation);await jest.advanceTimersByTimeAsync(1);expect(h.prompt.phase).toBe('running');
  h.fetch.mockResolvedValue({items:[{prompt:'Check HAL',response:'New response',started_at:Date.now()/1000}]});
  await jest.advanceTimersByTimeAsync(30000);expect(h.prompt.phase).toBe('complete');
});
test('repeated restoration does not create duplicate pollers', async () => {
  const h=harness();h.saveStationRequest(h.conversation,receipt());
  h.resumeStationRequest(h.conversation);h.resumeStationRequest(h.conversation);h.resumeStationRequest(h.conversation);
  await jest.advanceTimersByTimeAsync(1);expect(h.fetch).toHaveBeenCalledTimes(1);
});

test('reload honors the saved chat boundary instead of replacing it with a default chat', () => {
  const personal={kind:'direct',conversation_id:'personal',direct_agent_slug:'norman',principal_slug:'kristopher'};
  const general={...personal,conversation_id:'general',principal_slug:'general'};
  const state={view:'agent',conversations:[personal,general],groups:[]};
  const bindings={state,selectedConversation:()=>general,loadActiveConversation:()=>({directAgentSlug:'norman',principalSlug:'kristopher'}),
    saveActiveConversation:jest.fn(),slugify:x=>x||''};
  const restore=new Function(...Object.keys(bindings),section('  function restoreActiveConversation(', '  function beginSignIn(')+';return restoreActiveConversation;')(...Object.values(bindings));
  expect(restore()).toBe(personal);expect(state.selectedConversationId).toBe('personal');
});

test('early reload preserves the saved boundary while the provisional directory is loading', () => {
  const state={view:'agent',conversations:[],groups:[],agents:[{slug:'norman',principal_slug:'general'}]};
  const bindings={state,selectedConversation:()=>null,loadActiveConversation:()=>({directAgentSlug:'norman',principalSlug:'kristopher'}),
    saveActiveConversation:jest.fn(),slugify:x=>x||'',persistConversationLocally:x=>x,
    makeLocalConversation:x=>({kind:x.kind,conversation_id:'restored',principal_slug:x.principalSlug,direct_agent_slug:x.directAgentSlug}),currentGroup:()=>({slug:'general'})};
  const restore=new Function(...Object.keys(bindings),section('  function restoreActiveConversation(', '  function beginSignIn(')+';return restoreActiveConversation;')(...Object.values(bindings));
  expect(restore().principal_slug).toBe('kristopher');
});

test('session expiry pauses accepted work without losing its receipt; reauthentication resumes reads', async () => {
  const h=harness();h.saveStationRequest(h.conversation,receipt());h.state.authRequired=true;h.resumeStationRequest(h.conversation);
  await jest.advanceTimersByTimeAsync(30001);expect(h.fetch).not.toHaveBeenCalled();expect(h.savedStationRequest(h.conversation).id).toBe('original-id');expect(h.prompt.phase).toBe('running');expect(h.stationRequestFeedback(h.prompt)).toContain('Sign in');
  h.state.authRequired=false;h.fetch.mockResolvedValue({items:[{submission_id:'original-id',response:'Recovered'}]});await jest.advanceTimersByTimeAsync(30000);expect(h.prompt.phase).toBe('complete');expect(h.savedStationRequest(h.conversation)).toBeNull();
});
