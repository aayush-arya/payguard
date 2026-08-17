"""ledger entries immutability trigger

Revision ID: ab10ded442e0
Revises: 7c2fff35d572
Create Date: 2026-08-18 00:03:46.984375

Application code never updates or deletes ledger_entries rows (ADR-007), but
that's an application-layer promise, not a guarantee -- a bug, a bad
migration, or a manual `UPDATE` from a console could silently violate it.
This trigger is the database-level backstop: it fires regardless of which
role or code path attempts the mutation, so "the ledger is append-only" is
provably true of the data, not just of the code that's supposed to write it.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "ab10ded442e0"
down_revision: str | None = "7c2fff35d572"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION prevent_ledger_entries_mutation()
        RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'ledger_entries rows are immutable and cannot be updated or deleted (id=%)',
                COALESCE(OLD.id, NEW.id);
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER ledger_entries_no_update
        BEFORE UPDATE ON ledger_entries
        FOR EACH ROW EXECUTE FUNCTION prevent_ledger_entries_mutation();
        """
    )
    op.execute(
        """
        CREATE TRIGGER ledger_entries_no_delete
        BEFORE DELETE ON ledger_entries
        FOR EACH ROW EXECUTE FUNCTION prevent_ledger_entries_mutation();
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS ledger_entries_no_delete ON ledger_entries;")
    op.execute("DROP TRIGGER IF EXISTS ledger_entries_no_update ON ledger_entries;")
    op.execute("DROP FUNCTION IF EXISTS prevent_ledger_entries_mutation();")
