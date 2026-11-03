from sqlalchemy import Column, DateTime, ForeignKey, ForeignKeyConstraint, Integer, String, Text, func

from core.database import Base


class Note(Base):
    __tablename__ = "notes"
    __table_args__ = (
        ForeignKeyConstraint(["section_id", "launch_id"], ["run_sections.id", "run_sections.launch_id"], ondelete="CASCADE", name="fk_note_section_launch"),
        ForeignKeyConstraint(["material_id", "launch_id"], ["materials.id", "materials.launch_id"], ondelete="CASCADE", name="fk_note_material_launch"),
    )

    id = Column(Integer, primary_key=True)
    launch_id = Column(Integer, ForeignKey("launches.id", ondelete="CASCADE", name="fk_notes_launch"), nullable=False, index=True)
    material_id = Column(Integer, index=True)
    section_id = Column(Integer, index=True)
    author_id = Column(Integer, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    title = Column(String(255), nullable=False)
    content = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
