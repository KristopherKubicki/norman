from app.services.notifications import approval_payload


def test_approval_payload_does_not_include_confirm_token():
    class Dummy:
        id = 12
        connector_id = 7
        status = "pending"
        command_class = "destructive"
        reason = "high-risk"
        command_text = "rm -rf /"
        confirm_token = "abc123"

    payload = approval_payload(approval=Dummy(), connector_name="Ops tmux")
    assert "confirm_token" not in payload
    assert payload["approval_id"] == 12
    assert payload["connector_id"] == 7
    assert payload["command_preview"]
