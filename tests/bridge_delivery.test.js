const fs = require('fs');
const source = fs.readFileSync('app/static/js/bridge.js', 'utf8');
const slice = (a,b) => source.slice(source.indexOf(a),source.indexOf(b));
function harness({direct=true, owner='alice'}={}) {
  let conversation={kind:direct?'direct':'room',direct_agent_slug:'housebot',conversation_id:'c',_local_only:true};
  const state={prompt:{phase:'idle'},worker:{},stationHistory:{},composerDrafts:{},selectedRecipients:[],jobs:[]};
  const nodes={message:{value:'Do it once'}};
  const post=jest.fn(),fetch=jest.fn(),wait=jest.fn();
  const phase=(p,patch={})=>{Object.assign(state.prompt,patch,{phase:p});};
  const bindings={root:{dataset:{cacheOwner:owner}},state,nodes,selectedConversation:()=>conversation,
    composerDraftKey:c=>(c||conversation).conversation_id,slugify:x=>x,promptBusy:()=>['submitting','queued','running'].includes(state.prompt.phase),

    currentGroup:()=>({slug:'personal'}),currentDomain:()=>null,setPromptPhase:phase,
    saveComposerDraft:(_c,text)=>{state.composerDrafts.c=text;},resizeComposer:()=>{},renderFeed:()=>{},
    playInteractionTone:()=>{},postJson:post,fetchJson:fetch,API:'/api',waitForStationResponse:wait,
    loadBootstrap:async()=>{},connectJobEventStream:()=>{},updateComposerState:()=>{},crypto:{randomUUID:()=>`id-${Math.random()}`}};
  const promptHelpers=new Function(...Object.keys(bindings),slice('  function conversationPrompt(', '  function restoreComposerDraft(')+';return {activateConversationPrompt,setConversationPromptPhase,conversationPrompt};')(...Object.values(bindings));
  Object.assign(bindings,promptHelpers);
  promptHelpers.activateConversationPrompt(conversation);
  const functions=slice('  // Keep unresolved IDs across reloads;', '  async function cancelSelectedJob(');
  const api=new Function(...Object.keys(bindings),functions+';return {submitMessage,pendingDelivery};')(...Object.values(bindings));
  return {state,nodes,post,fetch,wait,submit:()=>api.submitMessage({preventDefault(){}}),pending:api.pendingDelivery,switchChat:(id)=>{conversation={...conversation,conversation_id:id,direct_agent_slug:id};promptHelpers.activateConversationPrompt(conversation);},promptFor:id=>state.promptByConversation[id]};
}
beforeEach(()=>sessionStorage.clear());
test('lost acceptance response reuses the ID after reload and preserves newer typing',async()=>{
  const first=harness();first.post.mockRejectedValue(Error('connection reset'));await first.submit();
  const id=first.post.mock.calls[0][1].submission_id;expect(first.pending().id).toBe(id);
  const resumed=harness();resumed.nodes.message.value='A different next message';
  resumed.post.mockResolvedValue({accepted:true,running:true});await resumed.submit();
  expect(resumed.post.mock.calls[0][1]).toMatchObject({submission_id:id,message:'Do it once'});
  expect(resumed.nodes.message.value).toBe('A different next message');expect(resumed.pending()).toBeNull();
});
test('unknown delivery retains the same ID for repeated receipt checks',async()=>{
  const h=harness();h.post.mockResolvedValue({accepted:false,submission_state:'unknown',safe_to_retry:false});await h.submit();const id=h.pending().id;await h.submit();
  expect(h.post.mock.calls.map(c=>c[1].submission_id)).toEqual([id,id]);expect(h.pending().id).toBe(id);
});
test('explicit rejection restores the draft and permits a fresh attempt',async()=>{
  const h=harness();h.post.mockResolvedValueOnce({accepted:false,safe_to_retry:true,error:'Capacity full'}).mockResolvedValueOnce({accepted:true});await h.submit();expect(h.nodes.message.value).toBe('Do it once');expect(h.pending()).toBeNull();await h.submit();expect(h.post.mock.calls[1][1].submission_id).not.toBe(h.post.mock.calls[0][1].submission_id);
});
test('unresolved delivery belongs to the signed-in account',async()=>{
  const h=harness();h.post.mockRejectedValue(Error('offline'));await h.submit();expect(harness({owner:'bob'}).pending()).toBeNull();expect(harness().pending()).not.toBeNull();
});
test('runtime timeout checks the original task and never starts a second run',async()=>{
  const h=harness({direct:false});h.post.mockImplementation(async(url,body)=>{if(url.endsWith('/jobs'))return {job_id:body.job_id};throw Error('lost run response');});await h.submit();expect(h.post).toHaveBeenCalledTimes(2);const id=h.pending().id;
  h.fetch.mockResolvedValue({job:{job_id:id,status:'completed'}});await h.submit();expect(h.post).toHaveBeenCalledTimes(2);expect(h.fetch.mock.calls[0][0]).toContain(id);expect(h.pending()).toBeNull();
});
test('a missing runtime receipt stays uncertain instead of recreating the task',async()=>{
  const h=harness({direct:false});h.post.mockRejectedValue(Error('timeout'));await h.submit();h.fetch.mockRejectedValue(Object.assign(Error('not found'),{status:404}));await h.submit();expect(h.post).toHaveBeenCalledTimes(1);expect(h.pending()).not.toBeNull();
});

