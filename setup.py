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
        "psycopg2",
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
    python_requires=">=3.8, <3.12",
    entry_points={
        "console_scripts": [
            "norman = main:main",
        ],
    },
)
