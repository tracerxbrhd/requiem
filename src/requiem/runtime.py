"""Event-loop factory compatible with Psycopg on Windows and Unix."""

import asyncio
import sys


def new_event_loop() -> asyncio.AbstractEventLoop:
    if sys.platform == "win32":
        loop = asyncio.SelectorEventLoop()
        asyncio.set_event_loop(loop)
        return loop
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    return loop
