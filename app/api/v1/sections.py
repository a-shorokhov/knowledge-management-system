from fastapi import APIRouter, Depends

from core.depends import get_current_user
from schemas.sections import CreateSectionRequest, UpdateSectionRequest, SectionResponse
from services.sections import SectionService


router = APIRouter(tags=["sections"])


@router.post("/launches/{launch_id}/sections", status_code=201, response_model=SectionResponse)
def create_section(
    launch_id: int,
    data: CreateSectionRequest,
    service: SectionService = Depends(),
    current_user: dict = Depends(get_current_user),
):
    result = service.create_section(launch_id, current_user["id"], data)

    return result


@router.get("/launches/{launch_id}/sections", response_model=dict[int, SectionResponse])
def get_sections(
    launch_id: int,
    service: SectionService = Depends(),
    current_user: dict = Depends(get_current_user),
):
    result = service.get_all_sections(launch_id, current_user["id"])

    return result["data"]


@router.get("/sections/{section_id}", response_model=SectionResponse)
def get_section_by_id(
    section_id: int,
    service: SectionService = Depends(),
    current_user: dict = Depends(get_current_user),
):
    result = service.get_section_by_id(section_id, current_user["id"])

    return result


@router.patch("/sections/{section_id}", response_model=SectionResponse)
def update_section(
    section_id: int,
    data: UpdateSectionRequest,
    service: SectionService = Depends(),
    current_user: dict = Depends(get_current_user),
):
    result = service.edit_section(section_id, current_user["id"], data)

    return result


@router.delete("/sections/{section_id}")
def delete_section(
    section_id: int,
    service: SectionService = Depends(),
    current_user: dict = Depends(get_current_user),
):
    result = service.delete_section(section_id, current_user["id"])

    return result
