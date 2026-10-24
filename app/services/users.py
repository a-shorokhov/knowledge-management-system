from fastapi import Depends

from core.security import hash_password, verify_password, create_access_token

from repositories.users import EmailAlreadyExistsError, UserAlreadyExistsError, UserRepository
from schemas.users import CreateUserRequest, UpdateUserRequest


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
                hash_password(raw_user.password),
            )
        except EmailAlreadyExistsError:
            return {
                "success": False,
                "message": "Email уже используется",
                "status_code": 400,
            }
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

    def login(self, username: str, password: str):
        user = self.repository.get_user_for_auth(username)

        if user is None or not verify_password(
                password,
                user.hashed_password,
        ):
            return {
                "success": False,
                "message": "Неверный логин или пароль",
            }

        token = create_access_token(
            {
                "username": user.username,
                "user_id": user.id,
            }
        )

        return {
            "success": True,
            "access_token": token,
            "token_type": "bearer",
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
            clear_dict["hashed_password"] = hash_password(clear_dict.pop("password"))

        try:
            user = self.repository.edit_user(user_id, clear_dict)
        except EmailAlreadyExistsError:
            return {
                "success": False,
                "message": "Email уже используется",
                "status_code": 400,
            }

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
