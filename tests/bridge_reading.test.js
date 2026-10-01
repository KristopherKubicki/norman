const fs=require('fs');
const source=fs.readFileSync('app/static/js/bridge.js','utf8');
const code=source.slice(source.indexOf('  function updateReadingTools('),source.indexOf('  function bindEvents('));
function harness(){
 document.body.innerHTML='<div id="feed"><article class="cockpit-message"><div class="cockpit-message__bubble">Check the router\nssh hal hostname</div><button data-copy-reply>Copy</button></article></div><div><form id="composer"><textarea>My draft</textarea></form></div>';
 const nodes={feed:document.getElementById('feed'),composer:document.getElementById('composer')},state={view:'agent'};
 Object.defineProperties(nodes.feed,{scrollHeight:{value:1000},clientHeight:{value:300}});
 const api=new Function('nodes','state',code+';return {setupReadingTools,updateReadingTools,copyReply};')(nodes,state);api.setupReadingTools();
 return {...api,nodes,state,button:document.querySelector('[data-copy-reply]')};
}
beforeEach(()=>jest.useFakeTimers());afterEach(()=>{jest.clearAllTimers();jest.useRealTimers();window.getSelection().removeAllRanges();});
test('latest control follows reading position and leaves a draft alone',()=>{
 const h=harness();h.nodes.feed.scrollTop=100;h.updateReadingTools();expect(h.nodes.latestReply.hidden).toBe(false);
 h.nodes.latestReply.click();expect(h.nodes.feed.scrollTop).toBe(1000);expect(h.nodes.latestReply.hidden).toBe(true);expect(document.querySelector('textarea').value).toBe('My draft');
});
test('latest control stays out of attention and signed-out views',()=>{
 const h=harness();h.state.view='global-attention';h.updateReadingTools();expect(h.nodes.latestReply.hidden).toBe(true);
 h.state.view='agent';h.state.authRequired=true;h.updateReadingTools();expect(h.nodes.latestReply.hidden).toBe(true);
});
test('copy confirms success without moving the editor caret',async()=>{
 const h=harness(),writeText=jest.fn().mockResolvedValue();Object.defineProperty(navigator,'clipboard',{configurable:true,value:{writeText}});
 const input=document.querySelector('textarea');input.focus();input.setSelectionRange(2,2);await h.copyReply(h.button);
 expect(writeText).toHaveBeenCalledWith('Check the router\nssh hal hostname');expect(h.nodes.readingFeedback.textContent).toBe('Reply copied.');expect(input.selectionStart).toBe(2);expect(document.activeElement).toBe(input);
});
test('clipboard rejection selects only the reply and explains manual copying',async()=>{
 const h=harness();Object.defineProperty(navigator,'clipboard',{configurable:true,value:{writeText:jest.fn().mockRejectedValue(Error('denied'))}});
 await h.copyReply(h.button);expect(window.getSelection().toString()).toBe('Check the router\nssh hal hostname');expect(h.nodes.readingFeedback.textContent).toContain('Reply selected');expect(h.button.disabled).toBe(false);
});
test('repeat clicks share the pending clipboard operation',async()=>{
 const h=harness();let resolve;const writeText=jest.fn(()=>new Promise(r=>{resolve=r}));Object.defineProperty(navigator,'clipboard',{configurable:true,value:{writeText}});
 const first=h.copyReply(h.button);await h.copyReply(h.button);expect(writeText).toHaveBeenCalledTimes(1);resolve();await first;expect(h.button.disabled).toBe(false);
});

test.each(['data-agent','data-job-id','data-conversation-id'])('reply metadata %s cannot trigger navigation; explicit controls can',attribute=>{
 const section=source.slice(source.indexOf('  function navigationControl('),source.indexOf('  function updateReadingTools('));
 const control=new Function(section+';return navigationControl;')();
 document.body.innerHTML=`<article ${attribute}="norman"><span id="text">A reply</span><button id="copy">Copy</button></article><button ${attribute}="norman" id="nav"><span id="label">Open</span></button>`;
 expect(control(document.getElementById('text'),attribute)).toBeNull();expect(control(document.getElementById('copy'),attribute)).toBeNull();expect(control(document.getElementById('label'),attribute)).toBe(document.getElementById('nav'));
});
