from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0003_notes_reflections"
down_revision = "0002_launch_designs"
branch_labels = None
depends_on = None


def upgrade():
    priority = postgresql.ENUM("low", "medium", "high", name="note_priority", create_type=False)
    status = postgresql.ENUM("open", "in_progress", "done", name="note_status", create_type=False)
    priority.create(op.get_bind(), checkfirst=True)
    status.create(op.get_bind(), checkfirst=True)
    op.add_column("notes", sa.Column("problem_or_practice", sa.Text(), nullable=True))
    op.add_column("notes", sa.Column("cause", sa.Text(), nullable=True))
    op.add_column("notes", sa.Column("proposed_solution", sa.Text(), nullable=True))
    op.add_column("notes", sa.Column("priority", priority, server_default="medium", nullable=False))
    op.add_column("notes", sa.Column("status", status, server_default="open", nullable=False))
    op.create_table(
        "launch_reflections",
        sa.Column("launch_id", sa.Integer(), nullable=False),
        sa.Column("what_went_well", sa.Text(), nullable=True),
        sa.Column("recurring_problems", sa.Text(), nullable=True),
        sa.Column("materials_to_update", sa.Text(), nullable=True),
        sa.Column("decisions_to_keep", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("launch_id"),
        sa.ForeignKeyConstraint(["launch_id"], ["launches.id"], ondelete="CASCADE"),
    )


def downgrade():
    op.drop_table("launch_reflections")
    for name in ("status", "priority", "proposed_solution", "cause", "problem_or_practice"):
        op.drop_column("notes", name)
    postgresql.ENUM(name="note_status").drop(op.get_bind(), checkfirst=True)
    postgresql.ENUM(name="note_priority").drop(op.get_bind(), checkfirst=True)
