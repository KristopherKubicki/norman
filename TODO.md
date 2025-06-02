# TODO

## High Priority

- [x] Implement and test all connectors (IRC, Slack, etc.)
- [x] Finalize and test CRUD operations and API endpoints for all models
- [x] Set up GitHub Actions for CI/CD
- [x] Configure authentication and authorization
- [x] Create a minimal Web UI for configuration and management
- [x] Implement the core logic for handling incoming messages and triggering actions
- [x] Finalize the configuration system to use `config.yaml` and `config.yaml.dist`
 - [x] Test and optimize the SQLite database configuration
- [x] Develop a system for handling multiple channel connectors
- [x] Implement a lightweight API for external communication
- [x] Refactor the current connector model to use dynamic Connectors that read existing hardcoded models as connector_types
      - This will allow admins to add as many or as few Connectors as they want, or even duplicate connectors for more than 1 connection to a service (e.g., multiple IRC servers)

## Medium Priority

- [ ] Improve logging and exception handling
 - [x] Add more unit tests and integration tests
- [ ] Implement support for additional GPT models
- [ ] Write documentation for the project
- [x] Redesign the bots.html page to be similar to the OpenAI chat window
      - Bots should be listed on the left side of the screen
      - The main chat window should be in the middle of the screen
      - Clicking on a bot should replace the messages in the main window with the messages from that bot's Interactions
- [x] Create a bot_detail.html page for editing details about the bot session, including:
      - GPT model
      - Name
      - Description
      - Enabled status
- [x] Update the message_log.html page to fit the new design
      - Channels should be listed on the left side of the screen instead of bots
      - Clicking on a channel should replace the messages in the main window with the messages from that channel's Interactions

## Low Priority

- [ ] Explore options for direct communication with Norman for configuration
- [ ] Implement additional features and improvements based on user feedback
