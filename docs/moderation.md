# Moderation

Stage 2 implements seven global, top-level slash commands. Required arguments use
`<value>` below; optional arguments use `[value]`. Confirmations, errors and automatic
deferred responses are ephemeral. No command is hidden by per-guild module settings or
`default_member_permissions`.

| Syntax | Native permission for actor and bot |
| --- | --- |
| `/warn member:<member> reason:<text>` | None; target safety and hierarchy still apply |
| `/timeout member:<member> duration:<duration> reason:[text]` | `MODERATE_MEMBERS` |
| `/untimeout member:<member> reason:[text]` | `MODERATE_MEMBERS` |
| `/kick member:<member> reason:[text]` | `KICK_MEMBERS` |
| `/ban user:<user> duration:[duration] delete_messages:[duration] reason:[text]` | `BAN_MEMBERS` |
| `/unban user_id:<snowflake> reason:[text]` | `BAN_MEMBERS` |
| `/purge amount:<1-100> member:[member] channel:[channel] reason:[text]` | `MANAGE_MESSAGES` in the affected channel |

## Access and target safety

Every command first uses the shared Core hook: guild context, enabled Moderation module,
enabled command, then an allowed Requiem role. Owner and Administrator do not bypass
these checks. Commands remain registered when disabled. Configuration defaults to disabled
and an empty allowed-role set denies access.

Use the existing `Runtime.configuration` application service to enable `moderation` and
set its allowed roles (`set_module_enabled`, `set_module_roles`). Command overrides use
`set_command_enabled`, `set_command_access_mode` and `set_command_custom_roles`.
No configuration HTTP endpoint or Discord configuration command is added in this stage.

The Moderation service then checks fresh native permissions and hierarchy. Self, bot and
owner targets are protected. Member targets must be strictly below both actor and bot.
Ordering uses role position with Discord's ID tie-break, with everyone at the bottom.
Guild owner bypasses only the actor's native permission/hierarchy checks; Administrator
bypasses native permission bits, but not hierarchy. Bot hierarchy is never bypassed.
Non-member bans skip member hierarchy, while still checking permissions and protected IDs.
Permission snapshots and REST actions are not atomic; Discord also enforces bot authority
at execution time, and concurrent role changes can cause a request to fail.

## Inputs and command behaviour

Durations accept positive integers with case-insensitive `s`, `m`, `h`, `d`, `w` units,
including compounds such as `1d12h`. Fractions, spaces, negatives, zero and overflow are
rejected. Only `delete_messages` allows zero; its default is zero and maximum is `7d`.
Discord receives `delete_message_seconds`, not the deprecated day field.

Timeout uses native Discord timeout with a maximum of `28d`. Owner and Administrator
targets are rejected. Untimeout reports when there is no active timeout. Kick is permanent
removal from the server, without a scheduled action.

Reasons are required for warn and optional elsewhere. The shared validator preserves the
supplied text without truncation, rejects empty/control-character input, and conservatively
limits the percent-encoded UTF-8 representation to 512 characters. Consequently Unicode
and reserved characters consume more of the limit than plain ASCII. Eligible native
administrative endpoints receive the reason as their Discord audit-log reason.

Warn attempts a DM naming the server and reason, with mention parsing disabled. Closed DMs
or a Discord failure do not fail the warning; the moderator is told delivery failed.
Warnings do not create persistent history, cases, counters or strikes.

Unban accepts a decimal user ID in `1..2^63-1` without leading zeros. It checks the current
ban before reporting success. A confirmed missing ban also removes stale expiry state.

## Purge

The default channel is the invoking channel; an explicit channel selects the affected
channel. V1 supports guild text and announcement channels, excluding threads, forums,
categories and DMs. Actor requires visibility and `MANAGE_MESSAGES`; bot additionally
requires `READ_MESSAGE_HISTORY`. Effective permissions account for everyone, combined role
and member overwrites in the selected channel, including Administrator/owner semantics.

Purge selects up to the requested amount, with optional author filtering. It scans at most
10 pages of 100 messages, stopping at exhausted or too-old history. It excludes ephemeral
and known non-deletable message types. Messages must be newer than two weeks, with a
one-minute safety margin checked again before deletion. One result uses an individual
delete; 2–100 results use bulk deletion. Older messages never trigger mass individual
deletes. No eligible matches gives an explicit error.

The confirmation counts eligible IDs accepted by Discord. Discord's bulk endpoint does
not return a per-message deletion count; concurrent deletion by another moderator cannot
be distinguished from deletion by this request. A failed/partial REST request returns an
error rather than claiming the whole selected set was deleted.

## Durable temporary bans

Migration `0002_temporary_bans` adds one operational record per `(guild_id, user_id)` with
expiry, next retry, creation timestamp, actor and optional reason. It contains no generic
moderation history. The foundation migration remains unchanged.

A temporary-ban intent is committed **before** the Discord ban request. Success therefore
has a durable reversal obligation; a crash or ambiguous REST failure leaves recoverable
expiry state. Re-tempban replaces the single authoritative expiry. Permanent ban performs
the native ban and then removes old expiry before acknowledging success. Manual Requiem
unban likewise removes expiry before acknowledging success.

Commands and expiry hold a PostgreSQL transaction-scoped advisory lock for the guild/user
across their database commits and REST work. The lock uses a separate connection so intent
commits are durable before the native action. Concurrent work for that target returns a
short busy response; independent targets can proceed. Expiry re-reads the record after
locking, preventing a previously selected stale expiry from undoing a completed replacement.

The worker runs in the bot process, ticks immediately after gateway startup and polls every
15 seconds after each batch. Each batch takes at most 50 due records; each Discord expiry
attempt is bounded to 30 seconds. Successful unban or a confirmed Unknown Ban removes the
record. Other failures retain it and delay retry by one minute. Missing guild/access is not
treated as successful cleanup. Cancellation leaves unfinished records for the next startup.
Module disable and installation flags do not block these already committed obligations.
Expiry requires the bot, database and Discord access to be available; it may run late during
outages or a backlog. Deleting the database or its volume loses the obligations.

Discord and PostgreSQL cannot share a transaction. If permanent conversion reaches Discord
but clearing the old expiry fails or the process crashes, no success is acknowledged and
the old expiry remains, favouring reversal over an accidentally permanent punishment.
A temporary request with an uncertain outcome can similarly leave an expiry for a ban
that was never created. A confirmed absent ban completes that obligation. Network partitions
and delayed remote completion cannot provide absolute cross-system ordering guarantees.

Discord does not expose a ban version/creation token that identifies each replacement.
An administrator who unbans and re-bans directly through Discord may therefore have that
new ban removed by an old Requiem expiry. Make managed lifecycle changes through Requiem;
do not assume native changes automatically cancel the pending record.

## Verified API references

Implementation was checked against installed Hikari 2.6.0 and hikari-arc 2.3.2, and the
official [guild endpoints](https://docs.discord.com/developers/resources/guild),
[permissions](https://docs.discord.com/developers/topics/permissions),
[message endpoints](https://docs.discord.com/developers/resources/message),
[audit reasons](https://docs.discord.com/developers/resources/audit-log),
[Hikari REST API](https://docs.hikari-py.dev/en/stable/reference/hikari/api/rest/) and
[Arc options](https://arc.hypergonial.com/guides/options/).

No audit embeds, audit-event listeners, message logging, Message Content intent, case system
or moderation HTTP action endpoints are implemented in this stage.
