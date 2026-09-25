"""Security boundaries for the staged AWS readiness executor."""

from unittest.mock import Mock

import pytest
from botocore.exceptions import ClientError

from app.services import aws_keys_readiness as executor


@pytest.fixture
def sdk(monkeypatch):
    """Replace all AWS networking with a controlled session."""
    session = Mock()
    factory = Mock(return_value=session)
    monkeypatch.setattr(executor.boto3, "Session", factory)
    sts, iam = Mock(), Mock()
    session.client.side_effect = lambda service, **kwargs: {"sts": sts, "iam": iam}[
        service
    ]
    sts.get_caller_identity.return_value = {
        "Account": "104637383649",
        "Arn": "arn:aws:sts::104637383649:assumed-role/CloudAgentManagement/test",
        "SecretAccessKey": "must-not-return",
    }
    iam.get_account_summary.return_value = {
        "SummaryMap": {"AccountMFAEnabled": 1, "untrusted": "must-not-return"}
    }
    return factory, session, sts, iam


def run(**overrides):
    """Use the ACM binding unless testing a rejected request."""
    args = {
        "executor_ref": "104637383649",
        "action": "inspect",
        "parameters": {"account_id": "104637383649"},
    }
    return executor.execute_readiness(**(args | overrides))


def test_receipt_is_allowlisted_and_endpoint_is_pinned(sdk):
    factory, session, _, _ = sdk
    assert run() == {
        "account_id": "104637383649",
        "identity_verified": True,
        "root_mfa_enabled": True,
    }
    factory.assert_called_once_with(profile_name="kk-acm", region_name="us-east-1")
    assert [c.kwargs["endpoint_url"] for c in session.client.call_args_list] == [
        "https://sts.us-east-1.amazonaws.com",
        "https://iam.amazonaws.com",
    ]
    assert all(c.kwargs["verify"] is True for c in session.client.call_args_list)


@pytest.mark.parametrize(
    "overrides",
    [
        {"executor_ref": "083762351172"},
        {"executor_ref": "770311548538"},
        {"action": "create-access-key"},
        {"parameters": {"account_id": "970651210182"}},
        {"parameters": {"account_id": "104637383649", "profile": "default"}},
        {
            "parameters": {
                "account_id": "104637383649",
                "endpoint": "https://example.com",
            }
        },
    ],
)
def test_rejects_unapproved_requests_before_sdk(sdk, overrides):
    with pytest.raises(executor.AWSReadinessError):
        run(**overrides)
    sdk[0].assert_not_called()


@pytest.mark.parametrize(
    "arn",
    [
        "arn:aws:iam::104637383649:root",
        "arn:aws:sts::104637383649:assumed-role/CloudAgentManagementEvil/test",
        "arn:aws:sts::104637383649:assumed-role/CloudAgentManagement/",
    ],
)
def test_wrong_principal_prevents_iam_check(sdk, arn):
    sdk[2].get_caller_identity.return_value["Arn"] = arn
    with pytest.raises(executor.AWSReadinessError, match="aws_identity_mismatch"):
        run()
    sdk[3].get_account_summary.assert_not_called()


def test_wrong_account_prevents_iam_check(sdk):
    sdk[2].get_caller_identity.return_value["Account"] = "770311548538"
    with pytest.raises(executor.AWSReadinessError, match="aws_identity_mismatch"):
        run()
    sdk[3].get_account_summary.assert_not_called()


def test_sdk_errors_do_not_escape(sdk):
    sdk[2].get_caller_identity.side_effect = ClientError(
        {"Error": {"Code": "Denied", "Message": "must-not-return"}}, "GetCallerIdentity"
    )
    with pytest.raises(executor.AWSReadinessError) as error:
        run()
    assert str(error.value) == "aws_check_failed"
    assert error.value.__suppress_context__


@pytest.mark.parametrize("account", list(executor.ACCOUNTS))
def test_each_bound_account_and_disabled_mfa(sdk, account):
    profile, arn = executor.ACCOUNTS[account]
    sdk[2].get_caller_identity.return_value = {
        "Account": account,
        "Arn": arn + "session" if arn.endswith("/") else arn,
    }
    sdk[3].get_account_summary.return_value = {"SummaryMap": {"AccountMFAEnabled": 0}}
    assert run(executor_ref=account, parameters={"account_id": account}) == {
        "account_id": account,
        "identity_verified": True,
        "root_mfa_enabled": False,
    }
    sdk[0].assert_called_once_with(profile_name=profile, region_name="us-east-1")


@pytest.mark.parametrize("value", [None, True, "1", 2])
def test_malformed_mfa_is_not_reported_as_success(sdk, value):
    sdk[3].get_account_summary.return_value = {
        "SummaryMap": {"AccountMFAEnabled": value}
    }
    with pytest.raises(executor.AWSReadinessError, match="aws_summary_invalid"):
        run()
