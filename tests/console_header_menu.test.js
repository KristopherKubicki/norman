const fs = require('fs');
for (const file of ['scripts/norman_codex_web.py','scripts/agent_console_template/agent_console_web.py']) {
 const source=fs.readFileSync(file,'utf8').replaceAll('{{','{').replaceAll('}}','}');
 const extract=(from,to)=>source.slice(source.indexOf(from),source.indexOf(to,source.indexOf(from)));
 function setup(){
  document.body.className='settings-open';
  document.body.innerHTML='<button id="opener">Menu</button><div id="menu"><button disabled>Unavailable</button><a href="#" id="first">Sessions</a><button id="second">Settings</button></div><textarea id="draft">Keep this draft</textarea>';
  const el={topbarMenu:document.getElementById('menu'),topbarMenuButton:document.getElementById('opener')};
  const names=['setOperatorActionPaletteOpen','setSwitcherOpen','setSettingsOpen','setNoticesOpen','setSystemOpen','setStatusActionOpen','syncTopbarMenuPosition'];
  const mocks=Object.fromEntries(names.map(n=>[n,jest.fn()]));
  const toggle=new Function('el',...names,extract('    function setTopbarMenuOpen(', '    function setStatusActionOpen(')+';return setTopbarMenuOpen;')(el,...Object.values(mocks));
  return {el,mocks,toggle};
 }
 test(`${file}: opening closes other panels and focuses an enabled control`,()=>{
  const h=setup();h.el.topbarMenuButton.focus();h.toggle(true);
  for(const [name,mock] of Object.entries(h.mocks)) if(name!=='syncTopbarMenuPosition')expect(mock).toHaveBeenCalledWith(false);
  expect(document.activeElement.id).toBe('first');expect(h.el.topbarMenu.inert).toBe(false);
  expect(h.el.topbarMenuButton.getAttribute('aria-expanded')).toBe('true');
  document.getElementById('second').focus();h.toggle(true);expect(document.activeElement.id).toBe('second');
 });
 test(`${file}: closing restores opener focus without touching the draft`,()=>{
  const h=setup();h.toggle(true);h.toggle(false);
  expect(document.activeElement).toBe(h.el.topbarMenuButton);expect(h.el.topbarMenu.inert).toBe(true);
  expect(h.el.topbarMenu.getAttribute('aria-hidden')).toBe('true');
  expect(document.getElementById('draft').value).toBe('Keep this draft');
 });
 test(`${file}: outside dismissal does not steal focus from typing`,()=>{
  const h=setup();h.toggle(true);document.getElementById('draft').focus();h.toggle(false);
  expect(document.activeElement.id).toBe('draft');
 });
 test(`${file}: Escape closes the menu without cancelling work or opening the keyboard`,()=>{
  const h=setup();h.toggle(true);
  const focus=jest.fn(),cancel=jest.fn();
  const handle=new Function('dismissTransientChrome','focusPromptInputAtEnd','fireAction',extract('    function maybeInterruptFromEscape(', '    function maybeFocusPromptFromEscape(')+';return maybeInterruptFromEscape;')(()=>{h.toggle(false);return true;},focus,cancel);
  const event={key:'Escape',preventDefault:jest.fn(),stopPropagation:jest.fn()};
  expect(handle(event)).toBe(true);expect(focus).not.toHaveBeenCalled();expect(cancel).not.toHaveBeenCalled();expect(document.activeElement).toBe(h.el.topbarMenuButton);
 });
}
