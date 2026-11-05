from alembic import op
from pgvector.sqlalchemy import VECTOR
import sqlalchemy as sa

revision = "0005_embedding_dimension"
down_revision = "0004_ai_storage"
branch_labels = None
depends_on = None


def upgrade():
    # Held until the surrounding Alembic transaction commits or rolls back:
    # writers cannot insert an incompatible vector after the preflight check.
    op.execute("LOCK TABLE document_chunks IN ACCESS EXCLUSIVE MODE")
    incompatible = op.get_bind().scalar(sa.text(
        "SELECT count(*) FROM document_chunks "
        "WHERE embedding IS NOT NULL AND vector_dims(embedding) <> 256"
    ))
    if incompatible:
        raise RuntimeError(
            f"Cannot migrate embedding to vector(256): {incompatible} incompatible rows "
            "have a dimension other than 256. No vectors were modified."
        )
    op.alter_column(
        "document_chunks", "embedding", existing_type=VECTOR(),
        type_=VECTOR(256), existing_nullable=True,
        postgresql_using="embedding::vector(256)",
    )


def downgrade():
    op.alter_column(
        "document_chunks", "embedding", existing_type=VECTOR(256),
        type_=VECTOR(), existing_nullable=True,
        postgresql_using="embedding::vector",
    )
