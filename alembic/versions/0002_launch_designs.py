from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0002_launch_designs"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("launches", sa.Column("starts_on", sa.Date(), nullable=True))
    op.add_column("launches", sa.Column("ends_on", sa.Date(), nullable=True))
    op.add_column("launches", sa.Column("participant_count", sa.Integer(), nullable=True))
    op.add_column("launches", sa.Column("changes_summary", sa.Text(), nullable=True))
    op.add_column("launches", sa.Column("changes_reason", sa.Text(), nullable=True))
    op.alter_column("launches", "description", server_default="")
    op.create_check_constraint("chk_launch_participant_count", "launches", "participant_count IS NULL OR participant_count >= 0")
    op.create_check_constraint("chk_launch_dates", "launches", "starts_on IS NULL OR ends_on IS NULL OR ends_on >= starts_on")
    op.create_table(
        "launch_designs",
        sa.Column("launch_id", sa.Integer(), nullable=False),
        sa.Column("template_version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("data", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("launch_id"),
        sa.ForeignKeyConstraint(["launch_id"], ["launches.id"], ondelete="CASCADE"),
        sa.CheckConstraint("template_version > 0", name="chk_design_template_version"),
        sa.CheckConstraint("jsonb_typeof(data) = 'object'", name="chk_design_data_object"),
    )
    op.execute(sa.text("INSERT INTO launch_designs (launch_id) SELECT id FROM launches"))


def downgrade():
    op.drop_table("launch_designs")
    op.drop_constraint("chk_launch_dates", "launches", type_="check")
    op.drop_constraint("chk_launch_participant_count", "launches", type_="check")
    op.alter_column("launches", "description", server_default=None)
    for name in ("changes_reason", "changes_summary", "participant_count", "ends_on", "starts_on"):
        op.drop_column("launches", name)
