# Extending Norman

This document provides an overview of how to extend and customize Norman. It covers creating new connectors, adding
custom actions, and modifying the core functionality.

## Table of Contents

- [Creating New Connectors](#creating-new-connectors)
- [Adding Custom Actions](#adding-custom-actions)
- [Modifying Core Functionality](#modifying-core-functionality)
- [Contributing to Norman](#contributing-to-norman)

## Creating New Connectors

Norman supports various chat platforms through connectors. To create a new connector, follow these steps:

1. Create a new Python file in the `app/connectors` directory with a descriptive name, e.g., `custom_connector.py`.

2. Inherit from the `BaseConnector` class and implement the required methods.  At a minimum you should provide
   `send_message` as well as optional `connect` and `disconnect` hooks.  You can also override `listen_and_process` and
   `process_incoming` to handle incoming data.
   The base class includes a default `is_connected` method that simply returns
   `True`.  Override this if your connector can perform a meaningful health
   check.

3. Place the new module inside the `app/connectors` package with a filename
   ending in `_connector.py`. Norman will automatically discover it.

4. Update the configuration files to include any necessary settings for your connector.

5. You can send messages by calling `queue_message`; `run()` starts a background dispatcher that forwards queued
   messages using your `send_message` implementation.

6. Test your new connector and ensure it works correctly with Norman's core functionality.

## Adding Custom Actions

Norman performs various actions based on the filters and rules defined by the user. To add a custom action, follow these
steps:

1. Create a new Python file in the `app/actions` directory with a descriptive name, e.g., `custom_action.py`.

2. Define your custom action class and inherit from the `BaseAction` class.

3. Implement the required methods, such as `execute`.

4. Update the `app/actions/__init__.py` file to import your new action class.

5. Modify the Norman core functionality to use your custom action when required.

6. Test your new action to ensure it works correctly with Norman's existing actions and filters.

## Modifying Core Functionality

Norman's core functionality can be modified and extended to suit your specific needs. Before making changes, familiarize
yourself with the codebase and understand the key components, such as:

- The FastAPI application (`app/main.py`)
- The database models (`app/models`)
- The API routes (`app/api`)
- The connectors (`app/connectors`)
- The actions (`app/actions`)

When making changes to the core functionality, ensure that your modifications are compatible with the existing features
and that they do not introduce new issues or vulnerabilities.

## Registering Pre/Post Hooks

Norman exposes simple hook points that allow you to run code before a message is
sent to the LLM and after a reply is generated. This lets you implement custom
checks, logging, or response rewriting without touching the core code.

Hooks are defined in `app.core.hooks`:

```python
from app.core import hooks

def my_pre_hook(message: str, context: dict) -> tuple[str, dict]:
    # Modify or reject the message here
    return message, context

def my_post_hook(reply: str, context: dict) -> tuple[str, dict]:
    # Inspect or alter the assistant reply
    return reply, context

hooks.register_pre_hook(my_pre_hook)
hooks.register_post_hook(my_post_hook)
```

The hooks receive the message text (or reply) and a context dictionary. Each
hook should return the possibly modified text and context. All registered hooks
are executed in the order they were added.

## Contributing to Norman

Contributions to the Norman project are welcome. Before submitting a pull request, please read and follow the
[CONTRIBUTING.md](../CONTRIBUTING.md) guidelines.

Feel free to modify and expand this document to include any additional information or steps specific to your project or
customization preferences.
