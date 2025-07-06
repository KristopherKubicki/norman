# Usage

This document provides an overview of how to interact with Norman, including creating and configuring chatbots, setting up channel filters and actions, and examples of common use-cases and automations.

## Table of Contents

- [Creating a Chatbot](#creating-a-chatbot)
- [Configuring a Chatbot](#configuring-a-chatbot)
- [Channel Filters and Actions](#channel-filters-and-actions)
- [Examples](#examples)
- [First Run](#first-run)
- [Slack Quick Start](#slack-bot-quick-start)
- [API Examples](#api-examples)

## Creating a Chatbot

To create a new chatbot, follow these steps:

1. Log in to the Norman Web UI.
2. Navigate to the "Chatbots" page.
3. Click the "Create New Chatbot" button.
4. Fill in the required fields, such as the chatbot's name and the GPT model to use.
5. Click "Save" to create the chatbot.

## Configuring a Chatbot

After creating a chatbot, you can configure its settings, such as its associated channels and filters. To do this:

1. Click on the chatbot's name in the "Chatbots" page.
2. On the chatbot's settings page, you can add or remove channels, create or modify channel filters, and define actions.

## Channel Filters and Actions

Channel filters are used to trigger actions based on incoming messages. To create a channel filter:

1. Navigate to the chatbot's settings page.
2. Click on the "Channel Filters" tab.
3. Click the "Add Channel Filter" button.
4. Fill in the required fields, such as the filter name, regex pattern, and associated channel.
5. Click "Save" to create the channel filter.

To create an action:

1. Navigate to the chatbot's settings page.
2. Click on the "Actions" tab.
3. Click the "Add Action" button.
4. Fill in the required fields, such as the action name, prompt, and reply channel.
5. Click "Save" to create the action.

## Examples

Here are some example use-cases for Norman:

1. **Helpdesk Automation:** Create a channel filter that detects when users mention "helpdesk" in a customer support channel. When the filter is triggered, Norman can investigate the issue, summarize its findings, and reply in an internal helpdesk channel.
2. **Meeting Scheduling:** Create a channel filter that detects when users request a meeting. Norman can then check participants' calendars, find an available time, and send out calendar invites.
3. **Automated Code Review:** Create a channel filter that detects when users submit pull requests. Norman can then analyze the code, provide suggestions or corrections, and post a review comment on the pull request.

Remember to expand on these sections and provide more detailed information based on your project's specific features and requirements.

## First Run

When starting Norman for the first time, the application creates a
`config.yaml` file with random credentials. The admin username, email
and password are printed to the console. Record these values, edit
`config.yaml` to supply your `openai_api_key` and any connector
settings, then restart Norman. Visit `http://localhost:8000` and sign
in with the credentials shown.

## Slack Bot Quick Start

This example demonstrates how to connect Norman to Slack and create a simple bot.

1. Run Norman once to generate `config.yaml` and edit the Slack section:

```yaml
slack_token: "xoxb-your-slack-token"
slack_channel_id: "C01234567"
```

2. Set your `openai_api_key` in the same file and optionally regenerate the secrets:

```bash
chmod +x generate_key.sh
./generate_key.sh
```

3. Start Norman with `python main.py` and open `http://localhost:8000` in your browser.
4. Log in with the admin credentials from `config.yaml`, create a chatbot and select the Slack connector. Messages posted in the configured channel will be processed by the bot.
5. When a bot is generating a reply, the interface displays a *Thinking...* indicator so you know it's working.

## API Examples

You can also interact with Norman programmatically. The API is exposed under the
path configured by `api_prefix` and `api_version` in `config.yaml` (by default
`/api/v1`). The following `curl` commands illustrate common operations:

Create a bot:

```bash
curl -X POST http://localhost:8000/api/v1/bots/ \
  -H "Content-Type: application/json" \
  -d '{"name": "demo", "description": "example bot", "gpt_model": "gpt-4.1-mini"}'
```

List existing bots:

```bash
curl http://localhost:8000/api/v1/bots/
```

Delete a bot:

```bash
curl -X DELETE http://localhost:8000/api/v1/bots/1
```

List available connectors and their status:

```bash
curl http://localhost:8000/api/v1/connectors/available
```

Authentication headers may be required depending on your configuration.

### Rate Limiting

Norman applies a simple IP based rate limit to API requests. The limits can be
adjusted via `rate_limit_requests` and `rate_limit_window_seconds` in
`config.yaml`. Exceeding the limit returns a `429 Too Many Requests` response.
