from fastapi import APIRouter, Depends

from core.depends import get_current_user
from schemas.launch_reflections import LaunchReflectionResponse, ReplaceLaunchReflectionRequest
from services.launch_reflections import LaunchReflectionService


router = APIRouter(tags=["launch-reflections"])


@router.get("/launches/{launch_id}/reflection", response_model=LaunchReflectionResponse,
            description="Ручная итоговая рефлексия владельца запуска. Если запись отсутствует, все поля заполнения и временные метки равны null. GET не изменяет БД.")
def get_launch_reflection(
    launch_id: int,
    service: LaunchReflectionService = Depends(),
    current_user: dict = Depends(get_current_user),
):
    return service.get_reflection(launch_id, current_user["id"])


@router.put("/launches/{launch_id}/reflection", response_model=LaunchReflectionResponse,
            description="Создаёт или полностью заменяет ручную рефлексию. Непереданные поля очищаются до null. Пустой объект очищает всё заполнение. Доступ только владельцу, независимо от статуса запуска.")
def replace_launch_reflection(
    launch_id: int,
    data: ReplaceLaunchReflectionRequest,
    service: LaunchReflectionService = Depends(),
    current_user: dict = Depends(get_current_user),
):
    return service.replace_reflection(launch_id, current_user["id"], data)
