from fastapi import Depends
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from database import get_db
from models import User


class UserAlreadyExistsError(Exception):
    pass


class UserRepository:
    def __init__(self, db: Session = Depends(get_db)):
        self.db = db

    @staticmethod
    def _to_dict(user: User):
        return {
            "id": user.id,
            "username": user.username,
            "email": user.email,
        }

    def _commit(self):
        try:
            self.db.commit()
        except SQLAlchemyError:
            self.db.rollback()
            raise

    def create_user(self, username: str, email: str, hashed_password: str):
        user = User(username=username, email=email, hashed_password=hashed_password)
        self.db.add(user)
        try:
            self._commit()
        except IntegrityError as exc:
            constraint = getattr(getattr(exc.orig, "diag", None), "constraint_name", None)
            if constraint == "uq_users_username":
                raise UserAlreadyExistsError from None
            raise
        self.db.refresh(user)
        return self._to_dict(user)

    def get_all_users(self):
        users = self.db.scalars(select(User).order_by(User.id)).all()
        return {user.id: self._to_dict(user) for user in users}

    def get_user_by_id(self, user_id: int):
        user = self.db.get(User, user_id)
        return self._to_dict(user) if user is not None else None

    def get_user_by_username(self, username: str):
        user = self.db.scalar(select(User).where(User.username == username))
        return self._to_dict(user) if user is not None else None

    def edit_user(self, user_id: int, upd_data: dict):
        user = self.db.get(User, user_id)
        if user is None:
            return None
        for key, value in upd_data.items():
            setattr(user, key, value)
        self._commit()
        self.db.refresh(user)
        return self._to_dict(user)

    def delete_user(self, user_id: int):
        user = self.db.get(User, user_id)
        if user is not None:
            self.db.delete(user)
            self._commit()
