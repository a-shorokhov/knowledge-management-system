from fastapi import APIRouter, Depends

from core.depends import get_current_user, get_rag_service
from schemas.ai import AskRequest, AskResponse
from services.rag import RagService


router = APIRouter(prefix='/ai', tags=['ai'])


@router.post('/ask', response_model=AskResponse)
def ask(data: AskRequest, service: RagService = Depends(get_rag_service),
        current_user: dict = Depends(get_current_user)):
    return service.ask(current_user['id'], data.module_id, data.launch_id, data.question)
