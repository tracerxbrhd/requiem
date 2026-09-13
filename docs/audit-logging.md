# Audit and Logging

Stage 3 adds Requiem-owned Discord audit embeds and optional full Message Logging within
Moderation. Discord channels are the human-readable long-term destination. Requiem never
reads, polls or correlates Discord Audit Log and never subscribes to its entry-create event.
Native audit-log reasons on administrative requests remain supported.

## Configuration contract and defaults

`Runtime.logging_configuration` exposes `get(guild_id)` and `save(LoggingConfiguration)`.
The immutable value contains the full logging configuration. Save validates identifiers,
scope and positive Discord IDs before writing, then atomically replaces the guild's
configuration. Callers should edit a recently read snapshot; concurrent whole-configuration
saves are last-writer-wins. Stage 4 adds version-checked administration HTTP sections using this same contract;
see [Administration](administration.md). Direct full-value service saves remain last-writer-wins.

Migration `0003_logging` follows the unchanged `0001_core` and `0002_temporary_bans`:

| Table | Stored configuration |
| --- | --- |
| `moderation_logging` | Guild, enabled, nullable default channel |
| `moderation_logging_categories` | Guild/category destination override |
| `moderation_logging_events` | Guild/event enabled switch and nullable destination override |
| `moderation_message_logging` | Guild scope mode, include bots, include webhooks |
| `moderation_message_logging_channels` | Guild/channel membership in the active scope set |

Missing rows have deterministic application defaults, including for existing guilds:
logging enabled, no default channel, bots/webhooks excluded, `all_except_exclusions` with
an empty channel set. Defaults do not require backfilling one row per event. Foreign keys,
composite primary keys, positive channel checks, category and scope constraints preserve
relational invariants. The application rejects unknown event identifiers.

| Category | Events | Default |
| --- | --- | --- |
| Moderation | `warn`, `timeout_applied`, `timeout_removed`, `kick`, `ban`, `unban`, `purge` | On |
| Messages | `message_deleted`, `messages_bulk_deleted` | On |
| Members | `member_role_added`, `member_role_removed`, `member_nickname_changed` | Off |
| Server | `role_created`, `role_updated`, `role_deleted`, `channel_created`, `channel_updated`, `channel_deleted`, `permission_overwrite_changed` | Off |
| AutoMod | `automod_action_executed` | On |
| AutoMod | `automod_rule_created`, `automod_rule_updated`, `automod_rule_deleted` | Off |
| Message Logging | `message_sent`, `message_edited`, `message_deleted_content` | Off independently |

Logging state and command state are independent. Disabling a command never suppresses its
external audit family. The logging master switch controls all delivery; it does not affect
moderation actions or temporary-ban expiry. Disabling/re-enabling logging or Moderation
does not erase logging configuration. Configuration changes themselves are never audited.

## Routing and diagnostics

Logging is **Not Ready** without a usable default destination, even when an override is
configured. No channel is automatically selected, created or repaired. Moderation continues.

For each enabled event, routing tries the event override, category override, then default.
Only guild text and announcement channels in the same guild are accepted. Current effective
bot permissions must include `VIEW_CHANNEL`, `SEND_MESSAGES` and `EMBED_LINKS`; everyone,
combined role and member overwrites are respected. Invalid overrides fall back without
rewriting saved configuration. A send failure also permits fallback, covering races after
the permission check. Hikari handles its normal rate limits; there is no aggressive retry loop.

`LoggingDiagnosticsService.inspect(guild_id)` returns a typed status, each configured
destination's current health and unavailable optional capabilities. Statuses distinguish
disabled logging, missing/deleted destinations, unsupported channels, view/send/embed denial
and Discord unavailability. A valid override cannot conceal an unhealthy default. Health is
evaluated live, not stored as persistent Discord state. Delivery re-reads current settings,
including content scope, before sending queued work.

## Actions and Gateway observation

Successful Requiem actions emit `AuditEvent` values with their known actor, target, reason
and useful action details: warning DM outcome, timeout expiry, permanent/temporary ban,
message-history deletion interval, purge count/channel/filter. An expiry worker unban uses
the system actor `Requiem` and includes the original expiry and moderator. Failed actions
do not emit success; enqueue or delivery failure cannot fail an action or undo cleanup.

Gateway observers cover ban/unban, member role/nickname/timeout changes, role/channel CRUD,
permission-overwrite changes and AutoMod rules/actions. External actors are omitted. A member
departure only clears cache state: it is never identified as a kick. Before/after details
require reliable previous state; absent member state skips the diff, while role/channel
updates can state that previous state is unavailable. AutoMod execution includes rule,
action, user and available source IDs; matched content fragments are deliberately omitted.

Expected ban/unban/timeout/delete echoes are marked before REST, with at most 10,000 markers
and a 30-second TTL. Markers are consumed by matching Gateway events and removed on REST
failure where practical. Purge emits one application audit rather than duplicate basic
deletion logs. Optional deleted-content logging still runs independently. This is local,
best-effort correlation, not an actor-identification mechanism. Concurrent external changes,
ambiguous REST outcomes, late echoes or restart can cause a duplicate or suppress an
indistinguishable external echo. There is no persistent deduplication state.

## Intents and optional capabilities

