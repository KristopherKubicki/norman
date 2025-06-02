document.addEventListener('DOMContentLoaded', () => {
  const form = document.getElementById('slack-creds-form');
  form.addEventListener('submit', async (evt) => {
    evt.preventDefault();
    const token = document.getElementById('slack-token').value.trim();
    const channel = document.getElementById('slack-channel').value.trim();
    const resp = await fetch('/api/credentials/slack', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ token, channel_id: channel })
    });
    const statusEl = document.getElementById('slack-cred-status');
    if (resp.ok) {
      statusEl.textContent = 'saved';
      form.reset();
    } else {
      statusEl.textContent = 'error';
    }
  });
});
