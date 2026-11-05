from sqlalchemy import CheckConstraint, Column, Date, DateTime, Enum, ForeignKey, Index, Integer, String, Text, func

from core.database import Base
from models.enums import RunStatus


class Launch(Base):
    __tablename__ = "launches"
    __table_args__ = (
        Index("ix_run_module_year", "module_id", "year"),
        CheckConstraint("year > 0", name="chk_run_year"),
        CheckConstraint("participant_count IS NULL OR participant_count >= 0", name="chk_launch_participant_count"),
        CheckConstraint("starts_on IS NULL OR ends_on IS NULL OR ends_on >= starts_on", name="chk_launch_dates"),
        CheckConstraint("copied_from_launch_id IS NULL OR copied_from_launch_id <> id", name="chk_run_copy_source"),
    )

    id = Column(Integer, primary_key=True)
    module_id = Column(Integer, ForeignKey("modules.id", ondelete="CASCADE", name="fk_launch_module"), nullable=False)
    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=False, server_default="")
    year = Column(Integer, nullable=False)
    semester = Column(String(32), nullable=False)
    status = Column(Enum(RunStatus, name="run_status"), nullable=False, server_default="draft")
    copied_from_launch_id = Column(Integer, ForeignKey("launches.id", ondelete="SET NULL"))
    starts_on = Column(Date)
    ends_on = Column(Date)
    participant_count = Column(Integer)
    changes_summary = Column(Text)
    changes_reason = Column(Text)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