The bot requests non-privileged `GUILDS`, `GUILD_MODERATION`, `GUILD_MESSAGES`,
`AUTO_MODERATION_CONFIGURATION` and `AUTO_MODERATION_EXECUTION` intents. The moderation
intent does not cause audit-log-entry subscription. AutoMod delivery additionally depends
on Discord's guild permissions and event availability.

`REQUIEM_MESSAGE_CONTENT_INTENT_ENABLED` and `REQUIEM_GUILD_MEMBERS_INTENT_ENABLED` both default
to false. Enable the corresponding capability in the Developer Portal before opting in.
Startup checks the current application's intent flags via REST. A missing grant or failed
preflight disables the optional capability for that run, preserving ordinary moderation.
Diagnostics reflect the effective runtime capabilities. Restart is needed after changing
operator flags/grants. Revocation after preflight can still interrupt the Gateway connection.

Without Message Content, full content events are non-operational; basic deletion metadata
and Requiem action audit continue. Without Members, external member/timeout diffs are
unavailable; Requiem's own timeout audit continues. No presence or voice intent is requested.

## Message scope and ephemeral state

Scope is either `all_except_exclusions` or `selected_channels_only`. The relational channel
set is interpreted as exclusions or selections respectively. Threads inherit their parent
channel's scope; an unresolved parent skips content logging. All configured destinations,
including event/category overrides and Message Logging destinations, are always excluded.
Requiem's own messages are excluded regardless of bot/webhook inclusion flags.

Basic single deletion embeds contain channel/message IDs, event time and cached author when
known, never content. Bulk deletion produces one basic summary. Author metadata does not
require Message Content. Deleted-content events use cached content or explicitly state
that content is unavailable when useful author metadata remains; deleted bodies are never fetched.

| State | Bound | TTL |
| --- | --- | --- |
| Message metadata | 10,000 entries | 1 hour |
| Content snapshots | 2,000 entries | 15 minutes |
| Member snapshots | 10,000 entries | 30 minutes |
| Edit chains | 5,000 source messages | 30 minutes |
| Expected echoes / recent deletion markers | 10,000 each | 30 seconds |

Caches evict oldest entries and expire during access and periodic maintenance. Content
retains at most 4,000 text characters and ten attachment metadata strings of at most 800
characters each. A content fingerprint detects edits beyond the retained prefix. Hikari's
general message/member caches are disabled; role/channel caches supply available old state.
Nothing is written to PostgreSQL or a filesystem archive. Attachments are represented by
filename, size, media type and original URL; they are never downloaded or rehosted, and URLs
may later expire. Restart loses content, previous member state and edit chains.

Each meaningful edit is a separate event, without debounce. Partial updates retain known
fields; missing fields do not mean deletion. The first edit log is standalone, the second
replies to the first, and subsequent edits reply to the previous log. A missing reply target,
changed destination, expired mapping or restart starts a fresh chain. Reply failure falls
back to a standalone embed.

## Delivery, presentation and limits

Independent queues/workers hold up to 1,000 high-priority audit events and 500 low-priority
content events. Low-priority overflow increments an aggregated warning counter; a full
high-priority queue emits an application error. High-priority enqueue never waits for the
low queue. At most 100 message create/update callbacks await ordered adaptation; excess
input is shed and counted. Basic deletion adaptation bypasses this wait. Recent deletion
markers prevent delayed low-priority work from restoring already-deleted cache entries.

Each delivery attempt has a 30-second deadline and channel health checks are bounded.
Hikari retains responsibility for REST rate limiting, including global limits shared by
all bot operations. Workers and periodic cache cleanup run in the bot process. Shutdown
cancels workers; queued events can be lost. This is not a durable queue and does not promise
delivery across outages or crashes. Bulk-delete counts reflect Discord-accepted IDs, as
documented for Stage 2. Ordinary message overload may also reduce available deletion metadata.

All output uses a centralized embed renderer and semantic colours for enforcement, changes,
information and restoration. Empty/unknown actor fields are omitted. Field counts, individual
lengths and the combined embed budget are bounded; truncation is visibly marked. One event
does not expand into a multi-message archive. Mentions, including reply pings, are disabled.
Application logs report event/guild IDs and failures without printing content or REST payloads.

## References and verification

The implementation uses locked Hikari 2.6.0 and hikari-arc 2.3.2. API assumptions were checked
against official [Gateway intents](https://docs.discord.com/developers/events/gateway),
[Gateway events](https://docs.discord.com/developers/events/gateway-events),
[application flags](https://docs.discord.com/developers/resources/application),
[message/reply/embed rules](https://docs.discord.com/developers/resources/message),
[permissions](https://docs.discord.com/developers/topics/permissions), and
[Hikari AutoMod events](https://docs.hikari-py.dev/en/stable/reference/hikari/events/auto_mod_events/),
alongside the installed library source and REST signatures.

Automated tests use fakes for Discord and disposable PostgreSQL for configuration/migrations.
They cover routing, permission denials, defaults, action integration, Gateway limitations,
echoes, content scope, filters, partial edits, reply chains, TTL bounds and queue overload.
Live Discord smoke testing still requires an operator-provided development guild and token.
No administration UI, audit history API, case database or unrelated module is included.
