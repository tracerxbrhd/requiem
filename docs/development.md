# Development

Administration Discord requests use process-local 15-second authorization and
role/channel snapshots with bounded single-flight fetches. Permission revocation
can take up to that TTL; local bot installation status remains fresh from the DB.
No permission or metadata cache is persisted. See
[administration](administration.md#short-lived-discord-snapshots) for cache bounds,
429 handling and the deliberate authorization trade-off.

When checking Access, Logging and Message Logging, inspect normal tab navigation
for repeated `/users/@me/guilds` requests. Concurrent requests in one session should
share a fetch and reuse it within 15 seconds. Metadata failures should leave settings
visible, with a selector retry and the current draft intact. OAuth 429 uses Discord's
returned delay, with at most one short GET retry; do not deliberately hammer Discord
to test limits. Regression tests use controlled clocks, events and mocked responses.

## Requirements and installation

- Python 3.13 (managed by `uv` if needed).
- `uv`; the verified tool version is 0.10.7.
- Docker Engine/Desktop with Compose for local PostgreSQL and container verification.
- A Discord application and bot token only when connecting the bot.

Install `uv` using the [official instructions](https://docs.astral.sh/uv/getting-started/installation/).
For example, on PowerShell:

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
uv python install 3.13
uv sync --locked
Copy-Item .env.example .env
```

On macOS/Linux, install `uv` using the same instructions, then:

```bash
uv python install 3.13
uv sync --locked
cp .env.example .env
```

`uv.lock` records exact dependency versions and hashes. Use `--locked` for normal sync/run
commands; update dependencies deliberately with `uv lock --upgrade-package NAME`, review the
lock change, and rerun checks. The Docker image and CI install from the same lock.

## Environment variables

Settings read the process environment first, then `.env` from the current working directory.
Empty optional values are ignored. Run local commands from the repository root.

| Variable | Behaviour |
| --- | --- |
| `REQUIEM_DATABASE_URL` | Required by API, bot and migrations; must use `postgresql+psycopg` |
| `REQUIEM_DISCORD_TOKEN` | Required only by `requiem-bot` |
| `REQUIEM_MESSAGE_CONTENT_INTENT_ENABLED` | Defaults to false; opt in to privileged content capability |
| `REQUIEM_GUILD_MEMBERS_INTENT_ENABLED` | Defaults to false; opt in to privileged member observation |
| `REQUIEM_DISCORD_APPLICATION_ID` | Optional positive Discord application ID; reserved for later integrations |
| `REQUIEM_DISCORD_CLIENT_ID` | Optional positive client ID; no OAuth2 flow yet |
| `REQUIEM_API_HOST` | Defaults to `127.0.0.1`; Compose overrides to `0.0.0.0` internally |
| `REQUIEM_API_PORT` | Defaults to 8000; also selects Compose's host API port |
| `REQUIEM_ENVIRONMENT` | Defaults to `development` |
| `REQUIEM_LOG_LEVEL` | `DEBUG`, `INFO`, `WARNING`, `ERROR` or `CRITICAL` |
| `REQUIEM_LOG_FORMAT` | `console` or `json` |
| `REQUIEM_POSTGRES_PORT` | Compose-only host port override; defaults to 5432 |
| `TEST_DATABASE_URL` | Test-only, separate disposable database; name must end in `_test` |

Hikari obtains the bot identity using the token; the optional IDs are not needed to connect.
Never store real tokens in tracked files. `.env` is excluded from Git and Docker build context.
Logging redacts configured credentials and does not return internal exceptions to Discord or
health endpoint clients. Compose passes Discord credentials only to the bot service.

The supplied credentials `requiem:requiem` are for local development. Host ports are bound to
loopback. This Compose file is a development environment, not a production deployment design.

## Host-native processes with Docker PostgreSQL

```bash
docker compose up -d postgres
uv run --locked alembic upgrade head
uv run --locked requiem-api
```

Use a second terminal, with a real `REQUIEM_DISCORD_TOKEN` in `.env`, for:

```bash
uv run --locked requiem-bot
```

The default host database URL is:

```text
postgresql+psycopg://requiem:requiem@127.0.0.1:5432/requiem
```

Check [liveness](http://127.0.0.1:8000/health/live) and
[readiness](http://127.0.0.1:8000/health/ready). The bot registers the seven
[Moderation commands](moderation.md); configuration endpoints are not implemented yet.
Use the supplied entry points on Windows: they select an
asyncio loop compatible with Psycopg. Generic ASGI launchers may choose an incompatible
Windows Proactor loop.

## Migrations

Alembic is the only schema evolution mechanism; starting API/bot never creates tables.

```bash
uv run --locked alembic current
uv run --locked alembic upgrade head
uv run --locked alembic check
```

For a deliberate model change, generate a candidate migration with
`uv run --locked alembic revision --autogenerate -m "Describe the schema change"`, inspect it,
format/lint it and update the expected application schema revision. Test migration upgrades
in a disposable database. `downgrade base` removes the application schema and is only suitable
for intentional resets or disposable migration tests.

## Docker environment

After copying `.env.example` to `.env` and entering a bot token:

```bash
docker compose config --quiet
docker compose up --build
```

Without a token, start the API and its dependencies:

```bash
docker compose up --build -d api
```

This starts PostgreSQL, waits for `pg_isready`, runs `alembic upgrade head` once, and then starts
the API. Full startup also starts the separate bot after successful migrations. If the bot
has no token, it exits with a clear configuration error; the API continues independently.

The container database URL uses `postgres:5432`. Compose overrides the host-native URL, and
the API listens on port 8000 inside the container regardless of the published host port.
Changing code requires rebuilding the image; no source mounts or reload daemons are used.

Useful commands:

```bash
docker compose build
docker compose ps -a
docker compose logs -f api bot
docker compose logs migrate postgres
docker compose exec api alembic current
docker compose up -d postgres
docker compose run --rm migrate
docker compose stop bot
docker compose down
```

`docker compose down` removes the containers/network and **preserves** the named
`postgres-data` volume. The next `docker compose up -d api` reuses the database.

For an intentional complete local database reset:

```bash
docker compose down -v
docker compose up --build -d api
```

**`down -v` destroys the local Docker database data**, including guild configuration and
pending temporary-ban expirations. Losing those records prevents automatic unbanning.
The new volume starts empty and the migration service recreates the schema. Do not use it
when you need to preserve data. No reset command is run automatically by the application.

## Tests and quality

```bash
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked mypy
uv run --locked pytest
```

Tests without PostgreSQL cover configuration rules, settings, redacted logs, ephemeral
Discord errors, dependency wiring, shutdown cleanup and API readiness/liveness behaviour.
Moderation tests cover native permissions, hierarchy, channel overwrites, durations,
reason propagation, purge pagination and failure/restart/concurrency handling for bans.
PostgreSQL tests are explicitly skipped when `TEST_DATABASE_URL` is absent.

To run all tests, create a dedicated database in the local development PostgreSQL instance:

```bash
docker compose exec postgres createdb -U requiem requiem_test
```

PowerShell:

```powershell
$env:TEST_DATABASE_URL = 'postgresql+psycopg://requiem:requiem@127.0.0.1:5432/requiem_test'
uv run --locked pytest
```

macOS/Linux:

```bash
TEST_DATABASE_URL=postgresql+psycopg://requiem:requiem@127.0.0.1:5432/requiem_test uv run --locked pytest
```

The database name must end in `_test`. Each test session creates a unique schema, migrates
it from empty, and removes only that schema afterward. Migration round-trip tests never
downgrade the normal development schema. The test user needs schema creation privileges.
Integration tests exercise real PostgreSQL, SQLAlchemy asyncio, foreign keys, state isolation,
concurrent role replacement, installation preservation and migration/model agreement.
They also exercise durable temporary-ban state, advisory locks across store instances,
expiry while Moderation is disabled, and the `0001_core` to `0002_temporary_bans` upgrade.
Stage 3 extends this through `0003_logging`, including logging configuration defaults,
relational replacement and validation. Unit tests cover routing, diagnostics, Gateway
adapters, echo suppression, content scope, cache bounds, edit chains and queue overload.

Enable optional privileged intents in the Discord Developer Portal and set the matching
environment flag, then restart the bot. Startup checks application flags before requesting
them; unavailable or unverified capabilities are disabled for that run. Logging diagnostics
expose the resulting capabilities. See [Audit and Logging](audit-logging.md) for the
configuration contract, permissions and delivery limitations.

The GitHub Actions workflow performs locked dependency installation, lint, format, strict
type checking, the complete test suite with a PostgreSQL service, and Compose validation.
It requires no Discord credentials and contains no deployment or release automation.

## Administration frontend

Stage 4 adds the `frontend` Compose service and a direct Vite development workflow.
See [Administration](administration.md) for OAuth setup, the required session secret,
local dev authentication, explicit seed command and frontend quality checks.
