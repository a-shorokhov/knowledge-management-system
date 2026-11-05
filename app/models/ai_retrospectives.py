from sqlalchemy import CheckConstraint, Column, DateTime, ForeignKey, Index, Integer, Text, func

from core.database import Base


class AIRetrospective(Base):
    __tablename__ = "ai_retrospectives"
    __table_args__ = (
        Index("ix_retrospective_run_created", "launch_id", "created_at"),
        CheckConstraint("compared_to_launch_id IS NULL OR compared_to_launch_id <> launch_id", name="chk_retrospective_comparison"),
    )

    id = Column(Integer, primary_key=True)
    launch_id = Column(Integer, ForeignKey("launches.id", ondelete="CASCADE"), nullable=False)
    compared_to_launch_id = Column(Integer, ForeignKey("launches.id", ondelete="SET NULL"), index=True)
    generated_by_id = Column(Integer, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    content = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
