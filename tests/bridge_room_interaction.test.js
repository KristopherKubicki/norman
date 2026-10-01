const fs=require('fs');
const source=fs.readFileSync('app/static/js/bridge.js','utf8');
const code=source.slice(source.indexOf('  function openRoomDialog('),source.indexOf('  function setAttentionView('));
function harness(){
 document.body.innerHTML='<dialog open><form><input id="name" value="Repair room"><input id="search"><input name="member" type="checkbox" value="norman" checked><button>Create room</button><p hidden></p></form></dialog>';
 const form=document.querySelector('form'),dialog=document.querySelector('dialog');dialog.close=()=>dialog.removeAttribute('open');dialog.showModal=()=>dialog.setAttribute('open','');
 const nodes={roomForm:form,roomDialog:dialog,roomName:document.getElementById('name'),roomSearch:document.getElementById('search'),roomCreate:document.querySelector('button'),roomError:document.querySelector('p')};
 const state={conversations:[],roomDialogInitialized:true},post=jest.fn(),select=jest.fn(),announce=jest.fn();
 const bindings={state,nodes,postJson:post,selectConversation:select,announceReadingAction:announce,renderQuickChats:jest.fn(),renderWorkstreams:jest.fn(),currentGroup:()=>({slug:'personal'}),API:'/api',persistenceUnavailable:()=>false,updateRoomSelectionState:()=>{nodes.roomCreate.disabled=!!state.roomCreating},renderRoomMemberPicker:jest.fn(),filterRoomMembers:jest.fn()};
 const api=new Function(...Object.keys(bindings),code+';return {openRoomDialog,createRoom};')(...Object.values(bindings));
 return {...api,nodes,state,post,select,announce,submit:()=>api.createRoom({preventDefault(){}})};
}
test('pending room creation suppresses repeated submissions and restores controls',async()=>{
 const h=harness();let resolve;h.post.mockReturnValue(new Promise(r=>{resolve=r}));const first=h.submit();await h.submit();
 expect(h.post).toHaveBeenCalledTimes(1);expect(h.nodes.roomCreate.textContent).toBe('Creating…');expect(h.nodes.roomName.disabled).toBe(true);
 resolve({conversation_id:'created'});await first;expect(h.nodes.roomName.disabled).toBe(false);expect(h.state.roomCreating).toBe(false);expect(h.select).toHaveBeenCalledWith('created');
});
test('rejection retains entries and restores a usable retry',async()=>{
 const h=harness();h.post.mockRejectedValue(Error('Name unavailable'));await h.submit();
 expect(h.nodes.roomName.value).toBe('Repair room');expect(h.nodes.roomError.textContent).toBe('Name unavailable');expect(h.nodes.roomCreate.disabled).toBe(false);expect(h.nodes.roomForm.hasAttribute('aria-busy')).toBe(false);
});
test('closing a pending dialog prevents a late response from changing the conversation',async()=>{
 const h=harness();let resolve;h.post.mockReturnValue(new Promise(r=>{resolve=r}));const pending=h.submit();h.nodes.roomDialog.close();resolve({conversation_id:'created'});await pending;
 expect(h.select).not.toHaveBeenCalled();expect(h.state.conversations[0].conversation_id).toBe('created');expect(h.announce).toHaveBeenCalledWith('Room created. Find it in your conversations.');
});
test('reopening a canceled room dialog retains its name and selected members',()=>{
 const h=harness();h.nodes.roomDialog.close();h.openRoomDialog();expect(h.nodes.roomName.value).toBe('Repair room');expect(h.nodes.roomForm.querySelector('[name=member]').checked).toBe(true);
});
