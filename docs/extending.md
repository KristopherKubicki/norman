Here's a draft for the `docs/extending.md` file. You can modify and expand it based on your project requirements and customization preferences.

# Extending Norman

This document provides an overview of how to extend and customize Norman. It covers creating new connectors, adding custom actions, and modifying the core functionality.

## Table of Contents

- [Creating New Connectors](#creating-new-connectors)
- [Adding Custom Actions](#adding-custom-actions)
- [Modifying Core Functionality](#modifying-core-functionality)
- [Contributing to Norman](#contributing-to-norman)

## Creating New Connectors

Norman supports various chat platforms through connectors. To create a new connector, follow these steps:

1. Create a new Python file in the `app/connectors` directory with a descriptive name, e.g., `custom_connector.py`.

2. Inherit from the `BaseConnector` class and implement the required methods, such as `connect`, `disconnect`, and `send_message`.

3. Update the `app/connectors/__init__.py` file to import your new connector class.

4. Add your new connector to the `app/connectors/connectors.py` file by creating an instance of your connector class.

5. Update the configuration files to include any necessary settings for your connector.

6. Test your new connector and ensure it works correctly with Norman's core functionality.

## Adding Custom Actions

Norman performs various actions based on the filters and rules defined by the user. To add a custom action, follow these steps:

1. Create a new Python file in the `app/actions` directory with a descriptive name, e.g., `custom_action.py`.

2. Define your custom action class and inherit from the `BaseAction` class.

3. Implement the required methods, such as `execute`.

4. Update the `app/actions/__init__.py` file to import your new action class.

5. Modify the Norman core functionality to use your custom action when required.

6. Test your new action to ensure it works correctly with Norman's existing actions and filters.

## Modifying Core Functionality

Norman's core functionality can be modified and extended to suit your specific needs. Before making changes, familiarize yourself with the codebase and understand the key components, such as:

- The FastAPI application (`app/main.py`)
- The database models (`app/models`)
- The API routes (`app/api`)
- The connectors (`app/connectors`)
- The actions (`app/actions`)

When making changes to the core functionality, ensure that your modifications are compatible with the existing features and that they do not introduce new issues or vulnerabilities.

## Contributing to Norman

Contributions to the Norman project are welcome. Before submitting a pull request, please read and follow the [CONTRIBUTING.md](../CONTRIBUTING.md) guidelines.

Feel free to modify and expand this document to include any additional information or steps specific to your project or customization preferences.
