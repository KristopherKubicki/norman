# Repo Guidelines
- Run `make format` for Black.
- Verify `make lint` and `make test` succeed.
- Run `npm test` if anything in `frontend/` changes.
- Mention all tests in the PR summary.

## Shared Host Resource Safety

- Scope filesystem searches to the checkout or a known subtree. Do not run
  unbounded scans such as `find /`, `find /home`, or `rg ... /home`.
- Use the narrowest practical path plus a timeout for expensive discovery,
  verification, conversion, or browser automation tasks.
- Stop or clean up temporary workers, browser tabs, and disposable artifacts
  when a task finishes; do not leave idle resource consumers behind.
- When host pressure is reported, inspect the local pressure guard report before
  starting background or high-I/O work.

## Personal Bot Secret Handling

- This section is for `personal/home` and `shared-infra` Norman bots only. Do not treat it as guidance for `work` or `OpenBrand` bots.
- Prefer Norman Keys as the secret access path. Use a brokered lookup such as `NORMAN_SECRET_CMD` or `NORMAN_KEYS_URL` plus short-lived approval/lease behavior where available.
- Use logical secret names like `networking/firewall`, `networking/netgear`, `networking/dot10`, `networking/camera`, and `networking/synology`.
- Do not add new direct reads of repo-local plaintext secret dotfiles such as `.firewall`, `.netgear`, `.dot10`, `.camera`, `.synology`, `.modem`, `.sudo_pass`, or `.prox_root`.
- If Norman Keys is unavailable during migration, the temporary local fallback is the machine-local encrypted `cred` vault, not new plaintext files.
