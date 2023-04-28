# Norman

Norman is an open-source chatbot that leverages OpenAI's GPT models to assist and automate communication on various chat platforms like Slack and IRC. The project is built with FastAPI, SQLite, and SQLAlchemy, and is designed to be easily extensible with additional connectors.

## Part 1: Overview

### Features

- Supports multiple chat platforms (e.g., Slack, IRC) through connectors
- Allows multiple chatbots with different GPT models (e.g., gpt-3.5-turbo, gpt-4)
- Configurable channel filters and actions for automation
- Minimal Web UI for configuration and management
- SQLite database for lightweight deployment
- Authentication and authorization support
- Extendable with custom connectors

### Project Structure

- `app`: The main application directory
  - `api`: FastAPI routers and API endpoints
  - `core`: Core modules like configuration, logging, and exception handling
  - `crud`: CRUD operations for database models
  - `db`: Database models and utilities
  - `schemas`: Pydantic schemas for API validation
- `connectors`: Channel connectors (e.g., IRC, Slack)
- `tests`: Unit tests and integration tests
- `alembic`: Alembic migration scripts and configuration

## Part 2: Getting Started

### Prerequisites

- Python 3.8 or higher
- pip
- virtualenv (optional)

### Installation

1. Clone the repository:
```
git clone https://github.com/KristopherKubicki/norman.git
cd norman
```

2. Set up a virtual environment (optional):
```
python -m venv env
source env/bin/activate
```

3. Install the required packages:
```
pip install -r requirements.txt
```

4. Create a `config.yaml` based on the provided `config.yaml.dist`:
```
cp config.yaml.dist config.yaml
```

5. Edit `config.yaml` to configure the application, connectors, and API keys.

6. Run the application:
```
uvicorn app.main:app --reload
````

7. Open the API documentation in your browser: [http://localhost:8000/docs](http://localhost:8000/docs)

For more information, refer to the [documentation](docs/) and the [contributing guidelines](CONTRIBUTING.md).


Usage
This section can provide a brief overview of how to interact with Norman, including:

How to create and configure chatbots using the Web UI
How to set up channel filters and actions
Examples of common use-cases and automations
Deployment
Provide instructions on how to deploy Norman in different environments, such as:

Deploying with Docker
Deploying on a cloud provider (e.g., AWS, GCP, Azure)
Deploying with a reverse proxy (e.g., Nginx)
Extending Norman
Describe how users can extend Norman by:

Adding custom connectors for other chat platforms
Implementing custom actions or integrations
Contributing
Invite users to contribute to the project by:

Reporting bugs and requesting features via GitHub issues
Submitting pull requests with bug fixes or new features
Helping with documentation, tests, or translations
Community
Provide information about the project's community, such as:

Links to forums, mailing lists, or chat rooms
Social media accounts or hashtags
Upcoming events or meetups
Remember to update the relevant files in the repository to provide more detailed information on the topics mentioned above. The README.md file should serve as an entry point to help users quickly understand and use the project.

## License

This project is licensed under the MIT License. See the [LICENSE.md](LICENSE.md) file for details.

