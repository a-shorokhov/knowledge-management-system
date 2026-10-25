from sqlalchemy import Column, Integer, String, Text

from core.database import Base


class Template(Base):
    __tablename__ = "templates"

    id = Column(Integer, primary_key=True)
    title = Column(String(255), nullable=False)
    description = Column(Text)
    original_filename = Column(String(255), nullable=False)
    storage_key = Column(Text, nullable=False)