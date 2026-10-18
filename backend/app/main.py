from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.api.routes.auth import router as auth_router
from app.core.config import get_auth_settings
from app.core.security import dummy_password_hash


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    get_auth_settings()  # Fail closed if the signing secret is absent or weak.
    dummy_password_hash()
    yield


app = FastAPI(
    title="Red Antiextorsi?n Preventiva API", version="0.1.0", lifespan=lifespan,
)
app.include_router(auth_router)


@app.exception_handler(RequestValidationError)
async def invalid_request(request: Request, exc: RequestValidationError) -> JSONResponse:
    # Default validation errors can echo passwords or other raw request inputs.
    return JSONResponse(status_code=422, content={"detail": "Invalid request data"})


@app.middleware("http")
async def prevent_auth_caching(
    request: Request, call_next: Callable[[Request], Awaitable[Response]],
) -> Response:
    response = await call_next(request)
    if request.url.path.startswith("/api/v1/auth/"):
        response.headers["Cache-Control"] = "no-store"
        response.headers["Pragma"] = "no-cache"
    return response


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
