# Usage

This document provides an overview of how to interact with Norman, including creating and configuring chatbots, setting up channel filters and actions, and examples of common use-cases and automations.

## Table of Contents

- [Creating a Chatbot](#creating-a-chatbot)
- [Configuring a Chatbot](#configuring-a-chatbot)
- [Channel Filters and Actions](#channel-filters-and-actions)
- [Examples](#examples)

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
