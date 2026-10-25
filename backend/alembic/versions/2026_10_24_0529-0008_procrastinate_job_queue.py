"""procrastinate job queue

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-24 05:29:47.098019+00:00

Must stay backward compatible with the previous app version (expand → migrate → contract).
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0008"
down_revision: str | Sequence[str] | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Procrastinate's own schema (tables, types, functions) at the installed version.
    from procrastinate.schema import SchemaManager
    from sqlalchemy.util import await_only

    # Many statements in one script: asyncpg runs those only outside a prepared statement.
    driver = op.get_bind().connection.driver_connection
    assert driver is not None
    await_only(driver.execute(SchemaManager.get_schema()))


def downgrade() -> None:
    op.execute(
        """
        DO $$
        DECLARE r record;
        BEGIN
          FOR r IN SELECT tablename FROM pg_tables WHERE tablename LIKE 'procrastinate_%' LOOP
            EXECUTE format('DROP TABLE IF EXISTS %I CASCADE', r.tablename);
          END LOOP;
          FOR r IN SELECT p.oid::regprocedure AS sig FROM pg_proc p
                   WHERE p.proname LIKE 'procrastinate_%' LOOP
            EXECUTE format('DROP FUNCTION IF EXISTS %s CASCADE', r.sig);
          END LOOP;
          FOR r IN SELECT typname FROM pg_type WHERE typname LIKE 'procrastinate_%'
                   AND typtype IN ('e', 'c') LOOP
            EXECUTE format('DROP TYPE IF EXISTS %I CASCADE', r.typname);
          END LOOP;
        END $$;
        """
    )
