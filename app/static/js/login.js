/* Keep native form submission so browser password managers see the real login. */
(() => {
  const form = document.getElementById('login-form');
  if (!form) return;
  const password = document.getElementById('current-password');
  const reveal = document.getElementById('show-password');
  const submit = form.querySelector('[type="submit"]');
  const error = document.getElementById('login-error');
  let pending = false;
  const reset = () => {
    pending = false;
    submit.disabled = false;
    submit.textContent = 'Log in to Norman';
    form.removeAttribute('aria-busy');
    password.type = 'password';
    reveal.textContent = 'Show password';
    reveal.setAttribute('aria-pressed', 'false');
  };
  reveal.hidden = false;
  reveal.addEventListener('click', () => {
    const showing = password.type === 'password';
    password.type = showing ? 'text' : 'password';
    reveal.textContent = showing ? 'Hide password' : 'Show password';
    reveal.setAttribute('aria-pressed', String(showing));
  });
  form.addEventListener('submit', event => {
    if (pending || navigator.onLine === false) {
      event.preventDefault();
      if (!pending) {
        error.textContent = 'You are offline. Reconnect and try again; your entries are still here.';
        error.hidden = false;
      }
      return;
    }
    pending = true;
    submit.disabled = true;
    submit.textContent = 'Signing in…';
    form.setAttribute('aria-busy', 'true');
  });
  window.addEventListener('pageshow', reset);
})();
