const fs = require('fs');
for (const file of ['scripts/norman_codex_web.py', 'scripts/agent_console_template/agent_console_web.py']) {
  const source = fs.readFileSync(file, 'utf8').replaceAll('{{', '{').replaceAll('}}', '}');
  const extract = (a, b) => source.slice(source.indexOf(a), source.indexOf(b, source.indexOf(a)));
  function harness() {
    const values = new Map();
    const storage = {getItem: jest.fn(k => values.get(k) ?? null),setItem: jest.fn((k,v) => values.set(k,v)),removeItem: jest.fn(k => values.delete(k))};
    const code = extract('    const storageMemory =', '    function uiVersionStorageKey(')
      + extract('    function loadPromptSubmission(', '    function createPromptSubmissionId(');
    const api = new Function('window','PROMPT_SUBMISSION_STORAGE_KEY','PROMPT_SUBMISSION_MAX_AGE_MS','normalizePromptReceiptValue','state','UI_VERSION',code+';return {safeStorageGet,safeStorageSet,safeStorageRemove,loadPromptSubmission,persistPromptSubmission};')(
      {localStorage:storage},'receipt',12*60*60*1000,x=>String(x).trim(),{},'test');
    return {storage,values,...api};
  }
  test(`${file}: unresolved identified receipts survive an overnight interruption`, () => {
    const h=harness();h.persistPromptSubmission('Check HAL',{submissionId:'original-id',state:'reconciling',submittedAt:Date.now()-7*86400000});
    expect(h.loadPromptSubmission()).toMatchObject({submissionId:'original-id',value:'Check HAL'});
  });
  test(`${file}: quota errors retain the latest receipt rather than returning stale disk data`, () => {
    const h=harness();h.persistPromptSubmission('old',{submissionId:'old-id'});
    h.storage.setItem.mockImplementation(()=>{throw Error('Quota exceeded')});
    h.persistPromptSubmission('new',{submissionId:'new-id'});
    expect(h.loadPromptSubmission()).toMatchObject({submissionId:'new-id',value:'new'});
  });
  test(`${file}: blocked reads and writes still protect retries in the open tab`, () => {
    const h=harness();for(const fn of Object.values(h.storage))fn.mockImplementation(()=>{throw Error('Storage denied')});
    h.persistPromptSubmission('Check HAL',{submissionId:'same-id'});expect(h.loadPromptSubmission().submissionId).toBe('same-id');
    h.safeStorageRemove('receipt');expect(h.loadPromptSubmission()).toBeNull();
  });
  test(`${file}: a failed delete cannot resurrect a cleared receipt`, () => {
    const h=harness();h.persistPromptSubmission('old',{submissionId:'old-id'});h.storage.removeItem.mockImplementation(()=>{throw Error('denied')});
    h.safeStorageRemove('receipt');expect(h.loadPromptSubmission()).toBeNull();
  });
  test(`${file}: temporary storage failures recover persistence automatically`, () => {
    const h=harness();h.storage.setItem.mockImplementationOnce(()=>{throw Error('temporarily denied')});
    h.persistPromptSubmission('Check HAL',{submissionId:'retained-id'});
    expect(h.values.has('receipt')).toBe(false);
    expect(h.loadPromptSubmission().submissionId).toBe('retained-id');
    expect(JSON.parse(h.values.get('receipt')).submissionId).toBe('retained-id');
  });
  test(`${file}: working storage continues to see updates from other tabs`, () => {
    const h=harness();h.safeStorageSet('preference','one');h.values.set('preference','two');expect(h.safeStorageGet('preference')).toBe('two');
  });
}

test('NetOps keeps the new pending status visible despite an old identical prompt', () => {
  const source=fs.readFileSync('scripts/agent_console_template/agent_console_web.py','utf8').replaceAll('{{','{').replaceAll('}}','}');
  const start=source.indexOf('    function provisionalPromptSubmission(');
  const code=source.slice(start,source.indexOf('    function encodeSwitcherToken(',start));
  const receipt={state:'reconciling',submissionId:'new-id',value:'Check HAL'};
  const provisional=new Function('state','loadPromptSubmission','snapshotCompletedPromptSubmission','snapshotIncludesSubmissionId','snapshotIncludesPromptSubmission','AGENT_LABEL',code+';return provisionalPromptSubmission;')({snapshot:{}},()=>receipt,()=>false,()=>false,()=>true,'NetOps');
  expect(provisional()).toMatchObject({submissionId:'new-id',state:'reconciling'});
});
