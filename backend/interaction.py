"""Single-worker run ownership and durable, timed opportunities for human input."""

from __future__ import annotations

import asyncio
import threading
from datetime import datetime, timedelta, timezone
from typing import Any, AsyncIterator, Callable

import anyio
from fastapi import HTTPException
from fastapi.responses import StreamingResponse

from .discussion import DiscussionContext

INPUT_WAIT_SECONDS = 300


class RunController:
    def __init__(self, assistant: dict[str, Any], discussion: DiscussionContext | None, save: Callable[[], None]):
        self.assistant = assistant
        self.discussion = discussion
        self.save = save
        self.waiting: dict[str, Any] | None = None
        self._wake = asyncio.Event()
        self._expires = 0.0
        self._reason: str | None = None
        self._accepted: dict[str, Any] | None = None

    def submit(self, content: str | None, skip: bool) -> dict[str, Any]:
        if self.discussion is None or self.waiting is None or asyncio.get_running_loop().time() >= self._expires:
            raise HTTPException(status_code=409, detail="The council is not waiting for input. Keep your thought and send it after the current round or final answer.")
        thought = None
        if not skip:
            thought = {
                "after_round": self.waiting["after_round"], "content": content,
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            self.discussion.render(extra_input=thought)  # Check the full future prompt before accepting it.
            self.assistant["human_inputs"].append(thought)
        waiting = self.waiting
        self.assistant["waiting_for_input"] = None
        try:
            self.save()  # Save the thought before allowing the model calls to resume.
        except Exception:
            if thought is not None:
                self.assistant["human_inputs"].pop()
            self.assistant["waiting_for_input"] = waiting
            raise
        self.waiting = None
        self._accepted = thought
        self._reason = "skip" if skip else "input"
        self._wake.set()
        return {"accepted": True, "input": thought, "reason": self._reason}

    async def pause_after(self, after_round: int) -> AsyncIterator[dict[str, Any]]:
        self._wake.clear()
        self._reason = None
        self._accepted = None
        self._expires = asyncio.get_running_loop().time() + INPUT_WAIT_SECONDS
        waiting = {
            "after_round": after_round,
            "deadline": (datetime.now(timezone.utc) + timedelta(seconds=INPUT_WAIT_SECONDS)).isoformat(),
        }
        self.waiting = waiting
        self.assistant["waiting_for_input"] = waiting
        self.save()
        try:
            yield {"type": "awaiting_input", "data": waiting}
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=max(0, self._expires - asyncio.get_running_loop().time()))
            except asyncio.TimeoutError:
                pass
            self.waiting = None
            self.assistant["waiting_for_input"] = None
            self.save()
            if self._accepted is not None:
                yield {"type": "input_received", "data": self._accepted}
            yield {"type": "round_resumed", "data": {"after_round": after_round, "reason": self._reason or "timeout"}}
        finally:
            self.waiting = None
            self.assistant["waiting_for_input"] = None


class RunLease:
    def __init__(self, registry: ActiveRuns, conversation_id: str, controller: RunController):
        self.registry = registry
        self.conversation_id = conversation_id
        self.controller = controller

    def release(self) -> None:
        with self.registry._lock:
            # A late response cleanup must not release a newer run's lease.
            if self.registry._runs.get(self.conversation_id) is self:
                del self.registry._runs[self.conversation_id]


class ActiveRuns:
    def __init__(self):
        self._runs: dict[str, RunLease] = {}
        self._lock = threading.Lock()

    def get(self, conversation_id: str) -> RunLease | None:
        with self._lock:
            return self._runs.get(conversation_id)

    def acquire(self, conversation_id: str, controller: RunController) -> RunLease:
        with self._lock:
            if conversation_id in self._runs:
                raise HTTPException(status_code=409, detail="A debate is already running in this conversation.")
            lease = RunLease(self, conversation_id, controller)
            self._runs[conversation_id] = lease
            return lease


class RunStreamingResponse(StreamingResponse):
    def __init__(self, *args, lease: RunLease, **kwargs):
        super().__init__(*args, **kwargs)
        self.lease = lease

    async def __call__(self, scope, receive, send):
        try:
            await super().__call__(scope, receive, send)
        finally:
            try:
                with anyio.CancelScope(shield=True):
                    await self.body_iterator.aclose()
            finally:
                self.lease.release()
