# Deployment

This document outlines the steps to deploy Norman on a server or cloud provider. The guide covers installation,
configuration, and basic maintenance tasks.

## Table of Contents

- [Prerequisites](#prerequisites)
- [Installation](#installation)
- [Configuration](#configuration)
- [Running the Application](#running-the-application)
- [Updating Norman](#updating-norman)
- [Troubleshooting](#troubleshooting)

## Prerequisites

Before deploying Norman, ensure that your server meets the following requirements:

- Python 3.8, 3.9, 3.10, or 3.11
- SQLite (or another supported database system)
- A compatible operating system, such as Ubuntu, Debian, or CentOS

## Installation

1. Clone the Norman repository:

   ```
   git clone https://github.com/KristopherKubicki/norman.git
   ```

2. Change to the Norman directory:

   ```
   cd norman
   ```

3. Create a virtual environment:

   ```
   python3 -m venv env
   ```

4. Activate the virtual environment:

   ```
   source env/bin/activate
   ```

5. Install the required packages:

   ```
   pip install -r requirements.txt
   ```

## Configuration

1. Run Norman once to automatically create `config.yaml` with secure defaults.
   Edit this file to configure the required settings, such as the database connection string and API keys.

### Managed Service Configuration

Production services should not generate or keep `config.yaml` in a release
checkout. Set `NORMAN_CONFIG_SECRET` to a logical Norman Keys name and provide
one approved resolver:

```text
NORMAN_CONFIG_SECRET=norman/runtime-config
NORMAN_CONFIG_SECRET_CMD=<approved broker command using {name}>
NORMAN_CONFIG_REQUESTER_ID=norman-release
NORMAN_CONFIG_TARGET_HOST=norman.lollie.org
```

`NORMAN_CONFIG_SECRET_CMD` is preferred for the temporary machine-local `cred`
vault bridge. An external Norman Keys endpoint can instead be configured with
`NORMAN_KEYS_URL` and its short-lived service token. The secret value must be
a YAML mapping containing the normal `config.yaml` overrides, including a real
`admin_setup_key`.

Norman fails closed when a configured secret cannot be read or has invalid
YAML. It does not log the returned contents, generate a replacement
`config.yaml`, or silently fall back to a repo-local config file. The optional
`NORMAN_CONFIG_PATH` migration setting must be an absolute path outside the
application working tree; do not use it to point back at a release checkout.
When the secret policy has `allowed_hosts`, set
`NORMAN_CONFIG_TARGET_HOST` to the exact approved hostname. Hostname matching
is case-insensitive and ignores a trailing dot; an unset or unapproved host is
denied.

The repository includes `scripts/systemd/norman-release@.service` for a
loopback-only canary. It is intentionally separate from `norman.service`, so a
candidate can be validated without replacing the active service:

The canary reads its resolver settings only from `/etc/norman/release.env`;
do not reuse the live service's `/etc/norman/runtime.env`. Keep
`release.env` root-owned and mode `0600`, and limit it to
`NORMAN_CONFIG_SECRET` plus the selected broker resolver and token settings.

```bash
sudo systemctl daemon-reload
sudo systemctl start norman-release@<release-sha>
curl -fsS http://127.0.0.1:18000/health
sudo systemctl stop norman-release@<release-sha>
```

The release checkout must contain `.venv-3.10` and the managed configuration
environment before starting this unit.

### Production Credential Wrapper

Use `scripts/systemd/norman-production@.service` and
`scripts/systemd/norman-production-launch` for a SHA-pinned production release.
Install the launcher at `/usr/local/libexec/norman-production-launch` with mode
`0755`, and install the unit at
`/etc/systemd/system/norman-production@.service`. The unit is deliberately
separate from the loopback canary and from the legacy `norman.service`.

The unit reads only non-secret identities from
`/etc/norman/runtime-identities.env`. Store the following logical aliases in
the approved Norman Keys resolver or the encrypted `cred` migration vault:

```text
norman/prompt-proxy-token
norman/console-runtime-service-token
norman/keys-service-token
```

The unit loads a systemd encrypted credential containing the vault passphrase
and the launcher resolves the aliases only into the child process. Do not add
the token values to an environment file, a unit drop-in, a release checkout,
or shell history. The machine-local `cred` bridge is a migration fallback;
move these aliases to a networked Norman Keys backend with short-lived leases
when that backend is available.

The legacy `norman.service` rollback path must use the same identity file.
Install `scripts/systemd/norman.service.d/10-runtime-env.conf` before removing
the legacy plaintext token file.

For each production deployment, confirm the unit resolves to the expected
release and that the front door and local model lane remain healthy:

```bash
systemctl is-active norman-production@<release-sha>
curl -fsS http://127.0.0.1:8000/health
curl -fsS https://norman.home.arpa/health
curl -fsS https://llm.home.arpa/v1/models
```

To roll back a bad production release, stop and disable the SHA-specific unit,
then re-enable and start the prior known-good unit. Keep the legacy service
disabled unless it is the intentionally selected rollback target:

```bash
sudo systemctl stop norman-production@<bad-sha>
sudo systemctl disable norman-production@<bad-sha>
sudo systemctl enable --now norman-production@<known-good-sha>
```

## Running the Application

1. Start the Norman application:

   ```
   uvicorn app.main:app --host 0.0.0.0 --port 8000 --compression gzip

   If the `brotli_asgi` package is installed and your Uvicorn version supports
   it, you can use `--compression brotli` instead for better compression.
   ```

2. Access the Norman Web UI in your browser by navigating to `http://your_server_ip:8000`.

3. Log in with the default admin account and start configuring your chatbots, channels, and filters.

## Updating Norman

To update your Norman installation, perform the following steps:

1. Stop the running Norman application.

2. Activate the virtual environment:

   ```
   source env/bin/activate
   ```

3. Pull the latest changes from the repository:

   ```
   git pull
   ```

4. Update the installed packages:

   ```
   pip install -r requirements.txt
   ```

5. Restart the Norman application.

## Troubleshooting

If you encounter issues during deployment or operation, consult the following resources:

- Norman's [GitHub Issues](https://github.com/KristopherKubicki/norman/issues) for known problems and solutions.
- The [FastAPI documentation](https://fastapi.tiangolo.com/) for general information on the web framework.
- The [Python logging documentation](https://docs.python.org/3/library/logging.html) for guidance on configuring and
  troubleshooting logging.
- Norman exposes a simple health check at `/health` that can be polled by monitoring systems.

Feel free to modify and expand this document to include any additional information or steps specific to your project or
deployment preferences.
