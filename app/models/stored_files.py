from sqlalchemy import BigInteger, Boolean, CheckConstraint, Column, DateTime, Enum, ForeignKey, Integer, String, Text, UniqueConstraint, false, func

from core.database import Base
from models.enums import FileIndexStatus


class StoredFile(Base):
    __tablename__ = "stored_files"
    __table_args__ = (
        UniqueConstraint("bucket", "storage_key", name="uq_stored_file_object"),
        CheckConstraint("size_bytes >= 0", name="chk_file_size"),
    )

    id = Column(Integer, primary_key=True)
    bucket = Column(String(255), nullable=False)
    storage_key = Column(Text, nullable=False)
    original_filename = Column(String(255), nullable=False)
    mime_type = Column(String(255), nullable=False)
    size_bytes = Column(BigInteger, nullable=False)
    uploaded_by_id = Column(Integer, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    deletion_pending = Column(Boolean, nullable=False, server_default=false())
    indexing_status = Column(Enum(FileIndexStatus, name="file_index_status"), nullable=False, server_default="pending")
    indexing_error_code = Column(String(100))
    indexed_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
