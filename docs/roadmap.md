# Requiem Roadmap

This document tracks the major development stages of Requiem and gives a little more context than the overview in the main README.

## Overview

| Stage | Area | Status |
| --- | --- | --- |
| 1 | Foundation | ✅ Completed |
| 2 | Moderation | ✅ Completed |
| 3 | Audit & Logging | ✅ Completed |
| 4 | Administration Platform | ✅ Completed |
| 4.1 | Hardening | 🚧 In Progress |
| 5 | Operational Workflows | 📋 Planned |
| 6 | Automation & Lifecycle | 📋 Planned |
| 7 | Extended Modules | 📋 Planned |

---

## Stage 1 — Foundation

**Status:** Completed

The first stage built the common base that every later Requiem system relies on.

### What it added

- modular monolith structure;
- clear separation between Discord transport, application logic, domain logic and persistence;
- persistent guild configuration;
- module and command access control;
- PostgreSQL persistence;
- Alembic migrations;
- separate Discord bot and HTTP API runtimes;
- structured configuration and logging;
- Docker development and runtime setup;
- automated backend checks and tests.

This stage was intentionally about infrastructure rather than visible features. The point was to avoid every future module inventing its own configuration, persistence and runtime conventions.

See [Architecture & Configuration](architecture.md) and [Foundation Verification](foundation-verification.md).

---

## Stage 2 — Moderation

**Status:** Completed

Moderation became the first real operational module built on top of the shared core.

### What it added

- warnings;
- timeouts and timeout removal;
- kicks;
- permanent bans;
- temporary bans;
- unbanning;
- filtered message purging;
- Discord permission checks;
- role-hierarchy checks;
- persistent temporary-ban expiry.

Temporary bans were also the first feature where Requiem had to remember an operational obligation after the original command had finished. That behaviour became an important pattern for later lifecycle systems.

See [Moderation](moderation.md).

---

## Stage 3 — Audit & Logging

**Status:** Completed

Stage 3 added Requiem's own operational visibility instead of depending on Discord's Audit Log for application state.

### What it added

- moderation audit events;
- configurable logging categories;
- configurable destinations;
- selected external Discord event observation;
- optional Message Logging;
- routing and fallback between destinations;
- logging diagnostics;
- bounded runtime caches;
- bounded delivery queues.

Discord's native Audit Log is still left alone. Requiem only keeps the context it needs for its own operations and logging.

See [Audit & Logging](audit-logging.md).

---

## Stage 4 — Administration Platform

**Status:** Completed

Stage 4 added the web configuration layer.

The dashboard is for configuring Requiem. It is not intended to replace Discord as the place where moderators actually work.

### What it added

- React administration frontend;
- Discord OAuth authentication;
- guild selection;
- bot installation flow;
- Moderation configuration;
- command configuration;
- role access configuration;
- Audit & Logging configuration;
- Message Logging configuration;
- Discord role and channel metadata;
- configuration revision checks;
- responsive administration UI;
- local development authentication.

See [Administration Platform](administration.md).

---

## Stage 4.1 — Hardening

**Status:** In Progress

Stage 4.1 is a cleanup and hardening pass before the next major product stage.

It does not introduce a new module. The focus is making the existing platform more predictable, easier to maintain and more convincing to inspect from the outside.

### Current work

- hardening Administration Platform Discord requests;
- bounded role, channel and guild metadata caching;
- deduplicating concurrent upstream requests;
- clearer Discord rate-limit behaviour;
- partial-loading and retry handling;
- regression coverage;
- backend and frontend CI;
- repository presentation;
- README redesign;
- visible repository status badges;
- roadmap documentation;
- general repository trust and maintainability work.

### Done when

Stage 4.1 is complete when the current platform has a reliable automated quality baseline, the Administration Platform behaves predictably under common Discord/API failure cases, and the public repository accurately represents the state of the project.

---

## Stage 5 — Operational Workflows

**Status:** Planned

This is where Requiem starts moving beyond individual administrative actions and into complete workflows.

The focus will be on operations that currently require an administrator to coordinate several Discord changes by hand.

### Planned direction

- multi-step administrative operations;
- persistent operation state;
- ownership and attribution;
- reasons and operational context;
- clear operation lifecycle;
- coordinated Discord changes;
- rollback and restoration where practical;
- recovery after partial failures or restarts.

Incident-oriented administration is one possible system for this stage, but the stage is broader than a single feature.

---

## Stage 6 — Automation & Lifecycle

**Status:** Planned

Stage 6 extends the workflow model into systems that can manage themselves over time.

### Planned direction

- scheduled operations;
- temporary resources;
- temporary access;
- automatic expiration;
- restoration of previous state;
- server policies;
- administrative presets;
- recurring administrative tasks;
- lifecycle-aware resources;
- rule-driven operational automation.

The goal is useful server administration automation, not a generic event-action builder.

---

## Stage 7 — Extended Modules

**Status:** Planned

Once the core management platform is mature, Requiem can support optional systems that sit outside its main administrative role.

Possible areas include:

- Community;
- Economy;
- Games.

These modules should stay optional and isolated from the core architecture. They should only be added when they solve a real server use case without turning Requiem into a generic multipurpose bot.
