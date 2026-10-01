const fs = require('fs');
const script = fs.readFileSync('app/static/js/login.js', 'utf8');
beforeEach(() => {
  document.body.innerHTML = '<form id="login-form"><input id="username" name="username"><input id="current-password" name="password" type="password"><button id="show-password" hidden type="button">Show password</button><p id="login-error" hidden></p><button type="submit">Log in to Norman</button></form>';
  Object.defineProperty(navigator, 'onLine', {value:true, configurable:true});
  window.eval(script);
});
const submit = () => { const e=new Event('submit',{cancelable:true});document.querySelector('form').dispatchEvent(e);return e; };
test('autofilled values survive reveal and native submission', () => {
  document.getElementById('username').value='saved@example.com';
  const password=document.getElementById('current-password');password.value='saved password';
  document.getElementById('show-password').click();expect(password.type).toBe('text');
  expect(submit().defaultPrevented).toBe(false);
  expect(new FormData(document.querySelector('form')).get('password')).toBe('saved password');
  expect(submit().defaultPrevented).toBe(true);
});
test('back navigation resets a submitting form without clearing saved values', () => {
  const password=document.getElementById('current-password');password.value='saved';
  submit();window.dispatchEvent(new Event('pageshow'));
  expect(document.querySelector('[type="submit"]').disabled).toBe(false);
  expect(password.value).toBe('saved');expect(password.type).toBe('password');
  expect(submit().defaultPrevented).toBe(false);
});
test('offline submit keeps entries and explains how to retry', () => {
  Object.defineProperty(navigator,'onLine',{value:false,configurable:true});
  document.getElementById('username').value='saved@example.com';
  expect(submit().defaultPrevented).toBe(true);
  expect(document.getElementById('login-error').hidden).toBe(false);
  expect(document.getElementById('username').value).toBe('saved@example.com');
  expect(document.querySelector('[type="submit"]').disabled).toBe(false);
});
