# Evergreen SMS Bridge

Local home-side bridge for Evergreen inbound SMS.

This package is the house-side companion to `projects/evergreen-sms-cloud`:

- AWS SQS holds normalized inbound SMS from Twilio
- this bridge long-polls that queue outbound-only
- it can write messages to a local spool, forward them to a local webhook, or
  deliver them to Norman's local collector, or inject them into a local tmux target
- it only deletes an SQS message after local delivery succeeds

The safe default is `spool` mode so inbound SMS can land on Norman/Subprime even
before a real Switchboard webhook exists.

## Current Modes

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

- `run-consumer.py` polls SQS and dispatches locally
- `.env.example` shows the expected runtime settings
- `install.sh` creates a local venv, installs `boto3`, and installs a user-level service
- `systemd/evergreen-sms-bridge.service.in` is the unit template

## Quick Start

1. Copy `.env.example` to `.env`.
2. Fill in at least:
   - `INBOUND_QUEUE_URL`
   - `AWS_PROFILE`
   - `DELIVERY_MODE`
3. Start with safe spool mode:

```bash
cd projects/evergreen-sms-bridge
cp .env.example .env
./install.sh
```

4. Watch the bridge:

```bash
systemctl --user status evergreen-sms-bridge.service --no-pager
journalctl --user -u evergreen-sms-bridge.service -f
```

## Recommended First Pass

Use:

- `DELIVERY_MODE=spool`
- `KEEP_SPOOL_COPY=true`
- `SPOOL_DIR=~/.local/state/cloudagent/evergreen-sms/inbox`

That gives you a durable local inbox without assuming Switchboard already exists.

When Norman/Subprime should receive the SMS directly, move to:

- `DELIVERY_MODE=spool,collector`
- `COLLECTOR_URL=http://127.0.0.1:8796`
- `COLLECTOR_TOKEN=<subprime-web-token>`

That keeps the spool copy and hands the inbound SMS to Norman's native collector
API, which is the same path Norman uses for tmux-backed manual sends.

If the collector is unavailable and you need a last-resort local pane injection,
move to:

- `DELIVERY_MODE=spool,tmux`
- `TMUX_TARGET=norman-bot-prime:0.0`
- `TMUX_WORKING_DIR=/home/operator/code/norman`
- `TMUX_SEND_ENTER=true`
- `TMUX_ENTER_COUNT=2`

That keeps the spool copy and injects the inbound SMS into the live Subprime
tmux pane, but it is not the preferred Norman-native ingress.

When Switchboard has an HTTP intake, move to:

- `DELIVERY_MODE=both`
- `WEBHOOK_URL=http://127.0.0.1:8796/hooks/evergreen-sms`

or whatever the actual local intake becomes.

## Message Shape

Each local dispatch envelope contains:

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

- This bridge intentionally does not expose any local port publicly.
- It leaves failed SQS messages in the queue by not deleting them.
- It is safe to run before Twilio is fully switched over.
- `collector` mode is the preferred Norman/Subprime handoff because it uses the
  local authenticated collector instead of depending on pane state.
- `TMUX_TARGET` delivery uses local `tmux send-keys`; it does not depend on
  Norman's LLM routing stack.
