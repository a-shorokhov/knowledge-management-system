from fastapi import APIRouter, Depends
from fastapi.security import OAuth2PasswordRequestForm
from core.depends import get_current_user, require_user_owner

from schemas.users import (
    CreateUserRequest,
    UpdateUserRequest,
    UserResponse,
    Token,
)
from services.users import UserService


router = APIRouter(tags=["users"])


@router.post("/auth/register", status_code=201, response_model=UserResponse)
def create_user(
    raw_user: CreateUserRequest,
    service: UserService = Depends(),
):
    user = service.create_user(raw_user)

    return user

@router.post("/auth/login", response_model=Token)
def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    service: UserService = Depends(),
):
    result = service.login(
        form_data.username,
        form_data.password,
    )

    return result

@router.get("/auth/me", response_model=UserResponse)
def me(current_user: dict = Depends(get_current_user)):
    return current_user

@router.get("/users", response_model=dict[int, UserResponse])
def get_users(
        service: UserService = Depends(),
        current_user: dict = Depends(get_current_user),
):
    return service.get_all_users()


@router.get("/users/{user_id}", response_model=UserResponse)
def get_user_by_id(
    user_id: int,
    service: UserService = Depends(),
    current_user: dict = Depends(get_current_user),
):
    user = service.get_user_by_id(user_id)

    return user


@router.patch("/users/{user_id}", response_model=UserResponse)
def update_user(
    user_id: int,
    upd_data: UpdateUserRequest,
    service: UserService = Depends(),
    current_user: dict = Depends(require_user_owner),
):
    user = service.edit_user(user_id, upd_data)

    return user


@router.delete("/users/{user_id}")
def delete_user(
    user_id: int,
    service: UserService = Depends(),
    current_user: dict = Depends(require_user_owner),
):
    result = service.delete_user(user_id)

    return result