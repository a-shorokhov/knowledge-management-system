from typing import Optional

from pydantic import BaseModel, EmailStr, Field, field_validator


def validate_password(value: str) -> str:
    if len(value) < 8:
        raise ValueError("Пароль должен содержать минимум 8 символов")

    if not any(char.isdigit() for char in value):
        raise ValueError("Пароль должен содержать цифры")

    if not any(char.isalpha() for char in value):
        raise ValueError("Пароль должен содержать буквы")

    if not any(char.isupper() for char in value):
        raise ValueError("Пароль должен содержать заглавные буквы")

    return value


class CreateUserRequest(BaseModel):
    username: str = Field(min_length=4, max_length=32)
    email: EmailStr
    password: str

    @field_validator("password")
    @classmethod
    def validate_password(cls, value):
        return validate_password(value)


class UpdateUserRequest(BaseModel):
    email: Optional[EmailStr] = None
    password: Optional[str] = None

    @field_validator("password")
    @classmethod
    def validate_password(cls, value):
        if value is None:
            return value

        return validate_password(value)


class UserResponse(BaseModel):
    id: int
    username: str
    email: EmailStr

class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"