from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from core.depends import get_current_user
from models.enums import MaterialKind
from schemas.materials import CopyMaterialRequest, MaterialResponse, MaterialUpload, UpdateMaterialRequest
from schemas.stored_files import DownloadResponse
from services.materials import MaterialService
from services.stored_files import StoredFileService


router = APIRouter(tags=["materials"])


@router.post("/launches/{launch_id}/materials", status_code=201, response_model=MaterialResponse)
def create_material(
    launch_id: int,
    title: str = Form(min_length=1, max_length=255),
    description: str | None = Form(default=None),
    file: UploadFile = File(),
    section_id: int | None = Form(default=None, ge=1),
    kind: MaterialKind = Form(default=MaterialKind.other),
    position: int = Form(default=0, ge=0),
    service: MaterialService = Depends(),
    current_user: dict = Depends(get_current_user),
):
    upload = MaterialUpload(file.file, file.filename, file.content_type, file.size)
    result = service.create_material(launch_id, current_user["id"], title, description, upload, section_id, kind, position)

    if result["success"]:
        return result

    raise HTTPException(status_code=result.get("status_code", 404), detail=result["message"])


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


@router.get("/materials/{material_id}", response_model=MaterialResponse)
def get_material_by_id(
    material_id: int,
    service: MaterialService = Depends(),
    current_user: dict = Depends(get_current_user),
):
    result = service.get_material_by_id(material_id, current_user["id"])

    if result["success"]:
        return result

    raise HTTPException(status_code=result.get("status_code", 404), detail=result["message"])


@router.patch("/materials/{material_id}", response_model=MaterialResponse)
def update_material(
    material_id: int,
    data: UpdateMaterialRequest,
    service: MaterialService = Depends(),
    current_user: dict = Depends(get_current_user),
):
    result = service.edit_material(material_id, current_user["id"], data)

    if result["success"]:
        return result

    raise HTTPException(status_code=result.get("status_code", 404), detail=result["message"])


@router.post("/materials/{material_id}/copy", status_code=201, response_model=MaterialResponse)
def copy_material(
    material_id: int,
    data: CopyMaterialRequest,
    service: MaterialService = Depends(),
    current_user: dict = Depends(get_current_user),
):
    result = service.copy_material(material_id, current_user["id"], data)

    if result["success"]:
        return result

    raise HTTPException(status_code=result.get("status_code", 404), detail=result["message"])


@router.put("/materials/{material_id}/file", response_model=MaterialResponse)
def replace_file(
    material_id: int,
    file: UploadFile = File(),
    service: MaterialService = Depends(),
    current_user: dict = Depends(get_current_user),
):
    upload = MaterialUpload(file.file, file.filename, file.content_type, file.size)
    result = service.replace_file(material_id, current_user["id"], upload)

    if result["success"]:
        return result

    raise HTTPException(status_code=result.get("status_code", 404), detail=result["message"])


@router.get("/materials/{material_id}/download", response_model=DownloadResponse)
def download_material(
    material_id: int,
    service: StoredFileService = Depends(),
    current_user: dict = Depends(get_current_user),
):
    result = service.get_material_download_url(material_id, current_user["id"])

    if result["success"]:
        return result

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
