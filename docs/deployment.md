# Deployment

This document outlines the steps to deploy Norman on a server or cloud provider. The guide covers installation, configuration, and basic maintenance tasks.

## Table of Contents

- [Prerequisites](#prerequisites)
- [Installation](#installation)
- [Configuration](#configuration)
- [Running the Application](#running-the-application)
- [Updating Norman](#updating-norman)
- [Troubleshooting](#troubleshooting)

## Prerequisites

Before deploying Norman, ensure that your server meets the following requirements:

- Python 3.8 or higher
- SQLite (or another supported database system)
- A compatible operating system, such as Ubuntu, Debian, or CentOS

## Installation

1. Clone the Norman repository:

   ```
   git clone https://github.com/KristopherKubicki/norman.git
   ```

2. Change to the Norman directory:

   ```
   cd norman
   ```

3. Create a virtual environment:

   ```
   python3 -m venv env
   ```

4. Activate the virtual environment:

   ```
   source env/bin/activate
   ```

5. Install the required packages:

   ```
   pip install -r requirements.txt
   ```

## Configuration

1. Copy the `config.yaml.dist` file to `config.yaml`:

   ```
   cp config.yaml.dist config.yaml
   ```

2. Open `config.yaml` in a text editor and configure the required settings, such as the database connection string and API keys.

3. Save and close the `config.yaml` file.

## Running the Application

1. Start the Norman application:

   ```
   uvicorn app.main:app --host 0.0.0.0 --port 8000
   ```

2. Access the Norman Web UI in your browser by navigating to `http://your_server_ip:8000`.

3. Log in with the default admin account and start configuring your chatbots, channels, and filters.

## Updating Norman

To update your Norman installation, perform the following steps:

1. Stop the running Norman application.

2. Activate the virtual environment:

   ```
   source env/bin/activate
   ```

3. Pull the latest changes from the repository:

   ```
   git pull
   ```

4. Update the installed packages:

   ```
   pip install -r requirements.txt
   ```

5. Restart the Norman application.

## Troubleshooting

If you encounter issues during deployment or operation, consult the following resources:

- Norman's [GitHub Issues](https://github.com/KristopherKubicki/norman/issues) for known problems and solutions.
- The [FastAPI documentation](https://fastapi.tiangolo.com/) for general information on the web framework.
- The [Python logging documentation](https://docs.python.org/3/library/logging.html) for guidance on configuring and troubleshooting logging.

Feel free to modify and expand this document to include any additional information or steps specific to your project or deployment preferences.
