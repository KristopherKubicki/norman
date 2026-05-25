"""Add destination connector support to routing rules/events.

Revision ID: 9b3c1b6e9f4a
Revises: 8d3c8c1d2c1e
Create Date: 2026-02-15

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "9b3c1b6e9f4a"
down_revision = "8d3c8c1d2c1e"
branch_labels = None
depends_on = None


def _sqlite_column_exists(conn, table: str, column: str) -> bool:
    rows = conn.execute(sa.text(f"PRAGMA table_info({table})")).fetchall()
    # PRAGMA table_info: (cid, name, type, notnull, dflt_value, pk)
    return any(row[1] == column for row in rows)


def _sqlite_index_exists(conn, table: str, index_name: str) -> bool:
    # Prefer PRAGMA index_list because it reflects in-connection schema state.
    try:
        rows = conn.execute(sa.text(f"PRAGMA index_list('{table}')")).fetchall()
        # PRAGMA index_list: (seq, name, unique, origin, partial)
        if any(row[1] == index_name for row in rows):
            return True
    except Exception:
        # Fall back to sqlite_master below.
        pass

    row = conn.execute(
        sa.text("SELECT 1 FROM sqlite_master WHERE type='index' AND name=:name"),
        {"name": index_name},
    ).fetchone()
    return row is not None


def upgrade():
    conn = op.get_bind()
    dialect = conn.dialect.name

    # These migrations are often run against SQLite (and sometimes re-run after
    # partial failure). Make them idempotent.
    if dialect == "sqlite":
        if not _sqlite_column_exists(conn, "routing_rules", "destination_connector_id"):
            op.add_column(
                "routing_rules",
                sa.Column("destination_connector_id", sa.Integer(), nullable=True),
            )

        if not _sqlite_column_exists(conn, "routing_events", "destination_connector_id"):
            op.add_column(
                "routing_events",
                sa.Column("destination_connector_id", sa.Integer(), nullable=True),
            )

        if not _sqlite_column_exists(conn, "routing_events", "destination_connector_type"):
            op.add_column(
                "routing_events",
                sa.Column("destination_connector_type", sa.String(), nullable=True),
            )

        if not _sqlite_index_exists(
            conn, "routing_rules", "ix_routing_rules_destination_connector_id"
        ):
            try:
                op.create_index(
                    "ix_routing_rules_destination_connector_id",
                    "routing_rules",
                    ["destination_connector_id"],
                )
            except Exception:
                pass
        if not _sqlite_index_exists(
            conn, "routing_events", "ix_routing_events_destination_connector_id"
        ):
            try:
                op.create_index(
                    "ix_routing_events_destination_connector_id",
                    "routing_events",
                    ["destination_connector_id"],
                )
            except Exception:
                pass
        return

    op.add_column(
        "routing_rules",
        sa.Column("destination_connector_id", sa.Integer(), nullable=True),
    )
    op.add_column(
        "routing_events",
        sa.Column("destination_connector_id", sa.Integer(), nullable=True),
    )
    op.add_column(
        "routing_events",
        sa.Column("destination_connector_type", sa.String(), nullable=True),
    )

    # Alembic supports if_not_exists on some dialects, but keep safe.
    try:
        op.create_index(
            "ix_routing_rules_destination_connector_id",
            "routing_rules",
            ["destination_connector_id"],
        )
    except Exception:
        pass
    try:
        op.create_index(
            "ix_routing_events_destination_connector_id",
            "routing_events",
            ["destination_connector_id"],
        )
    except Exception:
        pass


def downgrade():
    # Best-effort downgrade.
    try:
        op.drop_index(
            "ix_routing_events_destination_connector_id", table_name="routing_events"
        )
    except Exception:
        pass
    try:
        op.drop_index(
            "ix_routing_rules_destination_connector_id", table_name="routing_rules"
        )
    except Exception:
        pass

    with op.batch_alter_table("routing_events") as batch:
        for col in ("destination_connector_type", "destination_connector_id"):
            try:
                batch.drop_column(col)
            except Exception:
                pass

    with op.batch_alter_table("routing_rules") as batch:
        try:
            batch.drop_column("destination_connector_id")
        except Exception:
            pass
