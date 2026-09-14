<div align="center">

<img src="media/requiem.jpg" alt="Requiem" width="180">

# Requiem

**A stateful management and automation layer for Discord communities.**

[![Quality](https://github.com/tracerxbrhd/requiem/actions/workflows/ci.yaml/badge.svg)](https://github.com/tracerxbrhd/requiem/actions/workflows/ci.yaml)
![Python](https://img.shields.io/badge/Python-3.13-blue)
![License](https://img.shields.io/badge/license-source--available-purple)
![Status](https://img.shields.io/badge/status-active%20development-orange)

</div>

## What is Requiem?

Requiem is a Discord server management and automation platform built around one idea: Discord should keep doing what Discord already does well, while Requiem handles the workflows around it.

Roles, channels, permissions, AutoMod and native moderation remain Discord's responsibility. Requiem sits above those primitives and adds the things that are harder to manage manually — persistent state, multi-step operations, temporary actions, configuration and lifecycle management.

The goal is not to collect as many commands as possible. Requiem is meant to make recurring administrative work more consistent, easier to reason about and safer to recover from when something goes wrong.

## Why Requiem?

### Operations over primitive commands

A command should represent an administrative goal, not just expose another Discord API call.

Where it makes sense, Requiem combines several low-level actions into one operation and keeps enough context to understand what happened afterwards.

### Stateful workflows

Some operations do not end when the interaction finishes.

Requiem can retain the state needed to continue, expire or restore an operation later — including who started it, why it exists and when it should end.

### Reversible administration

Temporary changes should not rely on someone remembering to undo them.

When Discord gives us enough information to do so safely, Requiem keeps the state required to reverse or complete an operation later.

### Discord-native first

Requiem is not trying to replace Discord's own systems.

Native roles, channels, permissions, AutoMod and moderation remain authoritative. Requiem uses them as building blocks and adds coordination where Discord does not provide the whole workflow.

## Current Capabilities

### Core Platform

The shared core currently provides:

- persistent per-server configuration;
- module and command access control;
- PostgreSQL-backed operational state;
- separate Discord bot and HTTP API runtimes;
- migration-driven persistence;
- structured logging and configuration;
- containerized development and runtime environments.

### Moderation

The Moderation module currently covers:

- warnings;
- timeouts and timeout removal;
- kicks;
- permanent and temporary bans;
- unbanning;
- filtered message purging;
- Discord permission and role-hierarchy checks.

Temporary bans survive restarts and keep their expiry obligation until Requiem can safely complete it.

### Audit & Logging

Requiem has its own operational logging layer instead of treating Discord's Audit Log as application state.

It currently supports:

- audit events for Requiem moderation actions;
- configurable event categories and destinations;
- selected external Discord event observation;
- optional Message Logging;
- per-server routing and diagnostics.

Discord's own Audit Log is left intact, and native audit reasons are still used where appropriate.

### Administration Platform

The web administration platform is focused on configuration rather than day-to-day moderation.

It currently provides:

- Discord OAuth authentication;
- server selection and installation flow;
- Moderation configuration;
- command and role access settings;
- Audit & Logging configuration;
- Message Logging configuration;
- live role and channel metadata;
- protection against stale configuration writes;
- a responsive administration interface.

Moderation itself still happens in Discord.

## Roadmap

```mermaid
flowchart LR
    F["Foundation"]
    M["Moderation"]
    L["Audit & Logging"]
    A["Administration"]
    H["Hardening"]
    O["Operational Workflows"]
    AU["Automation & Lifecycle"]
    E["Extended Modules"]

    F --> M --> L --> A --> H --> O --> AU --> E

    class F,M,L,A completed
    class H active
    class O,AU,E planned

    classDef completed fill:#2f2850,stroke:#8b7cff,stroke-width:2px,color:#ffffff
    classDef active fill:#4a356d,stroke:#b995ff,stroke-width:3px,color:#ffffff
    classDef planned fill:#24222b,stroke:#66616f,stroke-width:1px,color:#c6c2cd
```

See the [detailed roadmap](docs/roadmap.md).

## Documentation

More detailed technical and operational documentation lives in `docs/`:

- [Administration Platform](docs/administration.md)
- [Architecture & Configuration](docs/architecture.md)
- [Audit & Logging](docs/audit-logging.md)
- [Development & Docker](docs/development.md)
- [Moderation](docs/moderation.md)
- [Foundation Verification](docs/foundation-verification.md)
- [Roadmap](docs/roadmap.md)

## Technology

**Python 3.13 · Hikari · hikari-arc · FastAPI · PostgreSQL · SQLAlchemy · Alembic · React · TypeScript · Docker**

Backend and frontend checks run through GitHub Actions, including linting, formatting, type checking, tests and the production frontend build.

## Project Status

Requiem is under active development.

The foundation, Moderation, Audit & Logging and the Administration Platform are already implemented. The current work is focused on hardening those systems and improving the repository baseline before moving on to larger operational workflows.

## License

Requiem is **proprietary source-available software**, not open-source software.

Public access to this repository does not grant permission to deploy, modify, redistribute or self-host Requiem except where permitted by the [LICENSE](LICENSE), applicable law or GitHub's Terms of Service.
