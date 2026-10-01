const fs=require('fs');const source=fs.readFileSync('app/static/js/bridge.js','utf8');
const section=(a,b)=>source.slice(source.indexOf(a),source.indexOf(b));
function harness(){
 document.body.innerHTML='<main><button id="nav-open">Navigation</button><button id="details-open">Details</button><button id="menu-open">Menu</button><aside id="nav"><button id="cockpit-nav-close">Close</button></aside><aside id="details"><button id="cockpit-inspector-close">Close</button></aside><aside id="menu"><button>Refresh</button></aside><div id="backdrop"></div><textarea>Draft</textarea></main>';
 const root=document.querySelector('main'),state={},nodes={nav:document.getElementById('nav'),inspector:document.getElementById('details'),menu:document.getElementById('menu'),menuButton:document.getElementById('menu-open'),backdrop:document.getElementById('backdrop')};
 const api=new Function('root','state','nodes','setWorkspaceMenuOpen','renderMenuPanel',section('  function openDrawer(', '  function selectGroup(')+section('  function setMenuOpen(', '  function resizeComposer(')+';return {openDrawer,closeDrawers,setMenuOpen};')(root,state,nodes,jest.fn(),jest.fn());
 return {...api,root,state,nodes};
}
test('closing navigation returns focus to its opener without touching a draft',()=>{
 const h=harness(),opener=document.getElementById('nav-open');h.openDrawer('navigation',opener);expect(document.activeElement.id).toBe('cockpit-nav-close');h.closeDrawers();expect(document.activeElement).toBe(opener);expect(opener.getAttribute('aria-expanded')).toBe('false');expect(document.querySelector('textarea').value).toBe('Draft');
});
test('opening details closes navigation instead of stacking drawers',()=>{
 const h=harness();h.openDrawer('navigation',document.getElementById('nav-open'));h.openDrawer('details',document.getElementById('details-open'));expect(h.nodes.nav.classList.contains('is-open')).toBe(false);expect(h.nodes.inspector.classList.contains('is-open')).toBe(true);
});
test('controls menu and drawers are exclusive; closing makes menu inert and returns focus',()=>{
 const h=harness();h.openDrawer('navigation',document.getElementById('nav-open'));h.setMenuOpen(true);expect(h.nodes.nav.classList.contains('is-open')).toBe(false);expect(h.nodes.menu.contains(document.activeElement)).toBe(true);h.setMenuOpen(false);expect(h.nodes.menu.inert).toBe(true);expect(document.activeElement).toBe(h.nodes.menuButton);
});
test('closing an unrelated drawer does not steal focus from typing',()=>{
 const h=harness();h.openDrawer('navigation',document.getElementById('nav-open'));const input=document.querySelector('textarea');input.focus();h.closeDrawers();expect(document.activeElement).toBe(input);
});
function keyboard(nodes){
 const close=jest.fn(),menu=jest.fn(),workspace=jest.fn();const handler=new Function('nodes','closeDrawers','setMenuOpen','setWorkspaceMenuOpen',section('  function handleGlobalKeydown(', '  function handleComposerKeydown(')+';return handleGlobalKeydown;')(nodes,close,menu,workspace);return {handler,close,menu,workspace};
}
test('Escape in a native dialog leaves underlying panels alone',()=>{
 const h=keyboard({roomDialog:{open:true}});h.handler({key:'Escape'});expect(h.close).not.toHaveBeenCalled();expect(h.menu).not.toHaveBeenCalled();expect(h.workspace).not.toHaveBeenCalled();
});
test('Escape dismisses the workspace chooser before its navigation drawer',()=>{
 const h=keyboard({workspaceButton:{getAttribute:()=> 'true'}});h.handler({key:'Escape'});expect(h.workspace).toHaveBeenCalledWith(false);expect(h.close).not.toHaveBeenCalled();
});
