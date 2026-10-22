from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from api.v1 import users_router
from database import Base, engine
from models import User


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    try:
        yield
    finally:
        engine.dispose()


app = FastAPI(lifespan=lifespan)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    errors = exc.errors()
    for error in errors:
        location = error.get("loc", ())
        if "password" in location or tuple(location) == ("body",):
            error.pop("input", None)
    return JSONResponse(status_code=422, content={"detail": jsonable_encoder(errors)})


app.include_router(users_router)
