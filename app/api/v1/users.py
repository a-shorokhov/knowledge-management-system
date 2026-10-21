from fastapi import APIRouter, Depends, HTTPException

from schemas.users import (
    CreateUserRequest,
    UpdateUserRequest,
    UserResponse,
)
from services.users import UserService


router = APIRouter(tags=["users"])


@router.post("/users", status_code=201, response_model=UserResponse)
def create_user(
    raw_user: CreateUserRequest,
    service: UserService = Depends(),
):
    user = service.create_user(raw_user)

    if user["success"]:
        return user

    raise HTTPException(status_code=400, detail=user["message"])


@router.get("/users", response_model=dict[int, UserResponse])
def get_users(service: UserService = Depends()):
    return service.get_all_users()


@router.get("/users/{user_id}", response_model=UserResponse)
def get_user_by_id(
    user_id: int,
    service: UserService = Depends(),
):
    user = service.get_user_by_id(user_id)

    if user["success"]:
        return user

    raise HTTPException(status_code=404, detail=user["message"])


@router.patch("/users/{user_id}", response_model=UserResponse)
def update_user(
    user_id: int,
    upd_data: UpdateUserRequest,
    service: UserService = Depends(),
):
    user = service.edit_user(user_id, upd_data)

    if user["success"]:
        return user

    raise HTTPException(status_code=404, detail=user["message"])


@router.delete("/users/{user_id}")
def delete_user(
    user_id: int,
    service: UserService = Depends(),
):
    result = service.delete_user(user_id)

    if result["success"]:
        return result

    raise HTTPException(status_code=404, detail=result["message"])