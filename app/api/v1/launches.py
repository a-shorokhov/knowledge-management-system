from fastapi import APIRouter, Depends

from core.depends import get_current_user
from schemas.launches import CreateLaunchRequest, UpdateLaunchRequest, LaunchResponse, PreviousLaunchContextResponse
from services.launches import LaunchService


router = APIRouter(tags=["launches"])


@router.post("/modules/{module_id}/launches", status_code=201, response_model=LaunchResponse)
def create_launch(
    module_id: int,
    data: CreateLaunchRequest,
    service: LaunchService = Depends(),
    current_user: dict = Depends(get_current_user),
):
    result = service.create_launch(module_id, current_user["id"], data)

    return result


@router.get("/modules/{module_id}/launches", response_model=dict[int, LaunchResponse])
def get_launches(
    module_id: int,
    service: LaunchService = Depends(),
    current_user: dict = Depends(get_current_user),
):
    result = service.get_all_launches(module_id, current_user["id"])

    return result["data"]


@router.get("/launches/{launch_id}", response_model=LaunchResponse)
def get_launch_by_id(
    launch_id: int,
    service: LaunchService = Depends(),
    current_user: dict = Depends(get_current_user),
):
    result = service.get_launch_by_id(launch_id, current_user["id"])

    return result


@router.patch("/launches/{launch_id}", response_model=LaunchResponse)
def update_launch(
    launch_id: int,
    data: UpdateLaunchRequest,
    service: LaunchService = Depends(),
    current_user: dict = Depends(get_current_user),
):
    result = service.edit_launch(launch_id, current_user["id"], data)

    return result


@router.delete("/launches/{launch_id}")
def delete_launch(
    launch_id: int,
    service: LaunchService = Depends(),
    current_user: dict = Depends(get_current_user),
):
    result = service.delete_launch(launch_id, current_user["id"])

    return result


@router.post("/launches/{launch_id}/copy", status_code=201, response_model=LaunchResponse)
def copy_launch(
    launch_id: int,
    data: CreateLaunchRequest,
    service: LaunchService = Depends(),
    current_user: dict = Depends(get_current_user),
):
    result = service.copy_launch(launch_id, current_user["id"], data)

    return result


@router.get("/launches/{launch_id}/previous-context", response_model=PreviousLaunchContextResponse,
            response_model_exclude_unset=True,
            description="Актуальный контекст явно выбранного источника copied_from_launch_id: запуск, форма, заметки и ручная рефлексия. Источник должен быть доступен владельцу и относиться к тому же модулю. Если ссылки нет или источник недоступен, возвращает source_launch/design/reflection=null и notes={}. GET не изменяет БД и не ищет последний запуск.")
def get_previous_context(
    launch_id: int,
    service: LaunchService = Depends(),
    current_user: dict = Depends(get_current_user),
):
    return service.get_previous_context(launch_id, current_user["id"])
