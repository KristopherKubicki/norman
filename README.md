# Norman

[![CI](https://github.com/KristopherKubicki/norman/actions/workflows/ci_cd.yml/badge.svg)](https://github.com/KristopherKubicki/norman/actions/workflows/ci_cd.yml)
[![Codecov](https://codecov.io/gh/KristopherKubicki/norman/branch/main/graph/badge.svg)](https://codecov.io/gh/KristopherKubicki/norman)
[![OpenSSF Scorecard](https://api.securityscorecards.dev/projects/github.com/KristopherKubicki/norman/badge)](https://securityscorecards.dev/viewer/?uri=github.com/KristopherKubicki/norman)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE.md)
[![Python 3.8](https://img.shields.io/badge/python-3.8-blue.svg)](https://www.python.org/)

Norman is an open-source chatbot that leverages OpenAI's GPT models to assist and automate communication on various chat platforms like Slack and IRC. The project is built with FastAPI, SQLite, and SQLAlchemy, and is designed to be easily extensible with additional connectors.

![krstopher_abstract_readme_header_graphic_for_a_chatbot_software_a578ebda-8121-4195-ba94-7c5128049da3 (1)](https://user-images.githubusercontent.com/478212/235266088-7f69c1bd-e3db-4b80-b8ff-64c5785f55b7.png)

## Table of Contents

- [Features](#features)
- [Requirements](#requirements)
- [Installation](#installation)
- [Usage](#usage)
- [Testing](#testing)
- [Contributing](#contributing)
- [License](#license)
- [Docker Deployment](docs/docker.md)

### Features

- Supports multiple chat platforms (e.g., Slack, IRC) through connectors
- Allows multiple chatbots with different GPT models (e.g., gpt-4.1-mini, o3)
- Configurable channel filters and actions for automation
- Minimal Web UI for configuration and management
- SQLite database for lightweight deployment
- Authentication and authorization support
- Extendable with custom connectors

*Bots default to the `gpt-4.1-mini` model for speed. Use `o3` when you need deeper reasoning and can tolerate more latency.*

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

## Getting Started

### Prerequisites

- Python 3.8 or higher
- pip
- SQLite
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

Norman automatically enables [WAL](https://www.sqlite.org/wal.html) mode when using SQLite for improved concurrency.

4. Run Norman once to automatically generate `config.yaml` with secure defaults.
   Afterwards edit this file to configure connectors and add your OpenAI API key.

5. (Optional) Regenerate the secrets in `config.yaml` using the provided script:

```
chmod +x generate_key.sh
./generate_key.sh
```

You can also edit `config.yaml` manually to provide your own values. Be sure to add your OpenAI key under `openai_api_key`.

6. Run the application with Uvicorn:
```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --compression gzip
```
If `brotli_asgi` is installed and supported by your Uvicorn version,
replace `gzip` with `brotli` for improved compression.

7. Open the API documentation in your browser: [http://localhost:8000/docs](http://localhost:8000/docs)
   A basic health check endpoint is available at [http://localhost:8000/health](http://localhost:8000/health)

Norman emits structured JSON logs that include the timestamp, module and request ID. Sensitive data such as API keys are automatically redacted so these logs can be safely forwarded to monitoring systems.

For more information, refer to the [documentation](docs/) and the [contributing guidelines](CONTRIBUTING.md).

## Usage

For detailed information on how to use Norman, see the [Usage](./docs/usage.md) guide.
Practical walkthroughs and API calls can be found in the [Examples](./docs/examples.md) document.

## Testing

Automated tests are powered by `pytest`. The development dependencies are listed
in `requirements-dev.txt`.

```bash
pip install -r requirements-dev.txt
pytest -vv
```

For a test coverage report you can additionally run:

```bash
pytest --cov=./ -vv
```

## Deployment

Norman can be deployed on various platforms, such as on a local server or a cloud provider. For detailed deployment instructions, please refer to our [Deployment](docs/deployment.md) guide. A separate [Docker Deployment](docs/docker.md) guide is available if you prefer running Norman in containers.

## Architecture

The architecture of Norman is designed to be modular and scalable. We have a detailed explanation of our architectural principles in our [Architecture](docs/architecture.md) document, complete with a simple diagram to help you understand the structure.

## Extending Norman

Norman is built to be extensible, allowing you to add new connectors, actions, and filters as needed. To learn more about extending Norman, refer to our [Extending Norman](docs/extending.md) guide.

## Philosophy

We created Norman to provide an open, self-hosted, and open-source solution for accessing large language models like GPT-4. We hope others can build upon and extend Norman to incorporate additional chat technologies and channels. Our philosophy centers on continuous improvement, utilizing automation, and striving for excellence in our project. Learn more about our philosophy in our [Philosophy](docs/philosophy.md) document.

## Contributing

We welcome contributions from the community! If you're interested in helping us improve Norman, please refer to our [Contributing](CONTRIBUTING.md) guide.

## Community

Norman is more than just a software project; it's a community of developers and users working together to create something special. To learn more about our community and how to get involved, check out our [Community](docs/community.md) page.

## License

Norman is licensed under the MIT License. For more information, see the [LICENSE.md](LICENSE.md) file.
