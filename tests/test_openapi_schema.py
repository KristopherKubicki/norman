from pathlib import Path
import json

from generate_openapi import generate_schema


def test_generate_schema(tmp_path: Path) -> None:
    """Ensure the OpenAPI schema is generated."""
    out = generate_schema(tmp_path / "schema.json")
    assert out.exists()
    data = json.loads(out.read_text())
    assert "openapi" in data
    assert data["openapi"].startswith("3")
