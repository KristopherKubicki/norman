const fs=require('fs');
const source=fs.readFileSync('app/static/js/bridge.js','utf8');
const section=(a,b)=>source.slice(source.indexOf(a),source.indexOf(b));
function keyboard() {
  const nodes={message:{focus:jest.fn()},feed:{scrollTop:20,scrollHeight:999}};
  const close=jest.fn();
  const handler=new Function('nodes','closeDrawers','setMenuOpen','setWorkspaceMenuOpen',section('  function handleGlobalKeydown(','  function bindEvents(')+';return handleGlobalKeydown;')(nodes,close,()=>{},()=>{});
  return {nodes,handler,close};
}
test.each(['input','textarea','select','div contenteditable="true"'])('shortcuts do not steal typing from %s',tag=>{
  const h=keyboard();document.body.innerHTML=`<${tag} id="edit"></${tag.split(' ')[0]}>`;
  for(const key of ['/','End']){const preventDefault=jest.fn();h.handler({key,target:document.getElementById('edit'),preventDefault});expect(preventDefault).not.toHaveBeenCalled();}
  expect(h.nodes.message.focus).not.toHaveBeenCalled();expect(h.nodes.feed.scrollTop).toBe(20);
});
test('shortcuts work outside editors without stealing modified keys',()=>{
  const h=keyboard(),preventDefault=jest.fn();h.handler({key:'/',target:document.body,preventDefault});expect(h.nodes.message.focus).toHaveBeenCalledTimes(1);
  h.handler({key:'/',ctrlKey:true,target:document.body,preventDefault});expect(h.nodes.message.focus).toHaveBeenCalledTimes(1);
});
test('refreshing the current draft leaves the cursor position alone',()=>{
  const input=document.createElement('textarea');input.value='a long draft';input.setSelectionRange(2,2);
  const restore=new Function('nodes','state','composerDraftKey','selectedConversation','resizeComposer','updateComposerState','activateConversationPrompt','resumeStationRequest',section('  function restoreComposerDraft(','  function restoreActiveConversation(')+';return restoreComposerDraft;')({message:input},{composerDrafts:{a:'a long draft'}},()=> 'a',()=>({}),()=>{},()=>{},()=>{},()=>{});
  restore();expect(input.selectionStart).toBe(2);
});
function requests() {
  const state={connection:{},authRequired:false},fetch=jest.fn();
  const request=new Function('state','fetch','renderConnection',section('  class BridgeRequestError','  async function fetchEstateDirectory(')+';return fetchJson;')(state,fetch,()=>{});
  return {state,fetch,request};
}
test('expired session from any API is reported as authentication failure',async()=>{
  const h=requests();h.fetch.mockResolvedValue({status:401,ok:false});await expect(h.request('/api/v1/jobs')).rejects.toMatchObject({status:401});expect(h.state.authRequired).toBe(true);
});
test('legacy redirected login is not parsed as JSON',async()=>{
  const h=requests();h.fetch.mockResolvedValue({status:200,ok:true,redirected:true,url:'https://norman.home.arpa/login.html?next=x'});await expect(h.request('/api/v1/jobs')).rejects.toMatchObject({status:401});
});
test('an HTML gateway error produces an actionable message without exposing markup',async()=>{
  const h=requests();h.fetch.mockResolvedValue({status:502,ok:false,text:async()=>'<html>gateway failure</html>'});await expect(h.request('/api/v1/jobs')).rejects.toThrow('temporarily unavailable');expect(h.state.connection.failed).toBe(true);
});

test('background refresh preserves reading position while work continues',()=>{
  const state={view:'agent',selectedConversationId:'a',selectedJobId:'',authRequired:false};
  const feed=document.createElement('div');Object.defineProperties(feed,{scrollHeight:{value:1000},clientHeight:{value:300}});feed.scrollTop=100;
  const content=jest.fn(()=>{feed.scrollTop=1000;});
  const render=new Function('state','nodes','renderFeedContent',section('  function renderFeed()','  function renderFeedContent()')+';return renderFeed;')(state,{feed},content);
  render();feed.scrollTop=100;render();expect(feed.scrollTop).toBe(100);
});
test('selected response text survives a background refresh',()=>{
  const state={view:'agent',selectedConversationId:'a',selectedJobId:'',authRequired:false,feedContext:'false:agent:a:'};
  document.body.innerHTML='<div id="feed">Copy this response</div>';
  const feed=document.getElementById('feed'),range=document.createRange();range.selectNodeContents(feed);window.getSelection().removeAllRanges();window.getSelection().addRange(range);
  const content=jest.fn();const render=new Function('state','nodes','renderFeedContent',section('  function renderFeed()','  function renderFeedContent()')+';return renderFeed;')(state,{feed},content);
  render();expect(content).not.toHaveBeenCalled();expect(window.getSelection().toString()).toBe('Copy this response');window.getSelection().removeAllRanges();
});

