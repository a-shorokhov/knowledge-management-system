from sqlalchemy import Column, ForeignKey, Integer, String, Text

from core.database import Base


class Launch(Base):
    __tablename__ = "launches"

    id = Column(Integer, primary_key=True)
    module_id = Column(
        Integer,
        ForeignKey("modules.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    year = Column(Integer, nullable=False)
    title = Column(String(255))
    description = Column(Text)