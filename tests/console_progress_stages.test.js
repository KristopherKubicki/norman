const fs = require('fs');
for (const file of ['scripts/norman_codex_web.py', 'scripts/agent_console_template/agent_console_web.py']) {
  const source = fs.readFileSync(file, 'utf8').replaceAll('{{', '{').replaceAll('}}', '}');
  const start = source.indexOf('    function liveProgressStageCopy(');
  const code = source.slice(start, source.indexOf('    function liveStatusExpanded(', start));
  const copy = new Function('liveTurnForSnapshot', code + ';return liveProgressStageCopy;')(s => s.live_turn || {});
  test.each([
    ['checking_runtime', 'Checking runtime readiness'],
    ['preparing_context', 'Preparing conversation context'],
    ['waiting_model', 'Waiting for the model’s next update'],
  ])(`${file}: shows observed phase %s`, (phase, expected) => {
    expect(copy({pending:true,last_started_at:20,live_turn:{started_at:20,phase}})).toBe(expected);
  });
  test(`${file}: an earlier turn cannot supply the current progress stage`, () => {
    expect(copy({pending:true,last_started_at:20,live_turn:{started_at:10,phase:'waiting_model'}})).toBe('Request accepted; waiting for a progress update');
  });
  test(`${file}: idle and unknown stages do not invent model activity`, () => {
    expect(copy({pending:false,live_turn:{phase:'waiting_model'}})).toBe('');
    expect(copy({pending:true,live_turn:{phase:'unknown'}})).toBe('Request accepted; waiting for a progress update');
  });
}
