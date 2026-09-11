import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import cast

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from requiem.bootstrap import Runtime, build_runtime
from requiem.logging import configure_logging
from requiem.runtime import new_event_loop
from requiem.settings import Settings, load_settings


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved_settings = settings if settings is not None else load_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        runtime = build_runtime(resolved_settings)
        app.state.runtime = runtime
        try:
            yield
        finally:
            await runtime.close()

    app = FastAPI(
        title="Requiem", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None
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
        )
    )
    with asyncio.Runner(loop_factory=new_event_loop) as runner:
        runner.run(server.serve())
