# Administration platform

Stage 4 adds a public React website and a configuration workspace to the existing
FastAPI process. Discord remains the operational interface. The web UI has no
moderation operations, member browser, analytics, audit archive or message history.

## Architecture

`frontend/src/api.ts` centralizes credentials, session CSRF, errors and typed section
resources. `auth.tsx` guards dashboard routes; `pages.tsx` supplies landing, login,
server selection and the reusable workspace. `settings.tsx` implements purpose-built
Moderation tabs. `ui.tsx` owns selectors, switches, dialogs and navigation protection.
The locale abstraction in `locale.ts` currently offers English only.

FastAPI's `transports/api/administration.py` adapts HTTP requests to application
services in `application/admin/`. `ConfigurationService` can join an explicitly
owned transaction. The administration service reuses it and Stage 3's
`LoggingConfigurationService.read_in/save_in`; there is no parallel configuration
store. Guild metadata is fetched through an API-owned Hikari REST client, independent
of the bot's gateway cache. Existing Stage 3 diagnostics are reused.

Migration `0004_admin_platform` creates `admin_sessions` and `admin_oauth_states`.
Migrations 0001–0003 are unchanged. No audit or message persistence is introduced.

## Run locally

Set up `.env` from `.env.example`, preserving existing values. Generate a stable,
high-entropy session secret with `python -c "import secrets; print(secrets.token_urlsafe(48))"`
and put it in `REQUIEM_SESSION_SECRET`. Do not publish this value.

```sh
docker compose up -d --build postgres migrate api frontend
# Start bot separately once its Discord token is configured:
docker compose up -d bot
```

Open http://localhost:5173. API and frontend use a same-origin proxy; there is no
permissive CORS configuration. Direct refresh of dashboard URLs returns the SPA.
Ports are configurable with `REQUIEM_FRONTEND_PORT` and `REQUIEM_API_PORT`.
When changing the public port, also change `REQUIEM_FRONTEND_URL` and the OAuth URI.

For direct development, run PostgreSQL and migrations, then `uv run --locked requiem-api`.
In `frontend/`, run `npm ci` and `npm run dev`. Vite proxies `/api` to
`http://127.0.0.1:8000`. Use **localhost** consistently in the browser and configured
frontend URL: the development-login Origin check intentionally rejects a different host.

## Discord OAuth setup

In the Discord Developer Portal, configure the application's client ID and client
secret. Register this exact development redirect URI:

```text
http://localhost:5173/api/auth/discord/callback
```

Set `REQUIEM_DISCORD_CLIENT_ID`, `REQUIEM_DISCORD_CLIENT_SECRET`,
`REQUIEM_DISCORD_OAUTH_REDIRECT_URI`, `REQUIEM_FRONTEND_URL` and
`REQUIEM_SESSION_SECRET` for the API. The bot token is also needed by the API for
role/channel metadata and diagnostics. No bot gateway runs inside FastAPI.

Sign-in requests only `identify guilds`, uses the Authorization Code Grant, checks
single-use browser-bound state and exchanges codes server-side. OAuth access and
refresh tokens never appear in browser storage or responses. Refresh is serialized
by a database row lock to avoid token rotation races across API replicas.

The installation endpoint generates a URL with `bot applications.commands identify
guilds`, `response_type=code`, the registered redirect, selected guild and disabled
guild selection. Additional user scopes deliberately invoke Discord's supported
Advanced Bot Authorization flow; the callback-less bot shortcut cannot provide the
required return. The final callback always returns to `/dashboard/servers`.
Installation is never inferred from callback parameters: gateway-observed local
`guilds.installed` remains authoritative. Refresh the selector if the bot has not yet
observed the installation. No last-guild auto-navigation is stored.

Requested bot permissions: Kick Members, Ban Members, Manage Guild (AutoMod gateway
observation), View Channel, Send Messages, Manage Messages, Embed Links, Read Message
History and Moderate Members. Administrator is never requested. Discord channel
permission overwrites and role hierarchy can still prevent individual operations.

Official flow reference: https://docs.discord.com/developers/topics/oauth2#advanced-bot-authorization

## Sessions and request protection

The browser receives a random opaque HttpOnly, SameSite=Lax session cookie. Only its
SHA-256 digest is persisted. Sessions expire after seven days by default, configurable
with `REQUIEM_SESSION_LIFETIME_SECONDS` (5 minutes to 30 days). New logins rotate the
session and invalidate the old one. Logout deletes the row and clears the cookie.
Expired sessions are lazily removed on login; expired OAuth states are removed when
starting another flow. OAuth state expires in ten minutes and is consumed once.

OAuth token JSON is authenticated-encrypted with Fernet using a key derived from the
operator's high-entropy session secret. Keep the same secret across replicas; changing
it requires users to sign in again. Back up the database and secret separately.
Authentication failures and upstream outages return typed messages, never tokens or
tracebacks. API/proxy access logging is disabled to avoid logging callback codes.

Mutating authenticated requests require a session-bound `X-CSRF-Token`, obtained from
`GET /api/auth/session`. Login state and API CSRF are independent. Dev login, before a
session exists, requires an exact configured frontend Origin. No URL supplied by a
browser controls redirects. Production URLs must use HTTPS and cookies are Secure.
Terminate TLS at your deployment edge; the local Compose setup binds only loopback.
Swagger/OpenAPI remains disabled. Keep development authentication off in production.

