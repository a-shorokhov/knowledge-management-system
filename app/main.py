from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from api.v1 import users_router, modules_router, launches_router, sections_router, notes_router, materials_router, stored_files_router
from api.v1 import launch_designs_router, launch_reflections_router
from core.database import engine
from core.config import settings
from core.handlers import register_exception_handlers


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        yield
    finally:
        engine.dispose()


app = FastAPI(lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_methods=["*"],
    allow_headers=["Content-Type", "Authorization"],
    allow_credentials=False,
)
register_exception_handlers(app)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    errors = exc.errors()
    for error in errors:
        location = error.get("loc", ())
        if "password" in location or tuple(location) == ("body",):
            error.pop("input", None)
    return JSONResponse(status_code=422, content={"detail": jsonable_encoder(errors)})


app.include_router(users_router)
app.include_router(modules_router)
app.include_router(launches_router)
app.include_router(notes_router)
app.include_router(materials_router)
app.include_router(sections_router)
app.include_router(stored_files_router)

app.include_router(launch_designs_router)

app.include_router(launch_reflections_router)
