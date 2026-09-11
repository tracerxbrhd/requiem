import asyncio
import os
import subprocess
import sys
import uuid
from collections.abc import AsyncIterator, Callable, Iterator
from pathlib import Path

import psycopg
import pytest
from psycopg import sql
from pydantic import SecretStr
from sqlalchemy import delete
from sqlalchemy.engine import make_url

from requiem.bootstrap import Runtime, build_runtime
from requiem.persistence.models import GuildRecord
from requiem.runtime import new_event_loop
from requiem.settings import Settings

ROOT = Path(__file__).resolve().parents[1]


def pytest_asyncio_loop_factories() -> dict[str, Callable[[], asyncio.AbstractEventLoop]]:
    return {"requiem": new_event_loop}


@pytest.fixture
def settings() -> Settings:
    return Settings(
        _env_file=None,
        database_url=SecretStr("postgresql+psycopg://requiem:requiem@127.0.0.1:1/requiem_test"),
    )


def run_migration(database_url: str, *arguments: str) -> None:
    environment = {**os.environ, "REQUIEM_DATABASE_URL": database_url}
    subprocess.run(
        [sys.executable, "-m", "alembic", *arguments],
        cwd=ROOT,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    raw_url = os.environ.get("TEST_DATABASE_URL")
    if raw_url is None:
        pytest.skip("Set TEST_DATABASE_URL to a disposable PostgreSQL database ending in _test")
    url = make_url(raw_url)
    if url.drivername != "postgresql+psycopg" or not (url.database or "").endswith("_test"):
        pytest.fail("TEST_DATABASE_URL must use postgresql+psycopg and a database ending in _test")
    # Every test session owns a new schema within the dedicated test database.
    # No public/development schema is truncated or downgraded.
    schema = "requiem_test_" + uuid.uuid4().hex
    connect_url = url.set(drivername="postgresql").render_as_string(hide_password=False)
    with psycopg.connect(connect_url, autocommit=True) as connection:
        connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    scoped_url = url.update_query_dict({"options": f"-csearch_path={schema}"}).render_as_string(
        hide_password=False
    )
    try:
        run_migration(scoped_url, "upgrade", "head")
        yield scoped_url
    finally:
        with psycopg.connect(connect_url, autocommit=True) as connection:
            connection.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


@pytest.fixture
async def runtime(database_url: str) -> AsyncIterator[Runtime]:
    instance = build_runtime(Settings(_env_file=None, database_url=SecretStr(database_url)))
    try:
        async with instance.database.sessions.begin() as session:
            await session.execute(delete(GuildRecord))
        yield instance
    finally:
        await instance.close()
