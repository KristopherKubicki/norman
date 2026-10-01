const fs=require('fs');
for(const file of ['scripts/norman_codex_web.py','scripts/agent_console_template/agent_console_web.py']){
 const source=fs.readFileSync(file,'utf8').replaceAll('{{','{').replaceAll('}}','}');
 const start=source.indexOf('    function setTransportState(');const code=source.slice(start,source.indexOf('    function triggerAuthRefresh(',start));
 test(`${file}: header connection status follows observed transport and keeps failure detail`,()=>{
  document.body.innerHTML='<span id="header-connection-state" role="status"></span><span id="transport"></span>';
  const state={snapshot:null};const el={transportStateMenu:document.getElementById('transport')};
  const set=new Function('state','el',code+';return setTransportState;')(state,el);
  const header=document.getElementById('header-connection-state');
  set('Live updates connected',true);expect(header.textContent).toBe('Live');expect(header.dataset.connected).toBe('true');
  set('Sign-in required',false);expect(header.textContent).toBe('Not connected');expect(header.title).toBe('Sign-in required');
  expect(header.dataset.connected).toBe('false');expect(el.transportStateMenu.textContent).toBe('Sign-in required');
 });
}
