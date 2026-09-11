# Foundation verification

Verified locally on 2026-09-11 using Windows, Python 3.13.12, uv 0.10.7,
Docker Desktop with Linux containers and Docker Compose.

## Implementation

The `src/requiem` package is a modular monolith with shared domain, application and
persistence code. Independent `requiem-api` and `requiem-bot` entry points own their own
async database runtime. [Architecture](architecture.md) describes the boundaries, defaults,
schema and extension points; [development](development.md) covers setup and commands.

Alembic migration `0001_core` creates `guilds`, `guild_modules`, `module_allowed_roles`,
`guild_commands` and `command_allowed_roles`, with composite keys, foreign keys and checks.
The guild configuration model supports module and command enablement, inherited or custom
role access, role replacement and preserved installation/configuration state.

Arc hooks delegate decisions to `CommandAccessService` and render denials ephemerally.
Hikari uses only `GUILDS`, persists join/availability/leave events, and closes before database
disposal. FastAPI uses lifespan ownership with `/health/live` and database/schema-aware
`/health/ready`. Settings are typed, use `REQUIEM_`, and require a token only for the bot.
Logging supports console and redacted JSON stdout.

One Dockerfile builds a locked, non-editable production installation and runs it as
UID/GID 10001. Compose uses `postgres -> migrate -> api + bot`; PostgreSQL has a named volume
and `pg_isready`, migration is one-shot, and API health uses Python's standard library.
Container services use hostname `postgres`; native development retains `127.0.0.1`.
Neither application runs migrations implicitly. Environment files and local artifacts are
excluded from Git and image context.

## Selected versions

Exact package versions and hashes are recorded in `uv.lock`.

| Component | Version |
| --- | --- |
| Python | 3.13.12; project range `>=3.13,<3.14` |
| Hikari / hikari-arc | 2.6.0 / 2.3.2 |
| FastAPI / Uvicorn | 0.141.1 / 0.52.4 |
| SQLAlchemy / Psycopg | 2.0.52 / 3.3.5 |
| Alembic | 1.19.2 |
| Pydantic / Pydantic Settings | 2.13.5 / 2.15.0 |
| PostgreSQL image | `postgres:18.6-bookworm` |
| pytest / pytest-asyncio | 9.1.1 / 1.4.0 |
| Ruff / mypy | 0.16.7 / 1.20.2 |

## Verification results

| Check | Result |
| --- | --- |
| `uv sync`, `uv sync --locked` | Passed; lock and environment agree |
| `uv run --locked ruff check .` | Passed |
| `uv run --locked ruff format --check .` | Passed |
| `uv run --locked mypy` | Passed in strict mode, including tests/migrations |
| `mypy --platform linux` | Passed |
| Complete pytest suite with `TEST_DATABASE_URL` | 49 passed, no skips or warnings |
| `docker compose config --quiet` | Passed |
| `docker compose build` | Passed; one common application image |
| Empty PostgreSQL volume -> Alembic head | Passed on PostgreSQL 18.6; `0001_core` |
| Migration downgrade/upgrade/repeated upgrade | Passed in an isolated test schema |
| Migration/model comparison | No differences |
| API startup and both health endpoints | HTTP 200 with expected JSON |
| PostgreSQL outage | Readiness 503; liveness remains 200 |
| `docker compose down` then `up` | Named volume and saved module role preserved |
| Runtime user and environment exclusion | UID 10001; `/app/.env` absent |
| Bot without credentials | Clear nonzero exit for missing `REQUIEM_DISCORD_TOKEN` |

Container verification used the isolated project `requiem-foundation-check-20260911` with
host ports 55432 and 18000. A separate `requiem_test` database was used for integration tests;
each suite created and removed its own schema. The full test command used
`uv run --locked pytest -o cache_dir=.cache/pytest-full` to keep its cache inside the workspace.
Temporary verification containers, network and database volume were removed afterward.

Tests cover guild isolation, module/command state, configuration preservation, inherited
roles, replacement by custom roles, any-role access, empty-role denial, structured guard
failures, real Arc dependency injection, guild lifecycle, startup/shutdown cleanup,
readiness failures, relational constraints and concurrent role replacement.

`.github/workflows/ci.yaml` installs the lock and runs lint, formatting, strict typing,
the complete test suite with PostgreSQL, and Compose validation. It needs no Discord token.
The workflow exists locally; no remote CI run, deployment or release was triggered.

## Remaining review before the next milestone

- Live Discord connectivity was not tested because no valid token was supplied.
- Moderation commands/actions, native action permission/hierarchy checks, OAuth2,
  administration UI/APIs, scheduling and other product modules are not implemented.
- Review disabled-by-default modules, denial for empty role sets and the absence of an
  administrator/owner bypass before exposing configuration to server administrators.
- Installation state reflects observed gateway events. Offline removals are not reconciled
  yet, and the flag must not be treated as authoritative Discord membership.
- Keep application `SCHEMA_REVISION` synchronized with future migrations.

No stage 2 work has been started.