function composerKeyboard(disabled=false) {
  const nodes={send:{disabled},composer:{requestSubmit:jest.fn()}};
  const handler=new Function('nodes',section('  function handleComposerKeydown(', '  function bindEvents(')+';return handleComposerKeydown;')(nodes);
  return {nodes,handler};
}
test.each([{isComposing:true},{keyCode:229},{shiftKey:true},{defaultPrevented:true}])('Enter preserves composition and existing keyboard actions: %j', extra=>{
  const h=composerKeyboard(),event={key:'Enter',preventDefault:jest.fn(),...extra};h.handler(event);
  expect(event.preventDefault).not.toHaveBeenCalled();expect(h.nodes.composer.requestSubmit).not.toHaveBeenCalled();
});
test('Enter keeps editing when Send is unavailable',()=>{
  const h=composerKeyboard(true),event={key:'Enter',preventDefault:jest.fn()};h.handler(event);
  expect(event.preventDefault).not.toHaveBeenCalled();expect(h.nodes.composer.requestSubmit).not.toHaveBeenCalled();
});
test('Enter submits once when Send is available',()=>{
  const h=composerKeyboard(),event={key:'Enter',preventDefault:jest.fn()};h.handler(event);
  expect(event.preventDefault).toHaveBeenCalledTimes(1);expect(h.nodes.composer.requestSubmit).toHaveBeenCalledTimes(1);
});

function readingPositionHarness() {
 const state={view:'agent',selectedConversationId:'a',selectedJobId:'',authRequired:false};
 const feed=document.createElement('div');Object.defineProperties(feed,{scrollHeight:{value:2000,writable:true},clientHeight:{value:400}});
 const identity=new Function('slugify',section('  function conversationIdentity(', '  function mergeConversations(')+';return conversationIdentity;')(x=>x);
 const render=new Function('state','nodes','renderFeedContent','conversationIdentity',section('  function renderFeed()','  function renderFeedContent()')+';return renderFeed;')(state,{feed},()=>{feed.scrollTop=0;},identity);
 return {state,feed,render};
}
test('switching chats restores where the reader left off',()=>{
 const h=readingPositionHarness();h.render();h.feed.scrollTop=320;h.state.selectedConversationId='b';h.render();expect(h.feed.scrollTop).toBe(2000);
 h.feed.scrollTop=700;h.state.selectedConversationId='a';h.render();expect(h.feed.scrollTop).toBe(320);h.state.selectedConversationId='b';h.render();expect(h.feed.scrollTop).toBe(700);
});
test('returning to a chat that was at the end follows its newest content',()=>{
 const h=readingPositionHarness();h.render();h.feed.scrollTop=1600;h.state.selectedConversationId='b';h.render();h.feed.scrollHeight=3000;h.state.selectedConversationId='a';h.render();expect(h.feed.scrollTop).toBe(3000);
});
test('reading position memory is bounded and cleared on session expiry',()=>{
 const h=readingPositionHarness();for(let i=0;i<70;i++){h.state.selectedConversationId=String(i);h.render();}expect(h.state.feedPositions.size).toBeLessThanOrEqual(50);h.state.messageContentCache=new Map([['reply','cached html']]);h.state.messageContentCacheChars=16;h.state.authRequired=true;h.render();expect(h.state.feedPositions.size).toBe(0);expect(h.state.messageContentCache.size).toBe(0);expect(h.state.messageContentCacheChars).toBe(0);
});


test('syncing a direct chat ID keeps its reading position and separates workspaces',()=>{
 const h=readingPositionHarness();const chat={kind:'direct',conversation_id:'a',principal_slug:'personal',direct_agent_slug:'norman'};h.state.conversations=[chat];h.render();h.feed.scrollTop=320;
 chat.conversation_id='remote-a';h.state.selectedConversationId='remote-a';h.render();expect(h.feed.scrollTop).toBe(320);
 h.state.conversations.push({...chat,conversation_id:'work-a',principal_slug:'work'});h.state.selectedConversationId='work-a';h.render();expect(h.feed.scrollTop).toBe(2000);h.feed.scrollTop=900;
 h.state.selectedConversationId='remote-a';h.render();expect(h.feed.scrollTop).toBe(320);
});


test('touch Return inserts a newline while explicit Ctrl+Enter still sends', () => {
  const previous = window.matchMedia;
  window.matchMedia = jest.fn(() => ({ matches: true }));
  try {
    const h = composerKeyboard(), event = { key: 'Enter', preventDefault: jest.fn() };
    h.handler(event);
    expect(event.preventDefault).not.toHaveBeenCalled();
    expect(h.nodes.composer.requestSubmit).not.toHaveBeenCalled();
    h.handler({ ...event, ctrlKey: true });
    expect(h.nodes.composer.requestSubmit).toHaveBeenCalledTimes(1);
  } finally { window.matchMedia = previous; }
});

test('long drafts scroll when mobile CSS caps the composer below its desktop height', () => {
  const input = document.createElement('textarea');
  input.style.maxHeight = '100px';
  document.body.append(input);
  Object.defineProperty(input, 'scrollHeight', { value: 130 });
  input.scrollTop = 12;
  const resize = new Function('nodes', 'state', section('  function resizeComposer(', '  // Keep unresolved IDs') + ';return resizeComposer;')({ message: input }, {});
  resize({ immediate: true });
  expect(input.style.height).toBe('100px');
  expect(input.style.overflowY).toBe('auto');
  expect(input.scrollTop).toBe(12);
});
