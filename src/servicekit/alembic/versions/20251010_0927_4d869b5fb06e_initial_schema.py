"""Initial database schema migration - no tables for pure framework.

Note: While servicekit is a pure framework without domain tables,
the Entity base class includes common fields (id, created_at, updated_at, tags)
that all domain entities inherit. These fields are defined in the ORM models
and automatically included when domain tables are created.
"""

# revision identifiers, used by Alembic.
revision = "4d869b5fb06e"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Apply database schema changes."""
    # Servicekit is a pure framework - no domain-specific tables
    # Domain tables (tasks, artifacts, configs) are provided by chapkit
    # Entity base class fields (id, created_at, updated_at, tags) are
    # automatically included in all domain entity tables via ORM inheritance
    pass


def downgrade() -> None:
    """Revert database schema changes."""
    pass
