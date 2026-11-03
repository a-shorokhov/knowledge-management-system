from fastapi import APIRouter, Depends

from core.depends import get_current_user
from schemas.modules import CreateModuleRequest, UpdateModuleRequest, ModuleResponse
from services.modules import ModuleService


router = APIRouter(tags=["modules"])


@router.post("/modules", status_code=201, response_model=ModuleResponse)
def create_module(
    data: CreateModuleRequest,
    service: ModuleService = Depends(),
    current_user: dict = Depends(get_current_user),
):
    result = service.create_module(current_user["id"], data)

    return result


@router.get("/modules", response_model=dict[int, ModuleResponse])
def get_modules(
    service: ModuleService = Depends(),
    current_user: dict = Depends(get_current_user),
):
    result = service.get_all_modules(current_user["id"])

    return result["data"]


@router.get("/modules/{module_id}", response_model=ModuleResponse)
def get_module_by_id(
    module_id: int,
    service: ModuleService = Depends(),
    current_user: dict = Depends(get_current_user),
):
    result = service.get_module_by_id(module_id, current_user["id"])

    return result


@router.patch("/modules/{module_id}", response_model=ModuleResponse)
def update_module(
    module_id: int,
    data: UpdateModuleRequest,
    service: ModuleService = Depends(),
    current_user: dict = Depends(get_current_user),
):
    result = service.edit_module(module_id, current_user["id"], data)

    return result


@router.delete("/modules/{module_id}")
def delete_module(
    module_id: int,
    service: ModuleService = Depends(),
    current_user: dict = Depends(get_current_user),
):
    result = service.delete_module(module_id, current_user["id"])

    return result
