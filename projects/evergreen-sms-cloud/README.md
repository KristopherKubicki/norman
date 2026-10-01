# Evergreen SMS Cloud

This is the deployable AWS half of the Evergreen SMS reply path:

`Twilio -> inbound Lambda -> inbound SQS -> local bridge -> BBS callback ->
completion SQS -> outbound Lambda -> Twilio`.

The inbound handler returns `<Response/>` only. It never emits a visible
"routed" acknowledgement. A final reply is sent only after the BBS posts the
matching `conversation_id` and `turn_id` completion.

## Conversation Rules

- A conversation is keyed by Twilio account, destination number, and sender
  number.
- `/new` starts a new conversation for that pair.
- A 24-hour idle interval starts a new conversation.
- The first SMS in a burst waits eight seconds. Later texts in that window are
  appended to the same turn. The bridge reads the turn from DynamoDB before it
  calls the BBS, so it gets the merged body.
- Each turn has one immutable `turn_id`; all retries are idempotent on that ID.

## Deploy Deliberately

Do not deploy until the local bridge and the isolated SMS BBS callback service
are configured. The deployment script reconciles the existing named AWS
resources without sending an SMS:

```bash
cd projects/evergreen-sms-cloud
./deploy_existing.sh
./deploy_existing.sh --apply --profile personal-bedrock --region us-east-2
```

It keeps the Twilio auth token in the existing
`TWILIO_AUTH_TOKEN_SECRET_ARN` Secrets Manager secret. The script packages the
three handlers, creates the completion path, enables partial SQS batch
failures, and raises all pipeline queue visibility timeouts to 180 seconds.

The configured Twilio inbound webhook must exactly match
`TWILIO_WEBHOOK_URL` because Twilio signs the full URL. Configure the bridge
with the printed queue URLs, the DynamoDB table name, and the shared encrypted
`sms-callback-token` systemd credential. The normal BBS remains separate.
