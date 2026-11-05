from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from core.exceptions import AppException
from adapters.ai.yandex import AIError


def register_exception_handlers(app: FastAPI):
    @app.exception_handler(AIError)
    async def ai_exception_handler(request: Request, exc: AIError):
        return JSONResponse(status_code=exc.status_code, content={"error": {
            "ErrorCode": exc.code, "ErrorMessage": exc.message,
            "ErrorField": None, "ErrorContext": None,
        }})

    @app.exception_handler(AppException)
    async def app_exception_handler(request: Request, exc: AppException):
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": exc.detail},
            headers=exc.headers,
        )
