from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from core.depends import get_current_user
from schemas.materials import MaterialResponse
from services.materials import MaterialService


router = APIRouter(tags=["materials"])


@router.post("/launches/{launch_id}/materials", status_code=201, response_model=MaterialResponse)
def create_material(
    launch_id: int,
    title: str = Form(min_length=1, max_length=255),
    description: str | None = Form(default=None),
    file: UploadFile = File(),
    service: MaterialService = Depends(),
    current_user: dict = Depends(get_current_user),
):
    material = service.create_material(launch_id, current_user["id"], title, description, file)

    if material["success"]:
        return material

    raise HTTPException(status_code=material.get("status_code", 404), detail=material["message"])


@router.get("/launches/{launch_id}/materials", response_model=dict[int, MaterialResponse])
def get_materials(
    launch_id: int,
    service: MaterialService = Depends(),
    current_user: dict = Depends(get_current_user),
):
    result = service.get_all_materials(launch_id, current_user["id"])

    if result["success"]:
        return result["data"]

    raise HTTPException(status_code=result.get("status_code", 404), detail=result["message"])


@router.delete("/materials/{material_id}")
def delete_material(
    material_id: int,
    service: MaterialService = Depends(),
    current_user: dict = Depends(get_current_user),
):
    result = service.delete_material(material_id, current_user["id"])

    if result["success"]:
        return result

    raise HTTPException(status_code=result.get("status_code", 404), detail=result["message"])