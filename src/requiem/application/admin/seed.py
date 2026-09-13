"""Explicit, guarded local fixture creation; never runs during application startup."""

import argparse
import asyncio

from requiem.bootstrap import build_runtime
from requiem.runtime import new_event_loop
from requiem.settings import Settings, load_settings


async def seed(settings: Settings, guild_id: int) -> None:
    if settings.environment != "development" or not settings.dev_auth_enabled:
        raise ValueError("Development seed requires development environment and dev auth enabled")
    runtime = build_runtime(settings)
    try:
        existing = await runtime.guilds.get(guild_id)
        if existing is not None:
            raise ValueError("Guild already exists; seed never changes an existing installation")
        await runtime.guilds.set_installed(guild_id, True)
    finally:
        await runtime.close()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Create one explicitly requested local development guild"
    )
    parser.add_argument("--guild-id", type=int, required=True)
    arguments = parser.parse_args()
    with asyncio.Runner(loop_factory=new_event_loop) as runner:
        runner.run(seed(load_settings(), arguments.guild_id))


if __name__ == "__main__":
    main()
