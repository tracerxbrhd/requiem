# Architecture

Requiem is one modular monolith with two independently supervised processes.
Both import the same `requiem` package and share PostgreSQL and migrations.

```text
src/requiem/
  domain/                 Immutable configuration values and access decisions
  application/            Guild, configuration, command-access and health services
  modules/catalogue.py    Explicit module and command identifiers
  modules/moderation/     Moderation rules, application service, ports and expiry worker
  modules/moderation/audit/  Audit values, routing, queues and bounded message state
  persistence/            SQLAlchemy models, database lifecycle and repositories
  transports/discord/     Hikari lifecycle, Arc hooks and error presentation
  transports/api/         FastAPI lifecycle and health routes
  bootstrap.py            Process-owned runtime composition
  settings.py             Typed environment configuration
  logging.py              Console/JSON logging and secret redaction
  runtime.py              Asyncio loop factory, including Windows support
migrations/               Alembic schema history
tests/                    Domain, transport and PostgreSQL integration tests
```

Transport handlers call small application services. They neither issue SQL nor contain
permission rules. Services return immutable domain values, not ORM records. Each operation
opens its own session; mutations use a transaction. Repositories are concrete and scoped to
that transaction. There is no global session, mutable configuration cache, event bus or
dynamic plugin loader. Arc receives process-owned services through dependency injection.

## Schema

Migration `0001_core` creates the five configuration tables; `0002_temporary_bans`
adds operational lifecycle state:

| Table | Key | Purpose |
| --- | --- | --- |
| `guilds` | `guild_id` | Installation state and creation/update timestamps |
| `guild_modules` | `guild_id`, `module_name` | Per-guild module enabled state |
| `module_allowed_roles` | `guild_id`, `module_name`, `role_id` | Module default roles |
| `guild_commands` | `guild_id`, `module_name`, `command_name` | Command enabled state and access mode |
| `command_allowed_roles` | `guild_id`, `module_name`, `command_name`, `role_id` | Custom command roles |
| `temporary_bans` | `guild_id`, `user_id` | One authoritative expiry and retry timestamp per target |

Migration `0003_logging` adds five relational Moderation logging configuration tables.
There is no audit history or message body table. See [Audit and Logging](audit-logging.md).
`Runtime.logging_configuration` provides atomic full-configuration replacement, with a
root-row upsert serializing writers and repeatable-read snapshots for multi-table reads.

Composite foreign keys prevent roles and commands from being attached to another guild's
configuration. Primary keys deduplicate role assignments. Check constraints enforce positive
IDs, supported access modes and the exclusion of `core` from optional module state.
Current Discord snowflakes are stored as signed PostgreSQL `BIGINT`; the application
rejects IDs outside `1..2^63-1`. Timestamps use PostgreSQL time zones.

Configuration writers lock the guild row before updates, making role replacement atomic
even when the API and bot write concurrently. Permission resolution uses one SQL statement
to obtain a consistent snapshot. No write is required for a configuration read. Disabling a
module, switching access modes, or uninstalling the bot never deletes configuration.
Foreign-key cascades only apply if a guild is explicitly deleted; there is no guild deletion
use case in this milestone.

## Configuration defaults and authority

| Setting | Default / meaning |
| --- | --- |
| Known optional modules | `moderation` |
| Core | Always present; cannot be disabled |
| Missing module configuration | Disabled, no allowed roles |
| Missing command configuration | Enabled, `inherit`, no custom roles |
| `inherit` access | Use the module role set |
| `custom` access | Replace the module role set with the command role set |
| Empty effective role set | Deny access |
| Role matching | Any one effective allowed role is sufficient |
| Administrator/owner bypass | None |
| `@everyone` | Supported explicitly by configuring the guild ID as a role ID |

Custom roles remain stored when switching back to `inherit`. Changing custom roles does not
implicitly change access mode. The enabled state of a command remains stored when its module
is disabled. Installation state is separate from configuration defaults.

The catalogue identifies `warn`, `timeout`, `untimeout`, `kick`, `ban`, `unban` and `purge`.
All seven are implemented as global top-level commands with runtime guards; modules do not imply slash
command groups. Add new feature definitions explicitly in `modules/catalogue.py`.

## Discord boundary

`command_guard(module_name, command_name)` is an Arc pre-execution hook, attached with
`arc.with_hook`. It uses injected `CommandAccessService` and checks guild context, module
state, command state and effective roles, in that order. A denial raises
`CommandAccessDenied` carrying an `AccessResult`; the client error handler renders a clear
ephemeral message. Unexpected errors are logged with context and a generic ephemeral reply.
The client's automatic defer is ephemeral too, so a slow database lookup cannot make an
access-denied response public. Future commands should preserve that defer policy.

Requiem access is only one gate. The Moderation service additionally checks native Discord
permissions and actor/bot hierarchy using fresh REST snapshots. Purge uses overwrites in
the affected channel. The Discord adapter owns Hikari calls; application services receive
plain DTOs and never Arc contexts. See [Moderation](moderation.md) for policy and limits.

The bot requests `GUILDS`, `GUILD_MODERATION`, `GUILD_MESSAGES` and AutoMod intents.
Privileged Members and Message Content intents require explicit operator flags and a
successful application-capability preflight. Interaction member roles come from the
interaction payload. Guild join/availability marks the installation active; guild leave
marks it inactive. Temporary guild unavailability is not treated as removal. Installation
state reflects observed gateway events; removals while the bot is offline are not reconciled
in this milestone and the flag is not an authorization source.

The bot verifies database connectivity and schema revision before starting Hikari. Arc
follows Hikari's lifecycle. A PostgreSQL-backed expiry worker starts with the gateway,
independently of module configuration. Audit delivery also runs in this process with
independent bounded high/low queues. Cancellation and SIGTERM stop workers, then
close the gateway before disposing the database engine. There is no HTTP server inside
the bot process.

## HTTP boundary and readiness

FastAPI owns an independent runtime in its lifespan and disposes its engine at shutdown.
`GET /health/live` returns 200 without a database call. `GET /health/ready` has a bounded
database check and returns 200 only when PostgreSQL is reachable and Alembic reports the
expected schema revision. Missing schema, old revision, timeout and connection failures
produce 503 with no database details. API startup does not need a bot token, and database
outages do not prevent its liveness endpoint from responding.

When adding a migration, update `SCHEMA_REVISION` in `persistence/database.py` along with
its migration. Readiness intentionally requires that exact revision for this milestone.

## Runtime and scope

The shared image installs the locked production environment in a build stage and copies a
non-editable installation into a slim Python runtime. The runtime runs as UID/GID 10001 and
executes the console entry point directly. It contains migration files, but no development
dependencies, environment file or build-time package manager.

Compose starts healthy PostgreSQL, then one migration service, then independent API and bot
services. Neither application migrates on startup. API readiness uses Python's standard
library; PostgreSQL readiness uses `pg_isready`. No fake bot healthcheck is provided.

The disabled-by-default policy, empty-role denial, lack of owner/admin Requiem bypass,
and installation-state semantics remain unchanged. Configuration has application services
but no user-facing management UI or API yet. Authentication, general schedules and frontend
work remain outside this milestone. Logging switches are independent of command switches;
configuration changes themselves are not audited.
