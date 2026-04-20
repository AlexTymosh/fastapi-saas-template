from __future__ import annotations

import asyncio
import selectors
import sys
from collections.abc import Awaitable
from typing import TypeVar


def _loop_factory():
    if sys.platform == "win32":
        return asyncio.SelectorEventLoop(selectors.SelectSelector())
    return asyncio.new_event_loop()


T = TypeVar("T")


def run_async(awaitable: Awaitable[T]) -> T:
    return asyncio.run(awaitable, loop_factory=_loop_factory)
