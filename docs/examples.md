# Examples

This page walks through a small end‑to‑end example and shows how to interact with the REST API.

## Slack Bot Quick Start

1. Run Norman once to generate `config.yaml` and edit the Slack section:

```yaml
slack_token: "xoxb-your-slack-token"
slack_channel_id: "C01234567"
```

2. Set your `openai_api_key` in `config.yaml` and optionally regenerate the secrets:

```bash
chmod +x generate_key.sh
./generate_key.sh
```

3. Start Norman:

```bash
python main.py
```

4. Visit `http://localhost:8000` and log in with the admin credentials from `config.yaml`.
5. Create a chatbot in the Web UI and select the Slack connector. Messages sent to the configured channel will be processed by the bot.

## API Examples

Norman exposes a REST API under `/api/v1`. Below are some quick examples using `curl`.

Create a bot:

```bash
curl -X POST http://localhost:8000/api/v1/bots/ \
  -H "Content-Type: application/json" \
  -d '{"name": "demo", "description": "example bot", "gpt_model": "gpt-4"}'
```

List existing bots:

```bash
curl http://localhost:8000/api/v1/bots/
```

Delete a bot:

```bash
curl -X DELETE http://localhost:8000/api/v1/bots/1
```

Authentication headers may be required depending on your configuration.
