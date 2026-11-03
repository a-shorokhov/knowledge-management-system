from sqlalchemy import CheckConstraint, Column, ForeignKey, Index, Integer, String, Text, UniqueConstraint

from core.database import Base


class RunSection(Base):
    __tablename__ = "run_sections"
    __table_args__ = (
        Index("ix_section_run_position", "launch_id", "position"),
        UniqueConstraint("id", "launch_id", name="uq_section_id_run"),
        CheckConstraint("position >= 0", name="chk_section_position"),
    )

    id = Column(Integer, primary_key=True)
    launch_id = Column(Integer, ForeignKey("launches.id", ondelete="CASCADE", name="fk_sections_launch"), nullable=False)
    title = Column(String(255), nullable=False)
    description = Column(Text)
    position = Column(Integer, nullable=False, server_default="0")
