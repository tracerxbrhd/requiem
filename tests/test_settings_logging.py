import json
import logging
import sys

import pytest
from pydantic import SecretStr, ValidationError

from requiem.logging import RedactingFormatter
from requiem.settings import Settings, load_settings


def test_token_only_required_by_bot(settings: Settings) -> None:
    assert settings.discord_token is None
    with pytest.raises(ValueError, match="REQUIEM_DISCORD_TOKEN"):
        settings.require_discord_token()


def test_settings_read_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REQUIEM_DATABASE_URL", "postgresql+psycopg://r:r@localhost/requiem")
    monkeypatch.setenv("REQUIEM_API_PORT", "8010")
    monkeypatch.setenv("REQUIEM_DISCORD_APPLICATION_ID", "")
    monkeypatch.setenv("REQUIEM_DISCORD_CLIENT_ID", "123")
    settings = Settings(_env_file=None)
    assert settings.api_port == 8010
    assert settings.discord_application_id is None
    assert settings.discord_client_id == 123


@pytest.mark.parametrize("url", ["sqlite:///test.db", "bad-secret-value", "postgresql://r:r@db/r"])
def test_invalid_database_configuration_does_not_echo_input(url: str) -> None:
    with pytest.raises(ValidationError) as caught:
        Settings(_env_file=None, database_url=SecretStr(url))
    assert url not in str(caught.value)


def test_missing_database_fails_clearly(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("REQUIEM_DATABASE_URL", raising=False)
    monkeypatch.setattr(Settings, "model_config", {**Settings.model_config, "env_file": None})
    with pytest.raises(SystemExit, match="REQUIEM_DATABASE_URL"):
        load_settings()


@pytest.mark.parametrize("json_output", [False, True])
def test_logs_redact_messages_and_tracebacks(json_output: bool) -> None:
    secret = "example-private-token"
    try:
        raise RuntimeError(f"credential={secret}")
    except RuntimeError:
        record = logging.LogRecord(
            "requiem.test", logging.ERROR, __file__, 1, "Failure: %s", (secret,), sys.exc_info()
        )
    formatter = RedactingFormatter(json_output=json_output, secrets=(secret,))
    output = formatter.format(record)
    assert secret not in output
    assert "[REDACTED]" in output
    assert "RuntimeError" in output
    if json_output:
        assert json.loads(output)["level"] == "ERROR"
