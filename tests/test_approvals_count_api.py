from app import crud
from app.schemas.command_approval import CommandApprovalDecision
from app.schemas.connector import ConnectorCreate


def test_approvals_count_endpoint(test_app, db):
    before = test_app.get("/api/v1/approvals/count?status=pending").json()["count"]

    user = test_app.get("/api/v1/users/me").json()
    connector = crud.connector.create(
        db,
        obj_in=ConnectorCreate(
            name="tmux ops", connector_type="tmux", config={"session": "ops"}
        ),
        user_id=user["id"],
    )
    crud.command_approval.create(
        db,
        user_id=user["id"],
        connector_id=int(connector.id),
        event_id=None,
        command_text="echo hello",
        command_class="change",
        reason="needs approval",
    )

    after = test_app.get("/api/v1/approvals/count?status=pending").json()["count"]
    assert after == before + 1


def test_approvals_count_respects_status_filter(test_app, db, monkeypatch):
    from app.core.config import settings

    # Avoid executing tmux in tests; approvals should still transition status.
    monkeypatch.setattr(settings, "safety_read_only", True)

    pending_before = test_app.get("/api/v1/approvals/count?status=pending").json()[
        "count"
    ]
    approved_before = test_app.get("/api/v1/approvals/count?status=approved").json()[
        "count"
    ]

    user = test_app.get("/api/v1/users/me").json()
    connector = crud.connector.create(
        db,
        obj_in=ConnectorCreate(
            name="tmux ops", connector_type="tmux", config={"session": "ops"}
        ),
        user_id=user["id"],
    )
    approval = crud.command_approval.create(
        db,
        user_id=user["id"],
        connector_id=int(connector.id),
        event_id=None,
        command_text="echo hello",
        command_class="change",
        reason="needs approval",
    )

    resp = test_app.post(
        f"/api/v1/approvals/{approval.id}/approve",
        json=CommandApprovalDecision(reason="approved").dict(),
    )
    assert resp.status_code == 200

    pending_after = test_app.get("/api/v1/approvals/count?status=pending").json()[
        "count"
    ]
    approved_after = test_app.get("/api/v1/approvals/count?status=approved").json()[
        "count"
    ]

    assert pending_after == pending_before
    assert approved_after == approved_before + 1
