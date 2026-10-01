const fs = require('fs');
const source = fs.readFileSync('app/static/js/bridge.js', 'utf8');
const section = (a, b) => source.slice(source.indexOf(a), source.indexOf(b));
const deferred = () => { let resolve, reject; const promise = new Promise((a,b) => {resolve=a;reject=b;}); return {promise,resolve,reject}; };
function activityHarness() {
  const state = {selectedJobId:'a'}, fetchJson=jest.fn(), connect=jest.fn();
  const nodes={feed:{innerHTML:'current'}};
  const load=new Function('state','fetchJson','nodes','API','reconcilePromptState','renderFeed','renderInspector','renderRoom','connectJobEventStream','escapeHtml',section('  async function loadSelectedActivity(', '  function closeEventStream(')+';return loadSelectedActivity;')(state,fetchJson,nodes,'/api',()=>{},()=>{},()=>{},()=>{},connect,x=>x);
  return {state,fetchJson,nodes,connect,load};
}
test('late task response cannot replace a newer selection or event stream',async()=>{
  const h=activityHarness(),old=deferred();h.fetchJson.mockReturnValueOnce(old.promise).mockResolvedValueOnce({job:{job_id:'b'},events:[{sequence:7}]});
  const first=h.load();h.state.selectedJobId='b';await h.load();old.resolve({job:{job_id:'a'},events:[{sequence:99}]});await first;
  expect(h.state.activity.job.job_id).toBe('b');expect(h.state.lastEventSequence).toBe(7);expect(h.connect.mock.calls).toEqual([['b']]);
});
test('late workstream response is ignored after navigating away',async()=>{
  const h=activityHarness(),work=deferred();h.fetchJson.mockResolvedValueOnce({job:{workstream_id:'w'},events:[]}).mockReturnValueOnce(work.promise);
  const pending=h.load();await Promise.resolve();h.state.selectedJobId='';work.resolve({id:'w'});await pending;
  expect(h.state.activity).toBeUndefined();expect(h.connect).not.toHaveBeenCalled();
});
test('older failure cannot replace the current feed',async()=>{
  const h=activityHarness(),old=deferred();h.fetchJson.mockReturnValue(old.promise);const pending=h.load();h.state.selectedJobId='b';old.reject(Error('offline'));await pending;expect(h.nodes.feed.innerHTML).toBe('current');
});
test('latest refresh wins even when the task id is unchanged',async()=>{
  const h=activityHarness(),old=deferred();h.fetchJson.mockReturnValueOnce(old.promise).mockResolvedValueOnce({job:{job_id:'a'},events:[{sequence:8}]});const first=h.load();await h.load();old.resolve({job:{job_id:'a'},events:[{sequence:1}]});await first;expect(h.state.lastEventSequence).toBe(8);
});
function draftHarness(current='a') {
  const state={composerDrafts:{}},nodes={message:{value:''}},key=c=>c?.id||current;
  const save=(c,text)=>{state.composerDrafts[key(c)]=text;};
  const restore=new Function('state','nodes','composerDraftKey','saveComposerDraft','resizeComposer',section('  function restoreFailedDraft(', '  async function submitMessage(')+';return restoreFailedDraft;')(state,nodes,key,save,()=>{});
  return {state,nodes,restore};
}
test('failed send recovers into its original chat without changing the current draft',()=>{
  const h=draftHarness('b');h.nodes.message.value='Draft for B';h.restore({id:'a'},'Sent to A');expect(h.nodes.message.value).toBe('Draft for B');expect(h.state.composerDrafts.a).toBe('Sent to A');
});
test('failed send retains typing entered while the request was pending',()=>{
  const h=draftHarness();h.nodes.message.value='Next thought';h.restore({id:'a'},'Failed message');expect(h.nodes.message.value).toBe('Failed message\n\nNext thought');
});
test('failed send also preserves a newer saved draft in the original chat',()=>{
  const h=draftHarness('b');h.state.composerDrafts.a='New draft';h.restore({id:'a'},'Failed message');expect(h.state.composerDrafts.a).toBe('Failed message\n\nNew draft');
});
test('events queued by a closed stream cannot leak into the newly selected task',()=>{
  const streams=[];class FakeSource { constructor(){this.listeners={};streams.push(this);} addEventListener(type,handler){this.listeners[type]=handler;} close(){} }
  const state={lastEventSequence:0},handle=jest.fn();
  window.EventSource=FakeSource;
  const connect=new Function('state','EventSource','API','closeEventStream','handleRuntimeEvent',section('  function connectJobEventStream(', '  async function decideApproval(')+';return connectJobEventStream;')(state,FakeSource,'/api',()=>{state.eventSource?.close();state.eventSource=null;},handle);
  connect('a');connect('b');streams[0].listeners['job.started']({data:'old'});streams[1].listeners['job.started']({data:'new'});
  expect(handle.mock.calls).toEqual([[{data:'new'}]]);delete window.EventSource;
});
test('replayed progress events are applied only once',()=>{
  const state={eventSourceJobId:'a',lastEventSequence:0,jobs:[{job_id:'a'}],jobActivities:{},prompt:{jobId:'a'},selectedJobId:'',activity:null};
  const phase=jest.fn();
  const handle=new Function('state','promptPhaseForEvent','setPromptPhase','playInteractionTone','responseIdentity','playCompletionBell','renderFeed','renderInspector','renderRoom','renderGeneralFeed','loadBootstrap','loadSelectedActivity',section('  function handleRuntimeEvent(', '  function connectJobEventStream(')+';return handleRuntimeEvent;')(state,()=> 'running',phase,()=>{},()=>({}),()=>{},()=>{},()=>{},()=>{},()=>{},()=>{},()=>{});
  const message={data:JSON.stringify({sequence:5,event_type:'job.started'})};handle(message);handle(message);
  expect(state.jobActivities.a.events).toHaveLength(1);expect(phase).toHaveBeenCalledTimes(1);
});
test('conversation drafts survive reload without crossing chats',()=>{
  sessionStorage.clear();
  const storeSource=section('  function loadComposerDrafts()', '  function conversationIdentity(');
  const state={composerDrafts:{'direct:home:housebot':'House draft','direct:home:norman':'Norman draft'}};
  const storage=new Function('state','COMPOSER_DRAFTS_KEY',storeSource+';return {load:loadComposerDrafts,save:saveComposerDrafts};')(state,'workflow-drafts');
  storage.save();state.composerDrafts={};expect(storage.load()).toEqual({'direct:home:housebot':'House draft','direct:home:norman':'Norman draft'});
  sessionStorage.clear();
});
test('corrupt saved drafts do not prevent the composer from opening',()=>{
  sessionStorage.setItem('workflow-drafts','invalid-json');
  const load=new Function('COMPOSER_DRAFTS_KEY',section('  function loadComposerDrafts()', '  function saveComposerDrafts()')+';return loadComposerDrafts;')('workflow-drafts');
  expect(load()).toEqual({});sessionStorage.clear();
});
