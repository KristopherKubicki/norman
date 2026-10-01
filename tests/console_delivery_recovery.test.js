const fs=require('fs');
for(const file of ['scripts/norman_codex_web.py','scripts/agent_console_template/agent_console_web.py']) {
 const source=fs.readFileSync(file,'utf8').replaceAll('{{','{').replaceAll('}}','}');
 const extract=(a,b)=>{const start=source.indexOf(a);const end=source.indexOf(b,start+1);return source.slice(start,end<0?source.indexOf('\n    function ',start+1):end);};
 test(`${file}: absence from a status snapshot cannot discard an uncertain submission ID`,()=>{
  const receipt={value:'repair HAL',state:'reconciling',submissionId:'same-id',submittedAt:Date.now()-60000};
  const clear=jest.fn(),restore=jest.fn();
  const bindings={state:{snapshot:{pending:false}},loadPromptSubmission:()=>receipt,snapshotCompletedPromptSubmission:()=>false,
   snapshotIncludesSubmissionId:()=>false,snapshotIncludesPromptSubmission:()=>false,loadPromptDraft:()=>'',promptReceiptMatches:()=>false,
   clearPromptDraft:()=>{},persistPromptSubmission:()=>{},clearPromptSubmission:clear,restoreRejectedPrompt:restore,setOperatorReceipt:()=>{},PROMPT_SUBMISSION_RECONCILE_GRACE_MS:1000};
  const reconcile=new Function(...Object.keys(bindings),extract('    function reconcilePromptSubmission(','    function provisionalPromptSubmission(')+';return reconcilePromptSubmission;')(...Object.values(bindings));
  reconcile();expect(clear).not.toHaveBeenCalled();expect(restore).toHaveBeenCalledWith('repair HAL');
 });
 test.each(['sending','reconciling'])(`${file}: %s draft survives reload`,state=>{
  const el={promptInput:{value:''}},clear=jest.fn();
  const bindings={el,state:{snapshot:{}},loadPromptDraft:()=> 'repair HAL',loadPromptSubmission:()=>({state,value:'repair HAL'}),promptReceiptMatches:()=>true,clearPromptDraft:clear,
   autoresize:()=>{},updateComposerToolbar:()=>{},renderOperatorFocus:()=>{},renderSuggestions:()=>{}};
  const restore=new Function(...Object.keys(bindings),extract('    function restorePromptDraft(','    function clearPromptDraft(')+';return restorePromptDraft;')(...Object.values(bindings));
  expect(restore()).toBe(true);expect(el.promptInput.value).toBe('repair HAL');expect(clear).not.toHaveBeenCalled();
 });
}

for (const file of ['scripts/norman_codex_web.py','scripts/agent_console_template/agent_console_web.py']) {
 const source=fs.readFileSync(file,'utf8').replaceAll('{{','{').replaceAll('}}','}');
 const start=source.indexOf('        function snapshotCompletedPromptSubmission(');
 const code=source.slice(start,source.indexOf('    function reconcilePromptSubmission(',start));
 test(`${file}: old identical history cannot clear a new receipt`,()=>{
  const receipt={value:'Check HAL',submissionId:'new-id',submittedAt:Date.now()};
  const complete=new Function('loadPromptSubmission','promptReceiptMatches','isPlaceholderAssistantResponse','historyEntries',code+';return snapshotCompletedPromptSubmission;')(()=>receipt,(a,b)=>a===b,x=>x==='[waiting for reply]',s=>s.history||[]);
  expect(complete({history:[{prompt:'Check HAL',response:'old',started_at:(Date.now()-60000)/1000}]},'Check HAL')).toBe(false);
  expect(complete({history:[{prompt:'Check HAL',response:'new',started_at:Date.now()/1000}]},'Check HAL')).toBe(true);
  expect(complete({history:[{prompt:'Check HAL',response:'other task',submission_id:'other-id',started_at:Date.now()/1000}]},'Check HAL')).toBe(false);
  expect(complete({history:[{prompt:'Check HAL',response:'[waiting for reply]',started_at:Date.now()/1000}]},'Check HAL')).toBe(false);
 });
}