## Development authentication

`REQUIEM_DEV_AUTH_ENABLED=false` by default. Enabling it outside
`REQUIEM_ENVIRONMENT=development` **fails validated startup**. A session secret is
required. A development principal identifies itself as Local developer and does not
impersonate Discord or fabricate OAuth tokens. Existing local guild rows drive its
selector. Real Discord metadata is preferred when a bot token is configured.

For an empty, disposable local database, explicitly seed one guild:

```sh
docker compose exec api python -m requiem.application.admin.seed --guild-id 900000000000000001
```

The command requires development + dev auth, refuses an existing guild, and does not
run automatically. It creates only a local installed-guild fixture, not Discord roles
or channels. Without a bot token, General and Commands can be configured; selectors
show a retryable metadata-unavailable state. For full selectors, use an actual test
guild and bot token. Never seed a production database.

## Authorization and installation lifecycle

Every guild-specific API request checks the principal against fresh user OAuth guild
data. Only an owner or a user with Discord Administrator is admitted. Manage Guild
alone is insufficient. Frontend guards are only UX. Development principals use the
same authorization interface with an explicitly gated local guild source.

Removing the bot marks the installation inactive and preserves all configuration.
The selector combines authorized installed and non-installed servers, installed first,
then alphabetically. Inactive icons are subdued and screen-reader labels state the
installation status. Re-adding restores previous settings. Offline gateway removals
remain subject to Stage 3's installation-state observation limitation.

## API resources

All routes are under `/api`:

- `GET /auth/session`, `GET /auth/discord/start`, `GET /auth/discord/callback`
- `POST /auth/dev`, `POST /auth/logout`
- `GET /guilds`, `POST /guilds/{guild}/install`
- `GET /guilds/{guild}/overview`, `/roles`, `/channels`
- `GET` and `PUT /guilds/{guild}/modules/moderation/{section}`
- `POST /guilds/{guild}/modules/moderation/reset`

Sections: `general`, `commands`, `access`, `logging`, `message-logging`. GET returns
`{revision, data}`; PUT sends the same shape. Discord IDs are decimal strings in JSON
to preserve snowflakes beyond JavaScript's integer precision. Known commands/events,
IDs, role membership and newly selected channels are validated. Removed destinations
already saved may remain for explicit repair, as in Stage 3.

Errors have `{error: {code, message}}`, with 401 for missing/expired authentication,
403 for authorization/CSRF denial, 409 for stale revisions or inactive installation,
422 for invalid configuration, and 503 for unavailable Discord/auth configuration.

Revisions are SHA-256 hashes of a canonical complete section snapshot. Reads and
writes lock the existing guild row; save compares the current hash inside the same
transaction as all updates. Existing Core and logging writers use the same guild
lock, so this also detects changes through their services. No redundant version
columns are needed. Identical values produce the same revision (intentional ETag
semantics). Sections can be edited independently without overwriting other sections.

Reset deletes only the Moderation module configuration and logging roots in one
transaction, then reads domain defaults back. It preserves temporary bans, guild
installation and unrelated module configuration. No React defaults are authoritative.

## Interaction and visual design

Each tab holds a local draft. Changes are saved explicitly, atomically, and remain
visible on errors. A stale save offers reload; it never overwrites newer values.
Internal route changes and browser back use a Stay/Discard dialog. Browser unload
uses native protection. Reset requires its own confirmation. Access custom roles
replace module defaults; they do not create an Owner/Admin operational bypass.

Dark-only design uses the original Requiem logo's graphite, indigo and violet palette,
large translucent surfaces, subtle highlights and centralized CSS theme tokens.
Future light-theme tokens can replace the palette without changing components.
Manrope and Lucide are bundled locally; licenses ship in `/licenses/` and are recorded
in `THIRD_PARTY_NOTICES.md`. No Flaticon assets are used.

Desktop is primary. Guild grids reflow, forms stack and the sidebar opens as a drawer
on narrow screens. Controls have labels, visible focus and semantic switches; native
modal dialogs constrain focus. Reduced-motion preferences disable motion. English
is the sole language, with a language selector location and common copy abstraction.

## Verification

```sh
uv sync --locked
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked mypy
# Set TEST_DATABASE_URL to a disposable PostgreSQL database ending in _test.
uv run --locked pytest
docker compose config --quiet
cd frontend
npm ci
npm run lint
npm run format:check
npm run typecheck
npm run test
npm run build
```

Integration tests own isolated PostgreSQL schemas and verify the complete migration
chain, authorization, sessions, CSRF, section writes, races and reset preservation.
Discord HTTP is mocked in CI. Real Discord consent, app installation, privileged grants
and role/channel permission behavior need an operator-configured test application;
mocked tests cannot prove its Developer Portal configuration.

## Stage 4 verification record

The local verification run passed 250 Python tests (including PostgreSQL integration)
and eight frontend interaction tests. Ruff, formatting, strict mypy, TypeScript,
ESLint and the production Vite build passed. `npm ci` reported no known vulnerabilities.
The Docker images built successfully and API readiness returned healthy after migration.

Browser checks covered the landing page, dev authentication, empty server selection,
an explicitly seeded local server, guild overview, General settings save, unsaved-tab
navigation confirmation, direct nested-route refresh and a 390×844 mobile layout.
No browser console errors were observed. A real Discord OAuth application was not used
for these checks; consent, actual installation and real metadata require operator setup.
