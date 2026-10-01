const fs=require('fs');const marked=require('../app/static/js/marked.min.js');
const source=fs.readFileSync('app/static/js/bridge.js','utf8');
const code=source.slice(source.indexOf('  function safeLinkHref('),source.indexOf('  function slugify('));
const escapeHtml=s=>String(s).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;');
function harness(){
 const state={agents:[]},parser=jest.fn(marked.marked);window.marked={marked:parser,Renderer:marked.Renderer};
 const render=new Function('state','escapeHtml','slugify','entityCartoucheHtml',code+';return renderMessageContent;')(state,escapeHtml,x=>String(x).toLowerCase(),name=>`<span>${escapeHtml(name)}</span>`);
 return {state,parser,render};
}
test('unchanged Markdown parses once and retains safe HTML/link rendering',()=>{
 const h=harness(),text='**Hello** <script>alert(1)</script> [bad](javascript:alert(1))';const first=h.render(text);expect(h.render(text)).toBe(first);expect(h.parser).toHaveBeenCalledTimes(1);expect(first).toContain('<strong>Hello</strong>');expect(first).not.toContain('<script>');expect(first).not.toContain('href="javascript:');
});
test('changed replies and changed mention names render fresh content',()=>{
 const h=harness();h.state.agents=[{slug:'norman',display_name:'Norman'}];expect(h.render('Hello @norman')).toContain('Norman');h.state.agents[0].display_name='Updated Norman';expect(h.render('Hello @norman')).toContain('Updated Norman');expect(h.render('New reply')).toContain('New reply');expect(h.parser).toHaveBeenCalledTimes(3);
});
test('cache remains bounded by count and retained character budget',()=>{
 const h=harness();for(let i=0;i<100;i++)h.render(`${i} ${'words '.repeat(1500)}`);expect(h.state.messageContentCache.size).toBeLessThanOrEqual(80);expect(h.state.messageContentCacheChars).toBeLessThanOrEqual(524288);
 const calls=h.parser.mock.calls.length;h.render('x'.repeat(70000));h.render('x'.repeat(70000));expect(h.parser).toHaveBeenCalledTimes(calls+2);
});
test('changing the parser invalidates cached rendering',()=>{
 const h=harness();h.render('text');const replacement=jest.fn(()=>'<p>New renderer</p>');window.marked.marked=replacement;expect(h.render('text')).toBe('<p>New renderer</p>');expect(replacement).toHaveBeenCalledTimes(1);
});

test('typing preserves unchanged Send icon and live status text nodes; busy state still updates',()=>{
 document.body.innerHTML='<form><textarea>Draft</textarea><button><span></span></button><div><small></small></div></form>';
 const nodes={message:document.querySelector('textarea'),send:document.querySelector('button'),composer:document.querySelector('form'),composeMeta:document.querySelector('div'),composeHint:document.querySelector('small')};
 const state={prompt:{phase:'idle'},worker:{}};
 const code=source.slice(source.indexOf('  function updateComposerState('),source.indexOf('  function setPromptPhase('));
 const update=new Function('nodes','state','pendingDelivery','promptBusy','selectedConversation','composerGuidance','iconHtml',code+';return updateComposerState;')(nodes,state,()=>null,()=>state.prompt.phase==='running',()=>({kind:'direct'}),()=>({tone:'ready',text:'Ready for Norman'}),name=>`<svg data-name="${name}"></svg>`);
 update();const icon=nodes.send.querySelector('svg'),text=nodes.composeHint.firstChild;
 for(let i=0;i<100;i++){nodes.message.value+='x';update();}
 expect(nodes.send.querySelector('svg')).toBe(icon);expect(nodes.composeHint.firstChild).toBe(text);
 state.prompt.phase='running';update();expect(nodes.send.querySelector('svg').dataset.name).toBe('loader');expect(nodes.send.disabled).toBe(true);
});
