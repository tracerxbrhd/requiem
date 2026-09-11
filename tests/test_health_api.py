from unittest.mock import AsyncMock, MagicMock, Mock

import httpx
import pytest
from sqlalchemy.exc import OperationalError

from requiem.application.health import HealthService, Readiness
from requiem.bootstrap import Runtime
from requiem.persistence.database import SCHEMA_REVISION, Database
from requiem.settings import Settings
from requiem.transports.api.app import create_app


@pytest.mark.parametrize(
    "revisions,expected", [([SCHEMA_REVISION], True), ([], False), (["old"], False)]
)
async def test_readiness_checks_schema_revision(revisions: list[str], expected: bool) -> None:
    database = Mock(spec=Database)
    result = Mock()
    result.scalars.return_value.all.return_value = revisions
    connection = AsyncMock()
    connection.execute.return_value = result
    database.engine = MagicMock()
    database.engine.connect.return_value.__aenter__.return_value = connection
    assert (await HealthService(database).check()).ready is expected
    assert connection.execute.await_count == 2


@pytest.mark.parametrize(
    "error", [OperationalError("SELECT 1", {}, Exception("private")), TimeoutError()]
)
async def test_readiness_handles_database_failure(error: Exception) -> None:
    database = Mock(spec=Database)
    database.engine = MagicMock()
    database.engine.connect.return_value.__aenter__.side_effect = error
    assert (await HealthService(database).check()).ready is False


@pytest.mark.parametrize("ready,status_code", [(True, 200), (False, 503)])
async def test_api_health_and_lifecycle(
    settings: Settings, monkeypatch: pytest.MonkeyPatch, ready: bool, status_code: int
) -> None:
    runtime = Mock(spec=Runtime)
    runtime.health = Mock()
    runtime.health.check = AsyncMock(return_value=Readiness(ready))
    runtime.close = AsyncMock()
    monkeypatch.setattr("requiem.transports.api.app.build_runtime", lambda _: runtime)
    app = create_app(settings)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            live = await client.get("/health/live")
            assert live.status_code == 200
            assert live.json() == {"status": "alive"}
            runtime.health.check.assert_not_called()
            readiness = await client.get("/health/ready")
            assert readiness.status_code == status_code
            assert readiness.json() == {"status": "ready" if ready else "not_ready"}
            assert (await client.get("/guilds")).status_code == 404
    runtime.close.assert_awaited_once()


async def test_real_unreachable_database_does_not_prevent_api_liveness(settings: Settings) -> None:
    app = create_app(settings)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            assert (await client.get("/health/live")).status_code == 200
            assert (await client.get("/health/ready")).status_code == 503
