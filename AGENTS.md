# Repo Guidelines
- Run `make format` for Black.
- Verify `make lint` and `make test` succeed.
- Run `npm test` if anything in `frontend/` changes.
- Mention all tests in the PR summary.

## Personal Bot Secret Handling

- This section is for `personal/home` and `shared-infra` Norman bots only. Do not treat it as guidance for `work` or `OpenBrand` bots.
- Prefer Norman Keys as the secret access path. Use a brokered lookup such as `NORMAN_SECRET_CMD` or `NORMAN_KEYS_URL` plus short-lived approval/lease behavior where available.
- Use logical secret names like `networking/firewall`, `networking/netgear`, `networking/dot10`, `networking/camera`, and `networking/synology`.
- Do not add new direct reads of repo-local plaintext secret dotfiles such as `.firewall`, `.netgear`, `.dot10`, `.camera`, `.synology`, `.modem`, `.sudo_pass`, or `.prox_root`.
- If Norman Keys is unavailable during migration, the temporary local fallback is the machine-local encrypted `cred` vault, not new plaintext files.
