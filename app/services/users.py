from fastapi import Depends
from passlib.context import CryptContext

from repositories.users import UserAlreadyExistsError, UserRepository
from schemas.users import CreateUserRequest, UpdateUserRequest


pwd_context = CryptContext(schemes=["argon2"], deprecated="auto")


class UserService:
    def __init__(self, repository: UserRepository = Depends()):
        self.repository = repository

    def create_user(self, raw_user: CreateUserRequest):
        if self.repository.get_user_by_username(raw_user.username):
            return {
                "success": False,
                "message": "Пользователь уже существует",
            }

        try:
            user = self.repository.create_user(
                raw_user.username,
                raw_user.email,
                pwd_context.hash(raw_user.password),
            )
        except UserAlreadyExistsError:
            return {
                "success": False,
                "message": "Пользователь уже существует",
            }

        return {
            "success": True,
            "id": user["id"],
            "username": user["username"],
            "email": user["email"],
        }

    def get_all_users(self):
        return self.repository.get_all_users()

    def get_user_by_id(self, user_id: int):
        user = self.repository.get_user_by_id(user_id)

        if user is None:
            return {
                "success": False,
                "message": "Пользователь не найден",
            }

        return {
            "success": True,
            "id": user["id"],
            "username": user["username"],
            "email": user["email"],
        }

    def edit_user(self, user_id: int, upd_data: UpdateUserRequest):
        user = self.repository.get_user_by_id(user_id)

        if user is None:
            return {
                "success": False,
                "message": "Пользователь не найден",
            }

        upd_data = upd_data.model_dump()
        clear_dict = {}

        for k, v in upd_data.items():
            if v:
                clear_dict[k] = v

        if "password" in clear_dict:
            clear_dict["hashed_password"] = pwd_context.hash(clear_dict.pop("password"))

        user = self.repository.edit_user(user_id, clear_dict)

        if user is None:
            return {
                "success": False,
                "message": "Пользователь не найден",
            }

        return {
            "success": True,
            "id": user["id"],
            "username": user["username"],
            "email": user["email"],
        }

    def delete_user(self, user_id: int):
        user = self.repository.get_user_by_id(user_id)

        if user is None:
            return {
                "success": False,
                "message": "Пользователь не найден",
            }

        self.repository.delete_user(user_id)

        return {
            "success": True,
            "message": "Пользователь удалён",
        }
