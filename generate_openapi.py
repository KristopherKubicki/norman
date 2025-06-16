"""Utility to generate OpenAPI schema JSON."""

from pathlib import Path
import json

from main import app


def generate_schema(path: Path = Path("docs/openapi.json")) -> Path:
    """Generate the OpenAPI schema and write it to ``path``."""
    schema = app.openapi()
    path.write_text(json.dumps(schema, indent=2))
    return path


def main() -> None:
    """Entry point for the script."""
    output = generate_schema()
    print(f"OpenAPI schema written to {output}")


if __name__ == "__main__":
    main()
