from pgvector.sqlalchemy import VECTOR
from sqlalchemy import CheckConstraint, Column, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func

from core.database import Base


class DocumentChunk(Base):
    __tablename__ = "document_chunks"
    __table_args__ = (
        UniqueConstraint("stored_file_id", "chunk_index", name="uq_chunk_file_index"),
        CheckConstraint("chunk_index >= 0", name="chk_chunk_index"),
        CheckConstraint("page_number IS NULL OR page_number > 0", name="chk_chunk_page"),
        CheckConstraint("slide_number IS NULL OR slide_number > 0", name="chk_chunk_slide"),
    )

    id = Column(Integer, primary_key=True)
    stored_file_id = Column(Integer, ForeignKey("stored_files.id", ondelete="CASCADE"), nullable=False)
    chunk_index = Column(Integer, nullable=False)
    content = Column(Text, nullable=False)
    page_number = Column(Integer)
    slide_number = Column(Integer)
    sheet_name = Column(String(255))
    cell_range = Column(String(64))
    embedding = Column(VECTOR())
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
