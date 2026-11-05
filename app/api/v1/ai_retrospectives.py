from fastapi import APIRouter, Depends, Path, Query

from core.depends import get_current_user, get_retrospective_service
from schemas.ai_retrospectives import AIRetrospectiveResponse, GenerateRetrospectiveRequest
from services.ai_retrospectives import AIRetrospectiveService


router = APIRouter(tags=['ai-retrospectives'])


@router.post('/launches/{launch_id}/ai-retrospectives', response_model=AIRetrospectiveResponse, status_code=201,
             summary='Создать ИИ-ретроспективу или сравнение запусков',
             description='Без тела или с {} — анализ одного запуска. Для сравнения укажите compared_to_launch_id того же модуля. Генерация выполняется в запросе; каждый успешный вызов сохраняет новый отчёт, не меняя ручную рефлексию.')
def generate_retrospective(
    data: GenerateRetrospectiveRequest | None = None,
    launch_id: int = Path(gt=0),
    current_user: dict = Depends(get_current_user),
    service: AIRetrospectiveService = Depends(get_retrospective_service),
):
    return service.generate(current_user['id'], launch_id, data.compared_to_launch_id if data else None)


@router.get('/launches/{launch_id}/ai-retrospectives', response_model=list[AIRetrospectiveResponse],
            summary='История ИИ-ретроспектив запуска',
            description='От новых к старым. Чтение не запускает ИИ и не пересчитывает отчёты.')
def get_retrospectives(
    launch_id: int = Path(gt=0),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    current_user: dict = Depends(get_current_user),
    service: AIRetrospectiveService = Depends(get_retrospective_service),
):
    return service.history(current_user['id'], launch_id, limit, offset)
