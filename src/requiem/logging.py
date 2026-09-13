"""Stdout logging with redaction applied after exception formatting."""

import json
import logging
import re
import sys
from datetime import UTC, datetime
from urllib.parse import unquote

from sqlalchemy.engine import make_url

from requiem.settings import Settings


class RedactingFormatter(logging.Formatter):
    def __init__(self, *, json_output: bool, secrets: tuple[str, ...] = ()) -> None:
        super().__init__("%(asctime)s %(levelname)s %(name)s: %(message)s")
        self.json_output = json_output
        self.secrets = tuple(sorted(filter(None, secrets), key=len, reverse=True))

    def redact(self, value: str) -> str:
        for secret in self.secrets:
            value = value.replace(secret, "[REDACTED]")
        return re.sub(r"postgresql(?:\+psycopg)?://[^\s]+", "[DATABASE_URL]", value)

    def format(self, record: logging.LogRecord) -> str:
        if not self.json_output:
            return self.redact(super().format(record))
        payload = {
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": self.redact(record.getMessage()),
        }
        if record.exc_info:
            payload["exception"] = self.redact(self.formatException(record.exc_info))
        return json.dumps(payload, ensure_ascii=False)


def configure_logging(settings: Settings) -> None:
    database_url = settings.database_url.get_secret_value()
    password = make_url(database_url).password or ""
    token = settings.discord_token.get_secret_value() if settings.discord_token else ""
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        RedactingFormatter(
            json_output=settings.log_format == "json",
            secrets=(
                database_url,
                password,
                unquote(password),
                token,
                settings.discord_client_secret.get_secret_value()
                if settings.discord_client_secret
                else "",
                settings.session_secret.get_secret_value() if settings.session_secret else "",
            ),
        )
    )
    logging.basicConfig(level=settings.log_level, handlers=[handler], force=True)
    # SQL parameters and driver details are unsuitable for routine stdout logs.
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
