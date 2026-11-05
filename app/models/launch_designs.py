from sqlalchemy import CheckConstraint, Column, DateTime, ForeignKey, Integer, JSON, func, text
from sqlalchemy.dialects.postgresql import JSONB

from core.database import Base


class LaunchDesign(Base):
    __tablename__ = "launch_designs"
    __table_args__ = (
        CheckConstraint("template_version > 0", name="chk_design_template_version"),
        CheckConstraint("jsonb_typeof(data) = 'object'", name="chk_design_data_object").ddl_if(dialect="postgresql"),
    )

    launch_id = Column(Integer, ForeignKey("launches.id", ondelete="CASCADE"), primary_key=True)
    template_version = Column(Integer, nullable=False, server_default="1")
    data = Column(JSONB().with_variant(JSON(), "sqlite"), nullable=False, default=dict, server_default=text("'{}'"))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
