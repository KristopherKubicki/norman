from pathlib import Path


def test_connectors_ui_exposes_sms_webhook_url_and_catalog_entry():
    html = Path("app/templates/connectors.html").read_text()
    js = Path("app/static/js/connectors.js").read_text()

    assert 'id="sms-webhook-url"' in html
    assert "id: 'sms'" in js
    assert "SMS messages via Twilio." in js
    assert "/api/v1/connectors/sms/webhooks/sms/{connector_id}" in js
    assert "/api/v1/connectors/whatsapp/webhooks/whatsapp/{connector_id}" in js
