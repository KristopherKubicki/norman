const fs=require('fs');
const source=fs.readFileSync('app/static/js/bridge.js','utf8');
const boot=source.slice(source.indexOf('  async function loadBootstrap('),source.indexOf('  async function hydrateConversationActivities('));
function harness(cached=false) {
 const nodes={bootInterstitial:{hidden:false},bootActivity:{textContent:''}};
 const state={loading:false,bootstrapped:false,boot:{},authRequired:false,agents:[{},{}],conversations:[],stationHistory:{},worker:{}};
 const update=jest.fn(({complete})=>{nodes.bootInterstitial.hidden=Boolean(complete)});
 const bindings={state,nodes,root:{dataset:{}},historyCache:{get:()=>cached?{items:[]}:null},startBootActivity:()=>{},updateBootInterstitial:update,
 loadLocalConversations:()=>[],renderRuntime:()=>{},provisionalAgents:()=>[],restoreActiveConversation:()=>null,restoreComposerDraft:()=>{},renderAll:()=>{},loadStationHistory:()=>{},applyEstateDirectory:()=>{},loadPrograms:()=>{},
 fetchJson:jest.fn(async()=>({items:[]})),fetchEstateDirectory:async()=>({}),API:'/api',bootUpdateForRequest:()=>{},restoreAfterSignIn:()=>{},mergeConversations:()=>{},discardNonConversationalDirectConversations:()=>{},reconcilePromptState:()=>{},selectedConversation:()=>null,hydrateConversationActivities:()=>{},mergeCatalogAgents:x=>x};
 const load=new Function(...Object.keys(bindings),boot+';return loadBootstrap;')(...Object.values(bindings));
 return {load,nodes,state,update,fetch:bindings.fetchJson};
}
test('cached startup never leaves the initial loading banner visible',async()=>{
 const h=harness(true);await h.load();expect(h.nodes.bootInterstitial.hidden).toBe(true);
});
test('uncached startup dismisses its banner after loading',async()=>{
 const h=harness();await h.load();expect(h.nodes.bootInterstitial.hidden).toBe(true);expect(h.state.loading).toBe(false);
});

test('slow background requests do not bring the banner back after handoff',async()=>{
 jest.useFakeTimers();
 try {
  const h=harness();let resolve;const delayed=new Promise(r=>{resolve=r});h.fetch.mockReturnValue(delayed);
  const loading=h.load();jest.advanceTimersByTime(1400);expect(h.nodes.bootInterstitial.hidden).toBe(true);
  resolve({items:[]});await loading;
  expect(h.update.mock.calls.filter(([value])=>value.complete)).toHaveLength(1);
  expect(h.nodes.bootInterstitial.hidden).toBe(true);
 } finally {jest.useRealTimers();}
});
