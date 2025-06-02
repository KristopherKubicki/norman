import yaml
from fastapi.testclient import TestClient
from app.core.config import settings


def test_update_slack_credentials(test_app: TestClient):
    with open("config.yaml") as f:
        orig = yaml.safe_load(f)
    data = {"token": "x-test", "channel_id": "C123"}
    resp = test_app.post("/api/credentials/slack", json=data)
    assert resp.status_code == 200
    with open("config.yaml") as f:
        cfg = yaml.safe_load(f)
    assert cfg["slack_token"].startswith("ENC:") or cfg["slack_token"] == data["token"]
    assert settings.slack_token == data["token"]
    # restore
    with open("config.yaml", "w") as f:
        yaml.safe_dump(orig, f)
    settings.slack_token = orig.get("slack_token", "")
    settings.slack_channel_id = orig.get("slack_channel_id", "")
