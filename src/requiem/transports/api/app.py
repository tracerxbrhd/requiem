import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import cast

import uvicorn
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from starlette.middleware.base import RequestResponseEndpoint
from starlette.responses import Response

from requiem.application.admin.errors import AdminError
from requiem.bootstrap import Runtime, build_runtime
from requiem.logging import configure_logging
from requiem.runtime import new_event_loop
from requiem.settings import Settings, load_settings
from requiem.transports.api.administration import router
from requiem.transports.api.runtime import administration_runtime


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved_settings = settings if settings is not None else load_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        runtime = build_runtime(resolved_settings)
        app.state.runtime = runtime
        try:
            async with administration_runtime(resolved_settings, runtime) as administration:
                app.state.administration = administration
                yield
        finally:
            await runtime.close()

    app = FastAPI(
        title="Requiem", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None
    )
    app.include_router(router)

    @app.middleware("http")
    async def private_responses(request: Request, call_next: RequestResponseEndpoint) -> Response:
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    @app.exception_handler(AdminError)
    async def administration_error(request: Request, error: AdminError) -> JSONResponse:
        return JSONResponse(
            {
                "error": {
                    "code": error.code,
                    "message": error.message,
                    **({"retry_after": error.retry_after} if error.retry_after is not None else {}),
                }
            },
            status_code=error.status,
        )

    @app.exception_handler(RequestValidationError)
    @app.exception_handler(ValidationError)
    @app.exception_handler(ValueError)
    async def invalid_configuration(request: Request, error: Exception) -> JSONResponse:
        return JSONResponse(
            {
                "error": {
                    "code": "configuration_invalid",
                    "message": "Check the selected settings and try again.",
                }
            },
            status_code=422,
        )

    @app.get("/health/live")
    async def live() -> dict[str, str]:
        return {"status": "alive"}

    @app.get("/health/ready")
    async def ready(request: Request) -> JSONResponse:
        runtime = cast(Runtime, request.app.state.runtime)
        readiness = await runtime.health.check()
        return JSONResponse(
            {"status": "ready" if readiness.ready else "not_ready"},
            status_code=200 if readiness.ready else 503,
        )

    return app


def main() -> None:
    settings = load_settings()
    configure_logging(settings)
    server = uvicorn.Server(
        uvicorn.Config(
            create_app(settings),
            host=settings.api_host,
            port=settings.api_port,
            log_config=None,
            server_header=False,
            access_log=False,
        )
    )
    with asyncio.Runner(loop_factory=new_event_loop) as runner:
        runner.run(server.serve())
