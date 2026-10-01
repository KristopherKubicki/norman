const fs = require('fs');

for (const file of ['scripts/norman_codex_web.py', 'scripts/agent_console_template/agent_console_web.py']) {
  const source = fs.readFileSync(file, 'utf8').replaceAll('{{', '{').replaceAll('}}', '}').replaceAll('\\\\', '\\');
  const names = ['containsTokenReuseError', 'containsOpenAIAuthError', 'containsCodexAuthFailure', 'containsCodexCliUpgradeError', 'containsOpenAITransportError', 'containsRateLimitError', 'containsUsageLimitError', 'containsCertWorkflowError', 'containsCodexRouteMismatchError', 'looksLikeLowValueRawError', 'shouldCollapseErrorDetails', 'summarizeErrorText', 'renderErrorMarkup'];
  const code = names.map(name => {
    const start = source.indexOf(`    function ${name}(`);
    if (start < 0) throw new Error(`Missing ${name}`);
    return source.slice(start, source.indexOf('\n    function ', start + 1));
  }).join('\n');
  const escapeHtml = value => String(value).replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;');
  const api = new Function('escapeHtml', 'renderRichText', 'extractStructuredErrorOutput', 'summarizePrompt', 'WORKER_SESSION_LABEL', code + ';return {renderErrorMarkup,containsCodexAuthFailure};')(escapeHtml, escapeHtml, () => '', text => text, 'Worker');

  test.each(['invalid_refresh_token', 'refresh_token_reused', 'Could not validate your refresh token', 'Your access token could not be refreshed'])(`${file}: explains short sign-in failure %s`, error => {
    const html = api.renderErrorMarkup(error);
    expect(html).toContain('fresh sign-in');
    expect(html).toContain('<summary>Technical details</summary>');
    expect(html).toContain(`<pre>${error}</pre>`);
  });
  test.each([
    ['429 Too Many Requests', 'Provider rate limit hit'],
    ["You've hit your usage limit", 'Usage limit reached'],
    ['certificate_verify_failed', 'Certificate/TLS workflow failed'],
    ['requires a newer version of codex', 'CLI was stale'],
  ])(`${file}: short operational error has recovery guidance: %s`, (error, guidance) => {
    const html = api.renderErrorMarkup(error);
    expect(html).toContain(guidance);
    expect(html).toContain('<summary>Technical details</summary>');
  });
  test(`${file}: unrelated authorization failures are not diagnosed as provider sign-in failures`, () => {
    expect(api.containsCodexAuthFailure('Firewall returned 401 Unauthorized')).toBe(false);
    expect(api.renderErrorMarkup('Firewall returned 401 Unauthorized')).toBe('Firewall returned 401 Unauthorized');
  });
  test(`${file}: raw error details cannot inject markup`, () => {
    const html = api.renderErrorMarkup('invalid_refresh_token <img src=x onerror=alert(1)>');
    expect(html).not.toContain('<img');
    expect(html).toContain('&lt;img');
  });
  test(`${file}: empty error remains a readable message`, () => {
    expect(api.renderErrorMarkup('')).toContain('Check the latest warning details.');
  });
}
