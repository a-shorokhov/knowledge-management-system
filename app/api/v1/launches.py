from fastapi import APIRouter, Depends, HTTPException

from core.depends import get_current_user
from schemas.launches import CreateLaunchRequest, UpdateLaunchRequest, LaunchResponse
from services.launches import LaunchService


router = APIRouter(tags=["launches"])


@router.post("/modules/{module_id}/launches", status_code=201, response_model=LaunchResponse)
def create_launch(
    module_id: int,
    data: CreateLaunchRequest,
    service: LaunchService = Depends(),
    current_user: dict = Depends(get_current_user),
):
    launch = service.create_launch(module_id, current_user["id"], data)

    if launch["success"]:
        return launch

    raise HTTPException(status_code=launch.get("status_code", 404), detail=launch["message"])


@router.get("/modules/{module_id}/launches", response_model=dict[int, LaunchResponse])
def get_launches(
    module_id: int,
    service: LaunchService = Depends(),
    current_user: dict = Depends(get_current_user),
):
    result = service.get_all_launches(module_id, current_user["id"])

    if result["success"]:
        return result["data"]

    raise HTTPException(status_code=result.get("status_code", 404), detail=result["message"])


@router.get("/launches/{launch_id}", response_model=LaunchResponse)
def get_launch_by_id(
    launch_id: int,
    service: LaunchService = Depends(),
    current_user: dict = Depends(get_current_user),
):
    launch = service.get_launch_by_id(launch_id, current_user["id"])

    if launch["success"]:
        return launch

    raise HTTPException(status_code=launch.get("status_code", 404), detail=launch["message"])


@router.patch("/launches/{launch_id}", response_model=LaunchResponse)
def update_launch(
    launch_id: int,
    data: UpdateLaunchRequest,
    service: LaunchService = Depends(),
    current_user: dict = Depends(get_current_user),
):
    launch = service.edit_launch(launch_id, current_user["id"], data)

    if launch["success"]:
        return launch

    raise HTTPException(status_code=launch.get("status_code", 404), detail=launch["message"])


@router.delete("/launches/{launch_id}")
def delete_launch(
    launch_id: int,
    service: LaunchService = Depends(),
    current_user: dict = Depends(get_current_user),
):
    result = service.delete_launch(launch_id, current_user["id"])

    if result["success"]:
        return result

    raise HTTPException(status_code=result.get("status_code", 404), detail=result["message"])