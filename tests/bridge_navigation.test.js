const fs=require('fs');
beforeEach(()=>{localStorage.clear();window.eval(fs.readFileSync('app/static/js/bridge_navigation.js','utf8'));});
const a={kind:'direct',conversation_id:'a',principal_slug:'home',direct_agent_slug:'housebot',title:'Housebot'};
const b={kind:'direct',conversation_id:'b',principal_slug:'work',direct_agent_slug:'norman',title:'Norman'};
test('pins survive reload and a locally saved chat acquiring a server ID',()=>{
 const p=BridgeNavigation.createPreferences('alice');p.toggle(a);
 const reloaded=BridgeNavigation.createPreferences('alice');expect(reloaded.pinned({...a,conversation_id:'server-id'})).toBe(true);
 expect(BridgeNavigation.createPreferences('bob').pinned(a)).toBe(false);
});
test('pinned chats stay first while unpinned chats sort by last opened',()=>{
 const p=BridgeNavigation.createPreferences('alice');p.toggle(a);p.visit(b);expect(p.list([b,a]).map(c=>c.title)).toEqual(['Housebot','Norman']);p.toggle(a);expect(p.list([a,b])[0]).toBe(b);expect(p.list([a,b],'house')).toEqual([a]);
});
test('unavailable storage does not prevent pinning and switching',()=>{
 const storage={getItem(){throw Error()},setItem(){throw Error()}};
 const p=BridgeNavigation.createPreferences('alice',storage);p.toggle(a);p.visit(a);expect(p.pinned(a)).toBe(true);
});
test.each([
 [{online:false,authenticated:true,connected:true},'Offline'],
 [{online:true,authenticated:false},'Sign in'],
 [{online:true,authenticated:true,connected:false},'Connecting'],
 [{online:true,authenticated:true,connected:true,failed:true},'Reconnecting'],
 [{online:true,authenticated:true,connected:true,failed:false},'Connected'],
])('connection status describes the observed connection', (input,label)=>{expect(BridgeNavigation.connectionLabel(input).label).toBe(label)});
test('background restoration does not navigate away from Activity',()=>{
 const source=fs.readFileSync('app/static/js/bridge.js','utf8');
 const body=source.slice(source.indexOf('  function restoreActiveConversation()'),source.indexOf('  function beginSignIn()'));
 const state={view:'activity',conversations:[a],agents:[],groups:[{id:'home',slug:'home'}]};
 const restore=new Function('state','selectedConversation','saveActiveConversation','loadActiveConversation','slugify',body+';return restoreActiveConversation;')(state,()=>null,()=>{},()=>({directAgentSlug:'housebot',principalSlug:'home'}),x=>x||'');
 expect(restore()).toBeNull();expect(state.view).toBe('activity');
});
