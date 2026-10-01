"""Persistence tests for observe-only Kaizen records."""

from datetime import datetime, timedelta, timezone

from app.services.kaizen.store import DbKaizenStore
from app.services.kaizen.evidence import build_tui_observations
from tests.kaizen_helpers import create_kaizen_user, kpi_observation, tui_snapshot


def _record_tui_snapshot(db, *, user_id: int, **kwargs) -> None:
    DbKaizenStore().record_observations(
        db,
        user_id=user_id,
        observations=build_tui_observations(tui_snapshot(**kwargs)),
    )


def test_observations_are_idempotent_and_realm_scoped(db) -> None:
    store = DbKaizenStore()
    owner = create_kaizen_user(db)
    other = create_kaizen_user(db)
    observed_at = datetime(2026, 8, 2, 14, tzinfo=timezone.utc)
    observation = kpi_observation(kpi_id="tui_queue_depth", observed_at=observed_at)

    first = store.record_observations(db, user_id=owner.id, observations=[observation])
    second = store.record_observations(db, user_id=owner.id, observations=[observation])
    store.record_observations(db, user_id=other.id, observations=[observation])
    work = kpi_observation(
        kpi_id="tui_queue_depth",
        realm="work",
        observed_at=observed_at,
    )
    store.record_observations(db, user_id=owner.id, observations=[work])

    assert first[0]["id"] == second[0]["id"]
    assert (
        len(store.list_observations(db, user_id=owner.id, realm="personal/home")) == 1
    )
    other_items = store.list_observations(db, user_id=other.id, realm="personal/home")
    assert len(other_items) == 1
    assert other_items[0]["id"] != first[0]["id"]
    assert (
        store.list_observations(db, user_id=owner.id, realm="work")[0]["realm"]
        == "work"
    )


def test_reports_upsert_within_the_same_user_realm_period(db) -> None:
    store = DbKaizenStore()
    owner = create_kaizen_user(db)
    start = datetime(2026, 8, 2, 5, tzinfo=timezone.utc)
    end = datetime(2026, 8, 3, 5, tzinfo=timezone.utc)

    first = store.save_report(
        db,
        user_id=owner.id,
        realm="personal/home",
        kind="daily",
        period_key="2026-08-02",
        period_start=start,
        period_end=end,
        payload={"revision": 1},
    )
    second = store.save_report(
        db,
        user_id=owner.id,
        realm="personal/home",
        kind="daily",
        period_key="2026-08-02",
        period_start=start,
        period_end=end,
        payload={"revision": 2},
    )

    assert first["report_id"] == second["report_id"]
    assert second["payload"] == {"revision": 2}
    assert (
        store.latest_report(db, user_id=owner.id, realm="personal/home", kind="daily")[
            "report_id"
        ]
        == first["report_id"]
    )


def test_list_fresh_pilot_snapshot_scopes_requires_the_newest_snapshot_to_be_fresh(
    db,
) -> None:
    store = DbKaizenStore()
    now = datetime(2026, 8, 2, 16, tzinfo=timezone.utc)
    pilot_tui = "store-fresh-pilot"
    fresh_at = now - timedelta(seconds=10)
    stale_at = now - timedelta(minutes=10)
    future_at = now + timedelta(seconds=1)
    included = create_kaizen_user(db)
    stale = create_kaizen_user(db)
    future = create_kaizen_user(db)
    wrong_realm = create_kaizen_user(db)
    wrong_tui = create_kaizen_user(db)

    _record_tui_snapshot(
        db,
        user_id=included.id,
        source_tui=pilot_tui,
        observed_at=stale_at,
    )
    _record_tui_snapshot(
        db,
        user_id=included.id,
        source_tui=pilot_tui,
        observed_at=fresh_at,
    )
    _record_tui_snapshot(
        db,
        user_id=stale.id,
        source_tui=pilot_tui,
        observed_at=stale_at,
    )
    _record_tui_snapshot(
        db,
        user_id=future.id,
        source_tui=pilot_tui,
        observed_at=fresh_at,
    )
    _record_tui_snapshot(
        db,
        user_id=future.id,
        source_tui=pilot_tui,
        observed_at=future_at,
    )
    _record_tui_snapshot(
        db,
        user_id=wrong_realm.id,
        realm="work",
        source_tui=pilot_tui,
        observed_at=fresh_at,
    )
    _record_tui_snapshot(
        db,
        user_id=wrong_tui.id,
        source_tui="store-other-tui",
        observed_at=fresh_at,
    )

    scopes = store.list_fresh_pilot_snapshot_scopes(
        db,
        pilot_tui_ids=(pilot_tui,),
        allowed_realms=("personal/home",),
        observed_after=now - timedelta(minutes=5),
        observed_before=now,
        limit=10,
    )

    assert scopes == [(included.id, "personal/home", pilot_tui)]


def test_list_fresh_pilot_snapshot_scopes_uses_stable_cursor_order(db) -> None:
    store = DbKaizenStore()
    now = datetime(2026, 8, 2, 16, tzinfo=timezone.utc)
    first = create_kaizen_user(db)
    second = create_kaizen_user(db)
    _record_tui_snapshot(
        db,
        user_id=first.id,
        source_tui="pilot-b",
        observed_at=now,
    )
    _record_tui_snapshot(
        db,
        user_id=first.id,
        source_tui="pilot-a",
        observed_at=now,
    )
    _record_tui_snapshot(
        db,
        user_id=second.id,
        source_tui="pilot-a",
        observed_at=now,
    )
    expected = [
        (first.id, "personal/home", "pilot-a"),
        (first.id, "personal/home", "pilot-b"),
        (second.id, "personal/home", "pilot-a"),
    ]

    all_scopes = store.list_fresh_pilot_snapshot_scopes(
        db,
        pilot_tui_ids=("pilot-a", "pilot-b"),
        allowed_realms=("personal/home",),
        observed_after=now - timedelta(minutes=1),
        observed_before=now,
        limit=10,
    )
    after_first = store.list_fresh_pilot_snapshot_scopes(
        db,
        pilot_tui_ids=("pilot-a", "pilot-b"),
        allowed_realms=("personal/home",),
        observed_after=now - timedelta(minutes=1),
        observed_before=now,
        after_scope=expected[0],
        limit=10,
    )

    assert all_scopes == expected
    assert after_first == expected[1:]
