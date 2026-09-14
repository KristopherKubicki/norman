const fs = require('fs');
const source = fs.readFileSync('app/static/js/estate_applications.js', 'utf8');
const flush = () => new Promise(resolve => setTimeout(resolve, 0));

beforeEach(() => {
  document.body.innerHTML = `<div id="estate-applications"></div><input id="applications-search"><select id="applications-account"><option value=""></option></select><input type="checkbox" id="applications-attention"><input type="checkbox" id="applications-retired"><div id="applications-source"></div><div id="applications-count"></div><details id="applications-discoveries"></details>`;
});
afterEach(() => window.dispatchEvent(new Event('pagehide')));

test('groups apps, hides retired, filters accounts and escapes discovery content', async () => {
  global.fetch = jest.fn().mockResolvedValue({ok:true, json:async () => ({
    source:{fetched_at:'2026-09-14'}, discoveries:[{name:'<img src=x onerror=alert(1)>',kind:'surfaces'}],
    applications:[
      {id:'scout',name:'Scout',primary_tui:'ranger',account:'openbrand',health:'degraded',needs_attention:true,lifecycle:'managed',operator_observation:{health:'reachable'}},
      {id:'bird',name:'Pretty Bird',account:'openbrand',health:'retired',lifecycle:'retired'},
      {id:'cost',name:'CostCrawler',account:'personal',health:'unknown',lifecycle:'needs-owner'}]
  })});
  eval(source);
  await flush();
  expect(document.querySelector('[data-application="scout"]')).not.toBeNull();
  expect(document.querySelector('[data-application="bird"]')).toBeNull();
  expect(document.querySelector('#applications-discoveries img')).toBeNull();
  const retired = document.getElementById('applications-retired');
  retired.checked = true; retired.dispatchEvent(new Event('input'));
  expect(document.querySelector('[data-application="bird"]')).not.toBeNull();
  const account = document.getElementById('applications-account');
  account.value = 'personal'; account.dispatchEvent(new Event('input'));
  expect(document.querySelector('[data-application="scout"]')).toBeNull();
  expect(document.querySelector('[data-application="cost"]')).not.toBeNull();
});

test('failed fetch shows unavailable without claiming health', async () => {
  global.fetch = jest.fn().mockRejectedValue(new Error('offline'));
  eval(source);
  await flush();
  expect(document.getElementById('applications-source').textContent).toContain('Unable to refresh');
});
