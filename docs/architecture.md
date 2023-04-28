# Norman Architecture

This document provides an overview of Norman's architecture, its key components, and the relationships between them. A high-level understanding of the architecture will help developers work with the project more effectively.

## Table of Contents

- [High-Level Architecture](#high-level-architecture)
- [Key Components](#key-components)
- [Data Flow](#data-flow)
- [Extending Norman](#extending-norman)

## High-Level Architecture

Here is a text-based representation of Norman's high-level architecture:

```
+---------------------+     +--------------------+     +-------------------+
| Chat Platform       | <-> | Connector          | <-> | FastAPI App       |
| (Slack, IRC, etc.)  |     | (Slack, IRC, etc.) |     | (app/main.py)     |
+---------------------+     +--------------------+     +-------------------+
                                          |                  |
                                          v                  v
                                +-----------------+  +---------------------+
                                | Channel Filter  |  | Action              |
                                | (app/models)    |  | (app/models,        |
                                +-----------------+  | app/actions)        |
                                                     +---------------------+
```

## Key Components

- **Chat Platforms**: External chat services that Norman interacts with, such as Slack and IRC.

- **Connectors**: Modules that handle communication between the chat platforms and Norman. Each connector is responsible for a specific chat platform.

- **FastAPI App**: The core application that powers Norman. It is responsible for handling API requests, managing the database, and executing actions based on the filters.

- **Channel Filters**: Database models that define the rules for triggering actions in response to messages from chat platforms.

- **Actions**: Modules that define the actions to be performed when a channel filter is triggered. Actions can include generating replies, fetching data, or performing other tasks.

## Data Flow

1. A message is received from a chat platform.
2. The connector for the chat platform forwards the message to the FastAPI app.
3. The FastAPI app checks the message against the channel filters.
4. If a channel filter is triggered, the corresponding action is executed.
5. The action may involve generating a reply, which is then sent back through the connector to the chat platform.

## Extending Norman

Norman can be extended and customized in various ways, such as adding new connectors, creating custom actions, or modifying the core functionality. For more information, refer to the [Extending Norman](extending.md) documentation.

You can create a visual diagram based on the text representation above using tools like [draw.io](https://app.diagrams.net/), [Lucidchart](https://www.lucidchart.com/), or [PlantUML](https://plantuml.com/).
