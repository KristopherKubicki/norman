# Evergreen SMS Bridge

Local home-side bridge for Evergreen inbound SMS.

This package is the house-side companion to `projects/evergreen-sms-cloud`:

- AWS SQS holds normalized inbound SMS from Twilio
- this bridge long-polls that queue outbound-only
- it resolves the durable cloud turn, submits it to Norman's dedicated SMS API,
  and hosts an authenticated loopback completion callback
- it only deletes inbound SQS after the exact turn is durably accepted by the
  BBS, and only marks a reply sent after completion SQS accepts it

The default is `sms` mode. It is the only mode that supports correlated
multi-text conversations and final BBS replies. The previous modes remain
available only as migration fallbacks.

## Correlated SMS Mode

Set these values in `.env`:

- `DELIVERY_MODE=sms`
- `INBOUND_QUEUE_URL`
- `COMPLETION_QUEUE_URL`
- `SMS_CONVERSATIONS_TABLE`
- `BBS_URL`
- `SMS_CALLBACK_TOKEN_FILE` or systemd `CREDENTIALS_DIRECTORY`

The bridge binds the callback receiver to `127.0.0.1` by default. It posts
each exact `conversation_id` and `turn_id` to `/api/sms/turns`, then waits for
the BBS to call `/callbacks/sms` with the same correlation. The final callback
is recorded before a 2xx response is returned, and a durable outbox forwards
it to the cloud completion queue.

Production callback credentials are loaded from systemd's encrypted
`sms-callback-token` credential. They are not sent to the BBS or stored in a
durable bridge or turn record.

The matching system units are
`scripts/systemd/norman-sms-bbs.service` and
`scripts/systemd/evergreen-sms-bridge.service`. The SMS BBS listens only on
`127.0.0.1:8798`, owns a distinct state directory, and does not share the
normal BBS on port 8788. Its `norman-sms-codex` launcher loads the configured
NVM default when Codex is not on systemd's default `PATH`.

## Legacy Modes

- `spool`
  - write one JSON envelope per message under `SPOOL_DIR`
- `webhook`
  - POST the JSON envelope to `WEBHOOK_URL`
- `collector`
  - POST the normalized SMS text to Norman's `/api/ask` collector endpoint
- `tmux`
  - send the normalized SMS into a local tmux pane, typically Subprime
- `both`
  - backward-compatible alias for `spool,webhook`

You can also compose delivery targets directly with `DELIVERY_MODE=spool,tmux`,
`DELIVERY_MODE=spool,collector`, `DELIVERY_MODE=webhook,tmux`, or
`DELIVERY_MODE=all`.

## Files

- `sms_bridge.py` runs the correlated production bridge
- `.env.example` shows the expected runtime settings
- `install.sh` is limited to legacy one-way migration modes
- `../../scripts/systemd/norman-sms-bbs.service` runs the isolated BBS
- `../../scripts/systemd/evergreen-sms-bridge.service` runs the correlated bridge

## Install Correlated SMS

Do not use `install.sh` for `DELIVERY_MODE=sms`; it deliberately refuses that
configuration because the old user service does not load the shared encrypted
credential or start the isolated BBS.

1. Create the bridge virtual environment:
```bash
python3 -m venv projects/evergreen-sms-bridge/.venv
projects/evergreen-sms-bridge/.venv/bin/pip install --upgrade pip boto3
```

2. Put the non-secret cloud settings from `.env.example` in
   `/etc/norman/evergreen-sms-bridge.env`. It needs `AWS_PROFILE`,
   `AWS_REGION`, `INBOUND_QUEUE_URL`, `COMPLETION_QUEUE_URL`, and
   `SMS_CONVERSATIONS_TABLE`.
3. Provision the same `sms-callback-token` encrypted systemd credential for
   both services using the approved Norman Keys or secret-broker workflow.
   Do not add it to `.env` or another plaintext repo-local file.
4. Install and enable the two root systemd units:
```bash
sudo install -D -m 0644 scripts/systemd/norman-sms-bbs.service \
  /etc/systemd/system/norman-sms-bbs.service
sudo install -D -m 0644 scripts/systemd/evergreen-sms-bridge.service \
  /etc/systemd/system/evergreen-sms-bridge.service
sudo systemctl daemon-reload
sudo systemctl enable --now norman-sms-bbs.service evergreen-sms-bridge.service
```

Validate the loopback BBS and then follow both service logs:

```bash
curl --fail http://127.0.0.1:8798/health
sudo systemctl status norman-sms-bbs.service evergreen-sms-bridge.service --no-pager
sudo journalctl -fu norman-sms-bbs.service -u evergreen-sms-bridge.service
```

This local installation does not deploy AWS resources or send an SMS. Deploy
the cloud half separately and only after this local path is verified.

## Legacy Installation

The older spool, webhook, collector, and tmux modes remain available for
one-way migration work only. Set a non-`sms` `DELIVERY_MODE` and run:

```bash
cd projects/evergreen-sms-bridge
bash ./install.sh --legacy
```

`collector` mode uses the old shared console status polling and must not be
used for conversational SMS replies. If an emergency manual injection is
needed during migration, use:

- `DELIVERY_MODE=spool,tmux`
- `TMUX_TARGET=norman-bot-prime:0.0`
- `TMUX_WORKING_DIR=/home/operator/code/norman`
- `TMUX_SEND_ENTER=true`
- `TMUX_ENTER_COUNT=2`

That keeps the spool copy and injects the inbound SMS into the live Subprime
tmux pane, but it is not the preferred Norman-native ingress.

## Message Shape

The delayed SQS job contains `conversation_id`, `turn_id`, and `sequence`.
The bridge loads the authoritative turn body from DynamoDB before it reaches
the BBS, allowing a short burst of texts to become one turn.

Legacy dispatch envelopes contain:

- `bridge_received_at`
- `bridge_hostname`
- `delivery_mode`
- `source_queue_url`
- `message`

`message` is the normalized payload emitted by the cloud Lambda, including:

- `message_sid`
- `from`
- `to`
- `body`
- `received_at`
- `raw`

## Notes

- The callback receiver is loopback/private only and requires a bearer token.
- Failed inbound SQS jobs are left for retry; failed completion sends remain in
  the durable local outbox.
- Do not configure Twilio or deploy the cloud stack until this bridge and the
  BBS endpoint have been deliberately validated together.
