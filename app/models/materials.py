from sqlalchemy import CheckConstraint, Column, DateTime, Enum, ForeignKey, ForeignKeyConstraint, Index, Integer, String, Text, UniqueConstraint, func

from core.database import Base
from models.enums import MaterialKind


class Material(Base):
    __tablename__ = "materials"
    __table_args__ = (
        Index("ix_material_run_position", "launch_id", "position"),
        UniqueConstraint("id", "launch_id", name="uq_material_id_run"),
        ForeignKeyConstraint(["section_id", "launch_id"], ["run_sections.id", "run_sections.launch_id"], ondelete="CASCADE", name="fk_material_section_launch"),
        CheckConstraint("position >= 0", name="chk_material_position"),
        CheckConstraint("copied_from_material_id IS NULL OR copied_from_material_id <> id", name="chk_material_copy_source"),
    )

    id = Column(Integer, primary_key=True)
    launch_id = Column(Integer, ForeignKey("launches.id", ondelete="CASCADE", name="fk_materials_launch"), nullable=False)
    section_id = Column(Integer, index=True)
    stored_file_id = Column(Integer, ForeignKey("stored_files.id", ondelete="RESTRICT"), nullable=False, index=True)
    title = Column(String(255), nullable=False)
    description = Column(Text)
    kind = Column(Enum(MaterialKind, name="material_kind"), nullable=False, server_default="other")
    position = Column(Integer, nullable=False, server_default="0")
    copied_from_material_id = Column(Integer, ForeignKey("materials.id", ondelete="SET NULL"))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
