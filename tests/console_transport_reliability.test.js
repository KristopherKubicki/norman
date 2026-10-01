const fs=require('fs');
for(const file of ['scripts/norman_codex_web.py','scripts/agent_console_template/agent_console_web.py']) {
 const source=fs.readFileSync(file,'utf8').replaceAll('{{','{').replaceAll('}}','}');
 const code=source.slice(source.indexOf('    async function fetchWithDeadline('),source.indexOf('    async function loadFullLastResponse('));
 function harness(){
  const fetch=jest.fn(),auth=jest.fn();
  class BufferedResponse {
   constructor(body,options){this.body=body;Object.assign(this,options);this.ok=this.status>=200&&this.status<300;}
   async json(){return JSON.parse(Buffer.from(this.body).toString());}
  }
  const api=new Function('fetch','Response','ACTION_REQUEST_TIMEOUT_MS','STATUS_REQUEST_TIMEOUT_MS','clientPath','TOKEN','triggerAuthRefresh',code+';return {fetchWithDeadline,fetchStatus};')(fetch,BufferedResponse,2000,2000,x=>x,'test',auth);
  const response=(data={pending:false},status=200)=>({status,statusText:'OK',headers:{},url:'/api/status',redirected:false,arrayBuffer:async()=>Buffer.from(JSON.stringify(data))});
  return {fetch,auth,response,...api};
 }
 beforeEach(()=>jest.useFakeTimers());afterEach(()=>{jest.clearAllTimers();jest.useRealTimers();});
 test(`${file}: deadline includes a stalled body after headers arrive`,async()=>{
  const h=harness();h.fetch.mockImplementation(async(_url,{signal})=>({...h.response(),arrayBuffer:()=>new Promise((_,reject)=>signal.addEventListener('abort',()=>reject(Error('aborted'))))}));
  const outcome=h.fetchWithDeadline('/api/status',{},1000).catch(e=>e);
  await jest.advanceTimersByTimeAsync(1001);expect((await outcome).message).toContain('timed out');expect(jest.getTimerCount()).toBe(0);
 });
 test(`${file}: concurrent status readers share one request and a later check is fresh`,async()=>{
  const h=harness();let finish;h.fetch.mockImplementationOnce(()=>new Promise(r=>{finish=r}));
  const first=h.fetchStatus(),second=h.fetchStatus();expect(first).toBe(second);expect(h.fetch).toHaveBeenCalledTimes(1);
  finish(h.response());expect(await first).toEqual({pending:false});await second;
  h.fetch.mockResolvedValue(h.response({pending:true}));expect(await h.fetchStatus()).toEqual({pending:true});expect(h.fetch).toHaveBeenCalledTimes(2);
 });
 test(`${file}: a failed status attempt releases the slot for recovery`,async()=>{
  const h=harness();h.fetch.mockRejectedValueOnce(Error('offline'));await expect(h.fetchStatus()).rejects.toThrow('offline');
  h.fetch.mockResolvedValue(h.response());expect(await h.fetchStatus()).toEqual({pending:false});
 });
 test(`${file}: caller cancellation aborts response reading and cleans its timer`,async()=>{
  const h=harness(),caller=new AbortController();h.fetch.mockImplementation(async(_u,{signal})=>({...h.response(),arrayBuffer:()=>new Promise((_,reject)=>signal.addEventListener('abort',()=>reject(Error('caller cancelled'))))}));
  const result=h.fetchWithDeadline('/api/status',{signal:caller.signal}).catch(e=>e);await jest.advanceTimersByTimeAsync(1);caller.abort();expect((await result).message).toBe('caller cancelled');expect(jest.getTimerCount()).toBe(0);
 });
 test(`${file}: preserves auth rejection handling without retrying the request`,async()=>{
  const h=harness();h.fetch.mockResolvedValue(h.response({},401));await expect(h.fetchStatus()).rejects.toThrow('authentication required');expect(h.auth).toHaveBeenCalledTimes(1);expect(h.fetch).toHaveBeenCalledTimes(1);
 });
}
