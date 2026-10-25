from fastapi import APIRouter, Depends, HTTPException

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
    module = service.create_module(current_user["id"], data)

    if module["success"]:
        return module

    raise HTTPException(status_code=module.get("status_code", 404), detail=module["message"])


@router.get("/modules", response_model=dict[int, ModuleResponse])
def get_modules(
    service: ModuleService = Depends(),
    current_user: dict = Depends(get_current_user),
):
    return service.get_all_modules(current_user["id"])


@router.get("/modules/{module_id}", response_model=ModuleResponse)
def get_module_by_id(
    module_id: int,
    service: ModuleService = Depends(),
    current_user: dict = Depends(get_current_user),
):
    module = service.get_module_by_id(module_id, current_user["id"])

    if module["success"]:
        return module

    raise HTTPException(status_code=module.get("status_code", 404), detail=module["message"])


@router.patch("/modules/{module_id}", response_model=ModuleResponse)
def update_module(
    module_id: int,
    data: UpdateModuleRequest,
    service: ModuleService = Depends(),
    current_user: dict = Depends(get_current_user),
):
    module = service.edit_module(module_id, current_user["id"], data)

    if module["success"]:
        return module

    raise HTTPException(status_code=module.get("status_code", 404), detail=module["message"])


@router.delete("/modules/{module_id}")
def delete_module(
    module_id: int,
    service: ModuleService = Depends(),
    current_user: dict = Depends(get_current_user),
):
    result = service.delete_module(module_id, current_user["id"])

    if result["success"]:
        return result

    raise HTTPException(status_code=result.get("status_code", 404), detail=result["message"])