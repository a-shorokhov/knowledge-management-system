from sqlalchemy import Column, ForeignKey, Integer, String, Text

from core.database import Base


class Module(Base):
    __tablename__ = "modules"

    id = Column(Integer, primary_key=True)
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    title = Column(String(255), nullable=False)
    description = Column(Text)