"""SSE keepalives that leave a slow model request running between heartbeats."""

from __future__ import annotations

import asyncio
from typing import AsyncIterator

import anyio


async def with_heartbeats(source: AsyncIterator[str], interval: float = 15) -> AsyncIterator[str]:
    pending: asyncio.Task | None = None
    try:
        while True:
            if pending is None:
                pending = asyncio.create_task(anext(source))
            done, _ = await asyncio.wait({pending}, timeout=interval)
            if not done:
                yield ": heartbeat\n\n"
                continue
            completed, pending = pending, None
            try:
                yield completed.result()
            except StopAsyncIteration:
                break
    finally:
        # Starlette cancels its AnyIO scope on disconnect. Shield cleanup so the
        # child model request finishes cancelling and its persistence finally runs.
        with anyio.CancelScope(shield=True):
            if pending is not None:
                pending.cancel()
                await asyncio.gather(pending, return_exceptions=True)
            await source.aclose()