test.each([400, 401, 403, 409, 422, 429, 503])('HTTP %s during an uncertain delivery check preserves the original receipt', async status => {
  const h = harness();h.post.mockRejectedValueOnce(Error('lost acknowledgement'));await h.submit();const id=h.pending().id;
  h.nodes.message.value='My next draft';h.post.mockRejectedValueOnce(Object.assign(Error('Check unavailable'),{status}));await h.submit();
  expect(h.pending().id).toBe(id);expect(h.nodes.message.value).toBe('My next draft');expect(h.state.prompt.phase).toBe('unconfirmed');
  h.post.mockResolvedValueOnce({accepted:true});await h.submit();expect(h.post.mock.calls[2][1].submission_id).toBe(id);
});

test('another chat can send while the first acceptance is pending; late receipt stays with its chat', async () => {
  const h = harness();
  let acceptFirst;
  h.post.mockImplementationOnce(() => new Promise(resolve => {acceptFirst=resolve;}));
  const first=h.submit();
  expect(h.state.prompt.phase).toBe('submitting');
  h.switchChat('netops');h.nodes.message.value='Check the network';
  expect(h.state.prompt.phase).toBe('idle');
  h.post.mockResolvedValueOnce({accepted:true,running:true});await h.submit();
  const secondJob=h.state.prompt.jobId;
  acceptFirst({accepted:true,queued:true});await first;
  expect(h.post).toHaveBeenCalledTimes(2);
  expect(h.state.prompt.jobId).toBe(secondJob);
  expect(h.state.prompt.phase).toBe('running');
  expect(h.promptFor('c').phase).toBe('queued');
  h.switchChat('c');expect(h.state.prompt.phase).toBe('queued');
});

test('offline submission preserves the draft without creating an uncertain delivery', async () => {
  const h=harness();Object.defineProperty(navigator,'onLine',{configurable:true,value:false});
  try {await h.submit();expect(h.post).not.toHaveBeenCalled();expect(h.pending()).toBeNull();expect(h.nodes.message.value).toBe('Do it once');expect(h.state.prompt.phase).toBe('idle');}
  finally {Object.defineProperty(navigator,'onLine',{configurable:true,value:true});}
});
test('expired authentication blocks keyboard submission without clearing the draft', async () => {
  const h=harness();h.state.authRequired=true;await h.submit();
  expect(h.post).not.toHaveBeenCalled();expect(h.nodes.message.value).toBe('Do it once');expect(h.pending()).toBeNull();
});
test('going offline preserves an existing unresolved delivery ID', async () => {
  const h=harness();h.post.mockRejectedValue(Error('lost reply'));await h.submit();const id=h.pending().id;
  Object.defineProperty(navigator,'onLine',{configurable:true,value:false});
  try {await h.submit();expect(h.pending().id).toBe(id);expect(h.post).toHaveBeenCalledTimes(1);}
  finally {Object.defineProperty(navigator,'onLine',{configurable:true,value:true});}
});

test('explicit safe-to-retry confirmation can release an earlier uncertain receipt',async()=>{
  const h=harness();h.post.mockRejectedValueOnce(Error('lost reply'));await h.submit();
  h.post.mockResolvedValueOnce({accepted:false,safe_to_retry:true,error:'Original request was not accepted'});await h.submit();expect(h.pending()).toBeNull();expect(h.nodes.message.value).toBe('Do it once');
});
