from sqlalchemy import Column, Integer, String, Text, UniqueConstraint

from core.database import Base


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("username", name="uq_users_username"),
        UniqueConstraint("email", name="uq_users_email"),
    )

    id = Column(Integer, primary_key=True)
    username = Column(String(32), nullable=False)
    email = Column(String(320), nullable=False)
    hashed_password = Column(Text, nullable=False)
