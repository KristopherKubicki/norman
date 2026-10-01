const fs = require('fs');
for (const file of ['scripts/norman_codex_web.py', 'scripts/agent_console_template/agent_console_web.py']) {
  const source = fs.readFileSync(file, 'utf8').replaceAll('{{', '{').replaceAll('}}', '}').replaceAll('{STREAM_IDLE_SECONDS}', '4');
  const code = source.slice(source.indexOf('    function schedulePoll(delayMs)'), source.indexOf('    function confirmInterruptSubmit(message)'));
  function harness() {
    const streams = [];
    class Stream {
      constructor() { this.handlers = {}; this.close = jest.fn(); streams.push(this); }
      addEventListener(name, fn) { this.handlers[name] = fn; }
      emit(name, data = {}) { this.handlers[name]({data: JSON.stringify(data)}); }
    }
    const state = {snapshot: {}, transportAcknowledged: true};
    const fetchStatus = jest.fn().mockResolvedValue({pending: false});
    const render = jest.fn(), transport = jest.fn();
    const api = new Function('state', 'window', 'document', 'EventSource', 'clientPath', 'TOKEN', 'setTransportState', 'currentOperatorReceipt', 'setOperatorReceipt', 'render', 'fetchStatus', 'el', 'VISIBLE_PENDING_STATUS_POLL_MS', 'VISIBLE_IDLE_STATUS_POLL_MS', code + '; return {connectStream,disconnectStream,syncLiveTransport};')(state, {setTimeout,EventSource:Stream}, {hidden:false}, Stream, x=>x, 'test', transport, ()=>null, jest.fn(), render, fetchStatus, {runState:{}}, 3000, 10000);
    return {...api,state,streams,fetchStatus,render,transport};
  }
  beforeEach(()=>jest.useFakeTimers());
  afterEach(()=>{jest.clearAllTimers();jest.useRealTimers();});
  test(`${file}: silent live stream falls back to status and reconnects`, async()=>{
    const h=harness();h.connectStream();h.streams[0].emit('snapshot');
    await jest.advanceTimersByTimeAsync(45001);
    expect(h.streams[0].close).toHaveBeenCalledTimes(1);expect(h.fetchStatus).toHaveBeenCalledTimes(1);
    expect(h.transport).toHaveBeenCalledWith('Reconnecting · checking status…',false);
    await jest.advanceTimersByTimeAsync(1800);expect(h.streams).toHaveLength(2);
  });
  test(`${file}: heartbeats keep a healthy idle stream connected`, async()=>{
    const h=harness();h.connectStream();h.streams[0].emit('snapshot');
    for(let i=0;i<20;i++){await jest.advanceTimersByTimeAsync(4000);h.streams[0].emit('heartbeat');}
    expect(h.streams[0].close).not.toHaveBeenCalled();expect(h.fetchStatus).not.toHaveBeenCalled();
  });
  test(`${file}: malformed snapshot immediately restores polling`, async()=>{
    const h=harness();h.connectStream();h.streams[0].emit('snapshot');h.streams[0].handlers.snapshot({data:'invalid'});
    await jest.advanceTimersByTimeAsync(1);expect(h.fetchStatus).toHaveBeenCalledTimes(1);expect(h.streams[0].close).toHaveBeenCalled();
  });
  test(`${file}: disconnected stream callbacks cannot replace current state`,()=>{
    const h=harness();h.connectStream();const stale=h.streams[0];h.disconnectStream();h.connectStream();
    stale.emit('snapshot');stale.emit('heartbeat');stale.onerror();
    expect(h.render).not.toHaveBeenCalled();expect(h.streams[1].close).not.toHaveBeenCalled();expect(h.state.stream).toBe(h.streams[1]);
  });
  test(`${file}: disconnect cancels watchdog without reconnecting`, async()=>{
    const h=harness();h.connectStream();h.disconnectStream();await jest.advanceTimersByTimeAsync(90000);
    expect(h.fetchStatus).not.toHaveBeenCalled();expect(h.streams).toHaveLength(1);expect(jest.getTimerCount()).toBe(0);
  });
}
