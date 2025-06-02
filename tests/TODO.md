# TODO for Tests

This document outlines the remaining tasks to complete and improve the test suite for the Norman project.

## General

- [x] Improve test coverage for all CRUD operations in `app/crud`.
- [x] Add tests for exception handling and edge cases.

## Connectors

- [x] Write tests for the `irc_connector` in `tests/connectors/test_irc.py`.
- [x] Write tests for the `slack_connector` in `tests/connectors/test_slack.py`.
- [x] Write tests for the `teams_connector` in `tests/connectors/test_teams.py`.
- [x] Write tests for the `discord_connector` in `tests/connectors/test_discord.py`.
- [x] Write tests for the `google_chat_connector` in `tests/connectors/test_google_chat.py`.
- [x] Write tests for the `telegram_connector` in `tests/connectors/test_telegram.py`.

## Routers

- [x] Write tests for the `filters` router in `tests/routers/test_filters.py`.
- [x] Write tests for the `actions` router in `tests/routers/test_actions.py`.
- [x] Write tests for the `connectors` router in `tests/routers/test_connectors.py`.

## Utils and Core

 - [x] Write tests for utility functions in `app/core/utils.py`.
- [x] Write tests for the logging system in `app/core/logging.py`.
- [x] Write tests for the configuration system in `app/core/config.py`.

## Integration and End-to-End Tests

- [x] Write integration tests for the entire application.
- [x] Write end-to-end tests to simulate user interactions and verify the system's functionality.

