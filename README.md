# Norman

Norman is an open-source chatbot that leverages OpenAI's GPT models to assist and automate communication on various chat platforms like Slack and IRC. The project is built with FastAPI, SQLite, and SQLAlchemy, and is designed to be easily extensible with additional connectors.

## Table of Contents

- [Features](#features)
- [Requirements](#requirements)
- [Installation](#installation)
- [Usage](#usage)
- [Contributing](#contributing)
- [License](#license)

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

4. Create a `config.yaml` based on the provided `config.yaml.dist`:
```
cp config.yaml.dist config.yaml
```

5. Edit `config.yaml` to configure the application, connectors, and API keys.

6. Run the application:
```
python main.py
````

7. Open the API documentation in your browser: [http://localhost:8000/docs](http://localhost:8000/docs)

For more information, refer to the [documentation](docs/) and the [contributing guidelines](CONTRIBUTING.md).

## Usage

For detailed information on how to use Norman, please refer to the [Usage](./docs/usage.md) section in the documentation.

## Deployment

Norman can be deployed on various platforms, such as on a local server or a cloud provider. For detailed deployment instructions, please refer to our [Deployment](docs/deployment.md) guide.

## Architecture

The architecture of Norman is designed to be modular and scalable. We have a detailed explanation of our architectural principles in our [Architecture](docs/architecture.md) document, complete with a simple diagram to help you understand the structure.

## Extending Norman

Norman is built to be extensible, allowing you to add new connectors, actions, and filters as needed. To learn more about extending Norman, refer to our [Extending Norman](docs/extending.md) guide.

## Philosophy

We created Norman to provide an open, self-hosted, and open-source solution for accessing large language models like GPT-4. We hope others can build upon and extend Norman to incorporate additional chat technologies and channels. Our philosophy centers on continuous improvement, utilizing automation, and striving for excellence in our project. Learn more about our philosophy in our [Philosophy](docs/philosophy.md) document.

## Contributing

We welcome contributions from the community! If you're interested in helping us improve Norman, please refer to our [Contributing](docs/contributing.md) guide.

## Community

Norman is more than just a software project; it's a community of developers and users working together to create something special. To learn more about our community and how to get involved, check out our [Community](docs/community.md) page.

## License

Norman is licensed under the MIT License. For more information, see the [LICENSE.md](LICENSE.md) file.
