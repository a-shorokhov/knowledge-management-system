from fastapi import APIRouter, Depends, HTTPException

from core.depends import get_current_user
from schemas.stored_files import DownloadResponse, StoredFileResponse
from services.stored_files import StoredFileService


router = APIRouter(tags=["stored-files"])


@router.get("/stored-files", response_model=dict[int, StoredFileResponse])
def get_files(
    service: StoredFileService = Depends(),
    current_user: dict = Depends(get_current_user),
):
    result = service.get_all_files(current_user["id"])

    if result["success"]:
        return result["data"]

    raise HTTPException(status_code=result.get("status_code", 404), detail=result["message"])


@router.get("/stored-files/{file_id}", response_model=StoredFileResponse)
def get_file_by_id(
    file_id: int,
    service: StoredFileService = Depends(),
    current_user: dict = Depends(get_current_user),
):
    result = service.get_file_by_id(file_id, current_user["id"])

    if result["success"]:
        return result

    raise HTTPException(status_code=result.get("status_code", 404), detail=result["message"])


@router.get("/stored-files/{file_id}/download", response_model=DownloadResponse)
def download_file(
    file_id: int,
    service: StoredFileService = Depends(),
    current_user: dict = Depends(get_current_user),
):
    result = service.get_download_url(file_id, current_user["id"])

    if result["success"]:
        return result

    raise HTTPException(status_code=result.get("status_code", 404), detail=result["message"])


@router.delete("/stored-files/{file_id}")
def delete_file(
    file_id: int,
    service: StoredFileService = Depends(),
    current_user: dict = Depends(get_current_user),
):
    result = service.delete_file(file_id, current_user["id"])

    if result["success"]:
        return result

    raise HTTPException(status_code=result.get("status_code", 404), detail=result["message"])
