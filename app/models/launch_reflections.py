from sqlalchemy import Column, DateTime, ForeignKey, Integer, Text, func

from core.database import Base


class LaunchReflection(Base):
    __tablename__ = "launch_reflections"

    launch_id = Column(Integer, ForeignKey("launches.id", ondelete="CASCADE"), primary_key=True)
    what_went_well = Column(Text)
    recurring_problems = Column(Text)
    materials_to_update = Column(Text)
    decisions_to_keep = Column(Text)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
