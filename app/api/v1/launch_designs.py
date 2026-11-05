from fastapi import APIRouter, Depends

from core.depends import get_current_user
from schemas.launch_designs import LaunchDesignResponse, ReplaceLaunchDesignRequest
from services.launch_designs import LaunchDesignService


router = APIRouter(tags=["launch-designs"])


@router.get("/launch-design/template", summary="Фиксированная структура формы версии 1")
def get_design_template(
    service: LaunchDesignService = Depends(),
    current_user: dict = Depends(get_current_user),
):
    return service.get_template()


@router.get("/launches/{launch_id}/design", response_model=LaunchDesignResponse, response_model_exclude_unset=True,
            description="Только владелец запуска. При отсутствии записи возвращает пустую форму версии 1 с null в датах создания и обновления; БД не изменяется.")
def get_launch_design(
    launch_id: int,
    service: LaunchDesignService = Depends(),
    current_user: dict = Depends(get_current_user),
):
    return service.get_design(launch_id, current_user["id"])


@router.put("/launches/{launch_id}/design", response_model=LaunchDesignResponse, response_model_exclude_unset=True,
            description="Создаёт или полностью заменяет заполнение формы версии 1. Непереданные поля не сохраняются от старого документа. data={} очищает форму. Частичное заполнение допустимо; это PUT, а не PATCH.")
def replace_launch_design(
    launch_id: int,
    data: ReplaceLaunchDesignRequest,
    service: LaunchDesignService = Depends(),
    current_user: dict = Depends(get_current_user),
):
    return service.replace_design(launch_id, current_user["id"], data)
