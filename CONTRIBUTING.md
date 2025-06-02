# Contributing to Norman

Thank you for considering contributing to Norman! We appreciate your help and support. This document outlines the guidelines and best practices for contributing to the project. By following these guidelines, we can ensure a smooth and productive collaborative experience.

## Table of Contents

- [Code of Conduct](#code-of-conduct)
- [Getting Started](#getting-started)
- [Submitting Issues](#submitting-issues)
- [Pull Requests](#pull-requests)
- [Coding Standards](#coding-standards)
- [Testing](#testing)
- [Documentation](#documentation)
- [Community](#community)

## Code of Conduct

Please read and follow our [Code of Conduct](CODE_OF_CONDUCT.md) to maintain a welcoming, inclusive, and respectful environment for everyone.

## Getting Started

1. Fork the repository on GitHub.
2. Clone your forked repository to your local machine.
3. Create a new branch for your changes.
4. Install the required dependencies and set up the development environment.
5. Make your changes and commit them to your branch.
6. Push your changes to your forked repository on GitHub.
7. Create a Pull Request (PR) to submit your changes for review.

## Submitting Issues

Before submitting an issue, please check the existing issues to ensure that your issue hasn't already been reported. If you find an existing issue that closely matches yours, you can add your information to that issue.

When submitting a new issue, please provide as much information as possible, including:

- A clear and descriptive title.
- A detailed description of the problem or feature request.
- Steps to reproduce the issue (if applicable).
- Screenshots, error messages, or logs that can help illustrate the issue.

## Pull Requests

When submitting a Pull Request (PR), please ensure that:

- Your PR targets the correct branch.
- Your PR includes a clear and concise description of the changes.
- Your PR includes tests for new functionality or bug fixes.
- Your PR passes all existing tests and checks.
- Your PR follows the project's [coding standards](#coding-standards).

## Coding Standards

Please adhere to the following coding standards when contributing to the project:

- Use clear and descriptive variable and function names.
- Include comments to explain complex or non-obvious code.
- Keep functions and methods small and focused on a single task.
- Follow the established code structure and organization.
### Style Guide
- Run `make lint` or use `pre-commit` to format with Black and check with pylint.
- Use `snake_case` for functions and variables and `CamelCase` for classes.
- Name database session objects `db` when passed as a dependency.
- Keep error handling consistent across connectors.


## Testing

Before submitting your changes, please ensure that your code passes all existing tests. Additionally, if you are adding new functionality or fixing bugs, please include appropriate tests for your changes.

## Documentation

If your changes involve new functionality, please update the relevant documentation to reflect those changes. Similarly, if you find any outdated or incorrect documentation, please update it accordingly.

## Community

We encourage you to join our community and engage in discussions, share your experiences, and contribute to the project. By working together, we can create a powerful and versatile platform that benefits everyone.
