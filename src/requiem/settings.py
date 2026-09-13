"""Environment configuration shared by both runtime processes."""

from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, ValidationError, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="REQUIEM_",
        env_file=".env",
        env_file_encoding="utf-8",
        env_ignore_empty=True,
        extra="ignore",
        hide_input_in_errors=True,
    )

    database_url: SecretStr
    discord_token: SecretStr | None = None
    discord_application_id: int | None = Field(default=None, gt=0)
    discord_client_id: int | None = Field(default=None, gt=0)
    discord_client_secret: SecretStr | None = None
    discord_oauth_redirect_uri: str = "http://localhost:5173/api/auth/discord/callback"
    frontend_url: str = "http://localhost:5173"
    session_secret: SecretStr | None = None
    session_lifetime_seconds: int = Field(default=604800, ge=300, le=2592000)
    dev_auth_enabled: bool = False
    message_content_intent_enabled: bool = False
    guild_members_intent_enabled: bool = False
    api_host: str = "127.0.0.1"
    api_port: int = Field(default=8000, ge=1, le=65535)
    environment: str = "development"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    log_format: Literal["console", "json"] = "console"

    @model_validator(mode="after")
    def validate_administration(self) -> "Settings":
        if self.dev_auth_enabled and self.environment != "development":
            raise ValueError("Development authentication requires development environment")
        for value in (self.frontend_url, self.discord_oauth_redirect_uri):
            url = urlsplit(value)
            if (
                url.scheme not in {"http", "https"}
                or not url.hostname
                or url.username
                or url.password
                or url.query
                or url.fragment
            ):
                raise ValueError("Administration URLs must be absolute HTTP(S) URLs")
            if self.environment != "development" and url.scheme != "https":
                raise ValueError("Production administration URLs require HTTPS")
        if self.session_secret is not None and len(self.session_secret.get_secret_value()) < 32:
            raise ValueError("Session secret must contain at least 32 characters")
        if (self.dev_auth_enabled or self.discord_client_secret) and self.session_secret is None:
            raise ValueError("Administration authentication requires a session secret")
        return self

    @field_validator("database_url")
    @classmethod
    def validate_database_url(cls, value: SecretStr) -> SecretStr:
        try:
            url = make_url(value.get_secret_value())
            if url.drivername != "postgresql+psycopg" or not url.host or not url.database:
                raise ValueError
        except (ArgumentError, ValueError):
            raise ValueError("Expected a postgresql+psycopg URL with host and database") from None
        return value

    def require_discord_token(self) -> str:
        if self.discord_token is None or not self.discord_token.get_secret_value().strip():
            raise ValueError("REQUIEM_DISCORD_TOKEN is required to start the bot")
        return self.discord_token.get_secret_value()


def load_settings() -> Settings:
    try:
        return Settings()
    except ValidationError as error:
        fields = ", ".join(
            ("REQUIEM_" + "_".join(str(part).upper() for part in item["loc"]))
            if item["loc"]
            else str(item["msg"])
            for item in error.errors(include_input=False, include_context=False)
        )
        raise SystemExit(f"Missing or invalid configuration: {fields}. See .env.example.") from None
