from sqlalchemy import Column, Integer, String, UniqueConstraint

from core.database import Base


class User(Base):
    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("username", name="uq_users_username"),)

    id = Column(Integer, primary_key=True)
    username = Column(String(32), nullable=False)
    email = Column(String, nullable=False)
    hashed_password = Column(String, nullable=False)
