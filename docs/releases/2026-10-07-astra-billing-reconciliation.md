# Astra And Billing Reconciliation

The CT241 runtime has an explicit `norman-code-astra` route and personal-account
credential selection that were absent from staging. This candidate ports those
changes onto staging `5b31aeb8d51dbabe5baab7d47b7a00f120bf56ae` without replacing
its newer native Responses implementation or changing the default authority role.

- Advertise the explicit Astra alias and retain its governed text tool adapter.
- Require the compiled route policy to authorize `openai.gpt-6-astra`.
- Use the deployed `us-west-2` endpoint for that alias.
- Pass reasoning effort through the existing Responses options, defaulting to medium.
- Scope token-region selection to each broker subprocess, avoiding shared environment changes.
- Select personal credentials only from authenticated gateway context for the existing personal routes.
- Keep the configured work credential alias for other routes and reject arbitrary broker aliases.

The personal broker alias resolves `norman/bedrock-personal`; it does not reuse
`norman/bedrock-fallback`. No credential contents or production environment settings
are included in this change. The operator must provision aliases through the existing
approved secret path before enabling a fresh installation.

Tests cover alias routing and region selection, reasoning defaults and explicit overrides,
authorization gating, broker region isolation, separate credential selection, and rejection
of an untrusted top-level billing hint. Existing native Responses and malformed-envelope
regressions remain part of the full gateway suite.

This source reconciliation does not constitute a production release or proof that the
entire old live checkout can be replaced with staging. Other live-only source groups
and runtime dependencies still require release review.
