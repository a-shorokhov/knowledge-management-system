from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text, func

from core.database import Base


class Module(Base):
    __tablename__ = "modules"

    id = Column(Integer, primary_key=True)
    owner_id = Column(Integer, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
