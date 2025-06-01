from setuptools import setup, find_packages

setup(
    name="norman",
    version="0.1",
    packages=find_packages(),
    install_requires=[
        "fastapi",
        "uvicorn",
        "sqlalchemy",
        "alembic",
        "psycopg2-binary",
        "pika",
        "httpx",
        "requests",
    ],
    extras_require={
        "dev": [
            "pytest",
            "coverage",
            "flake8",
            "black",
            "mypy",
            "pytest",
            "pytest-asyncio",
        ]
    },
    entry_points={
        "console_scripts": [
            "norman = main:main",
        ],
    },
)
