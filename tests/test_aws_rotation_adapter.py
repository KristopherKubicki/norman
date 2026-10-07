"""Fixed AWS bindings and SDK failure boundaries, with no live AWS calls."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.services import aws_rotation_adapter as module
from app.services.aws_rotation_store import ACCOUNT, OLD_KEY, RotationError


@pytest.fixture
def rig(monkeypatch):
    session, iam, sts, transport = Mock(), Mock(), Mock(), Mock()
    factory = Mock(return_value=session)
    monkeypatch.setattr(module.boto3, "Session", factory)
    session.client.side_effect = lambda service, **kwargs: {"iam": iam, "sts": sts}[
        service
    ]
    session.get_credentials.return_value.get_frozen_credentials.return_value = (
        SimpleNamespace(access_key=OLD_KEY, token=None)
    )
    sts.get_caller_identity.return_value = {"Account": ACCOUNT, "Arn": module.PRINCIPAL}
    iam.list_access_keys.return_value = {
        "AccessKeyMetadata": [{"AccessKeyId": OLD_KEY, "Status": "Active"}]
    }
    iam.create_access_key.return_value = {
        "AccessKey": {
            "AccessKeyId": "dummy-new",
            "SecretAccessKey": "dummy-secret",
            "UserName": "cloudagent",
            "Status": "Active",
        }
    }
    transport.ready.return_value = True
    return module.AWSRotationAdapter(transport), session, iam, sts, factory, transport


def test_fixed_identity_endpoints_and_no_create_retries(rig):
    adapter, session, iam, _, factory, transport = rig
    assert adapter.preflight() is True
    assert adapter.create() == ("dummy-new", "dummy-secret")
    factory.assert_called_once_with(profile_name="kk-personal", region_name="us-east-1")
    iam.create_access_key.assert_called_once_with(UserName="cloudagent")
    assert transport.ready.call_count == 3
    for call in session.client.call_args_list:
        assert call.kwargs["verify"] is True
        assert call.kwargs["config"].retries == {"total_max_attempts": 1}
        assert call.kwargs["endpoint_url"] in (
            "https://iam.amazonaws.com",
            "https://sts.us-east-1.amazonaws.com",
        )


def test_wrong_account_or_principal_rejected(rig):
    adapter, _, iam, sts, _, _ = rig
    sts.get_caller_identity.return_value = {"Account": ACCOUNT, "Arn": "other-user"}
    with pytest.raises(RotationError, match="rotation_identity_mismatch"):
        adapter.preflight()
    iam.create_access_key.assert_not_called()


def test_existing_second_key_prevents_creation(rig):
    adapter, _, iam, _, _, _ = rig
    iam.list_access_keys.return_value["AccessKeyMetadata"].append(
        {"AccessKeyId": "unexpected-key", "Status": "Inactive"}
    )
    assert adapter.preflight() is False
    iam.create_access_key.assert_not_called()


def test_wrong_source_key_or_temporary_session_rejected(rig):
    adapter, session, _, _, _, _ = rig
    credentials = (
        session.get_credentials.return_value.get_frozen_credentials.return_value
    )
    credentials.token = "dummy-token"
    assert adapter.preflight() is False
    credentials.token = None
    credentials.access_key = "unexpected-key"
    assert adapter.preflight() is False


def test_unready_receiver_blocks_preflight(rig):
    adapter, _, _, _, _, transport = rig
    transport.ready.return_value = False
    assert adapter.preflight() is False


def test_disable_authenticates_with_new_key_and_only_updates_old_key(rig):
    adapter, _, iam, _, factory, _ = rig
    iam.list_access_keys.return_value = {
        "AccessKeyMetadata": [
            {"AccessKeyId": OLD_KEY, "Status": "Inactive"},
            {"AccessKeyId": "dummy-new", "Status": "Active"},
        ]
    }
    adapter.set_old_active("dummy-new", "dummy-secret", False)
    factory.assert_called_once_with(
        aws_access_key_id="dummy-new",
        aws_secret_access_key="dummy-secret",
        region_name="us-east-1",
    )
    iam.update_access_key.assert_called_once_with(
        UserName="cloudagent", AccessKeyId=OLD_KEY, Status="Inactive"
    )


def test_failed_readback_does_not_claim_success(rig):
    adapter, _, _, _, _, _ = rig
    with pytest.raises(RotationError, match="rotation_status_unverified"):
        adapter.set_old_active("dummy-new", "dummy-secret", False)


def test_cannot_create_without_preflight(rig):
    adapter, _, iam, _, _, _ = rig
    with pytest.raises(RotationError, match="rotation_preflight_required"):
        adapter.create()
    iam.create_access_key.assert_not_called()


def test_failed_preflight_cannot_be_bypassed_by_create(rig):
    adapter, _, iam, _, _, transport = rig
    transport.ready.return_value = False
    assert adapter.preflight() is False
    with pytest.raises(RotationError, match="rotation_preflight_required"):
        adapter.create()
    iam.create_access_key.assert_not_called()


def test_create_cannot_replay_after_success_or_uncertain_failure(rig):
    adapter, _, iam, _, _, _ = rig
    assert adapter.preflight() is True
    iam.create_access_key.side_effect = RuntimeError("dummy-network-timeout")
    with pytest.raises(RuntimeError):
        adapter.create()
    with pytest.raises(RotationError, match="rotation_preflight_required"):
        adapter.create()
    assert iam.create_access_key.call_count == 1
