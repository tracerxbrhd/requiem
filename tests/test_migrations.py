import pytest
from conftest import run_migration

pytestmark = pytest.mark.integration


def test_initial_migration_round_trip(database_url: str) -> None:
    run_migration(database_url, "downgrade", "base")
    run_migration(database_url, "upgrade", "0001_core")
    run_migration(database_url, "upgrade", "head")
    run_migration(database_url, "downgrade", "0001_core")
    run_migration(database_url, "upgrade", "head")
    run_migration(database_url, "check")
