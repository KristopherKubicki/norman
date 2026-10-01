const fs = require('fs');

for (const file of ['scripts/norman_codex_web.py', 'scripts/agent_console_template/agent_console_web.py']) {
  const source = fs.readFileSync(file, 'utf8').replaceAll('{{', '{').replaceAll('}}', '}');
  const start = source.indexOf('    function sendingPromptPhase(');
  const code = source.slice(start, source.indexOf('    function acceptedRouteReceipt(', start));
  const setup = () => {
    const receipt = {state:'sending', submissionId:'same-id', submittedAt:Date.now()};
    const state = {promptSubmitInFlight:true};
    const notify = jest.fn();
    const functions = new Function('loadPromptSubmission', 'state', 'setOperatorReceipt', 'ACTION_REQUEST_TIMEOUT_MS', code + ';return {sendingPromptPhase,scheduleSubmissionFeedback,routePreparationReceipt};')(() => receipt, state, notify, 30000);
    return {receipt,state,notify,...functions};
  };
  beforeEach(() => jest.useFakeTimers());
  afterEach(() => jest.useRealTimers());
  test(`${file}: slow confirmation has honest, reassuring feedback`, () => {
    const f = setup();
    expect(f.sendingPromptPhase(f.receipt).body).toContain('Waiting for the server');
    f.scheduleSubmissionFeedback('same-id');
    jest.advanceTimersByTime(9999);
    expect(f.notify).not.toHaveBeenCalled();
    jest.advanceTimersByTime(1);
    expect(f.notify).toHaveBeenCalledWith(expect.stringContaining('you don’t need to send it again'), 'info', expect.any(Object));
    expect(f.routePreparationReceipt('codex','model','tier')).not.toMatch(/worker|running|Preparing route/);
  });
  test.each(['accepted', 'different', 'finished', 'cancelled'])(`${file}: delayed feedback does not overwrite %s state`, mode => {
    const f = setup();
    const timer = f.scheduleSubmissionFeedback('same-id');
    if(mode === 'accepted') f.receipt.state='accepted';
    if(mode === 'different') f.receipt.submissionId='new-id';
    if(mode === 'finished') f.state.promptSubmitInFlight=false;
    if(mode === 'cancelled') window.clearTimeout(timer);
    jest.advanceTimersByTime(10000);
    expect(f.notify).not.toHaveBeenCalled();
  });
  test(`${file}: invalid and future timestamps do not claim a long delay`, () => {
    const f=setup();
    for(const submittedAt of [0, 'invalid', Date.now()+60000]) {
      expect(f.sendingPromptPhase({submittedAt}).body).toContain('Waiting for the server');
    }
  });
}
