from alembic import op
from pgvector.sqlalchemy import VECTOR
import sqlalchemy as sa

revision = "0004_ai_storage"
down_revision = "0003_notes_reflections"
branch_labels = None
depends_on = None


def upgrade():
    # Server-side pgvector files must be present in the PostgreSQL image.
    # Keep the shared extension outside per-test/application schemas.
    op.execute("CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA public")
    op.create_table(
        "document_chunks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("stored_file_id", sa.Integer(), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=True),
        sa.Column("slide_number", sa.Integer(), nullable=True),
        sa.Column("sheet_name", sa.String(255), nullable=True),
        sa.Column("cell_range", sa.String(64), nullable=True),
        sa.Column("embedding", VECTOR(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["stored_file_id"], ["stored_files.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("stored_file_id", "chunk_index", name="uq_chunk_file_index"),
        sa.CheckConstraint("chunk_index >= 0", name="chk_chunk_index"),
        sa.CheckConstraint("page_number IS NULL OR page_number > 0", name="chk_chunk_page"),
        sa.CheckConstraint("slide_number IS NULL OR slide_number > 0", name="chk_chunk_slide"),
    )
    op.create_table(
        "ai_retrospectives",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("launch_id", sa.Integer(), nullable=False),
        sa.Column("compared_to_launch_id", sa.Integer(), nullable=True),
        sa.Column("generated_by_id", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["launch_id"], ["launches.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["compared_to_launch_id"], ["launches.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["generated_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.CheckConstraint("compared_to_launch_id IS NULL OR compared_to_launch_id <> launch_id", name="chk_retrospective_comparison"),
    )
    op.create_index("ix_retrospective_run_created", "ai_retrospectives", ["launch_id", "created_at"])
    op.create_index("ix_ai_retrospectives_compared_to_launch_id", "ai_retrospectives", ["compared_to_launch_id"])
    op.create_index("ix_ai_retrospectives_generated_by_id", "ai_retrospectives", ["generated_by_id"])


def downgrade():
    op.drop_table("ai_retrospectives")
    op.drop_table("document_chunks")
    # Do not drop vector: other schemas/tables may still depend on it.
