"""Async OpenAI chat completions, guarded by the same policy as model selection."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, AsyncIterator, Optional

import httpx

from . import config
from .config import MAX_OUTPUT_TOKENS, REQUEST_TIMEOUT
from .model_policy import is_allowed_model

log = logging.getLogger("council.providers")

RETRY_STATUSES = {408, 409, 425, 429, 500, 502, 503, 504}
MAX_ATTEMPTS = 3
MAX_SSE_EVENT_CHARS = 1_000_000

_client: Optional[httpx.AsyncClient] = None


class ChatError(RuntimeError):
    """A safe error message suitable for a chat client, with no upstream details."""


def _provider_for(provider_name: str, model: str) -> dict[str, Any]:
    if not is_allowed_model(provider_name, model, config.PROVIDERS):
        raise ChatError("This OpenAI model is not available. Choose another model and try again.")
    # Selection and dispatch are separate checks: neither a stale panel nor a
    # direct title/chairman call can bypass the positive policy.
    choices = {(option["provider"], option["model"]) for option in config.model_options()}
    if (provider_name, model) not in choices:
        raise ChatError("This OpenAI model is not available. Choose another model and try again.")
    return config.PROVIDERS[provider_name]


def _get_client() -> httpx.AsyncClient:
    """One shared client so TLS connections are reused across the many calls of a debate."""
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(timeout=REQUEST_TIMEOUT)
    return _client


async def close_client() -> None:
    global _client
    if _client is not None and not _client.is_closed:
        await _client.aclose()
    _client = None


def _headers(provider: dict[str, Any]) -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    key = provider.get("api_key")
    if provider["auth"] == "bearer" and key:
        headers["Authorization"] = f"Bearer {key}"
    elif provider["auth"] == "api-key":
        headers["api-key"] = key or ""
    return headers


def _build_request(provider: dict[str, Any], model: str, system: str, user: str) -> tuple[str, dict[str, Any]]:
    return f"{provider['base_url'].rstrip('/')}/chat/completions", {
        "model": provider.get("model_deployments", {}).get(model, model),
        "max_completion_tokens": MAX_OUTPUT_TOKENS,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }


def _extract(provider: dict[str, Any], data: dict[str, Any], tag: str) -> Optional[str]:
    """Pull the assistant text out of a response and warn when it was cut off or empty."""
    choice = data["choices"][0]
    text = choice["message"].get("content") or ""
    if choice.get("finish_reason") == "length":
        log.warning("%s reply was truncated at MAX_OUTPUT_TOKENS=%s; raise it or shorten prompts", tag, MAX_OUTPUT_TOKENS)
    if not text.strip():
        log.warning("%s returned an empty completion (finish reason: %s)", tag, choice.get("finish_reason"))
        return None
    return text


async def chat(
    provider_name: str,
    model: str,
    system: str,
    user: str,
    timeout: float = REQUEST_TIMEOUT,
) -> Optional[str]:
    """Send one system+user exchange and return the assistant text, or None on failure.

    Retries transient HTTP errors with backoff. Failures are logged, not raised: the
    debate continues with the seats that answered.
    """
    try:
        provider = _provider_for(provider_name, model)
    except (ChatError, OSError, ValueError):
        log.error("Refused unavailable model %s/%s", provider_name, model)
        return None

    tag = f"{provider_name}/{model}"
    url, payload = _build_request(provider, model, system, user)
    client = _get_client()

    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            resp = await client.post(url, headers=_headers(provider), json=payload, timeout=timeout)
            if resp.status_code in RETRY_STATUSES and attempt < MAX_ATTEMPTS:
                delay = 2.0 * attempt
                log.warning("%s HTTP %s, retrying in %.0fs (attempt %d/%d)", tag, resp.status_code, delay, attempt, MAX_ATTEMPTS)
                await asyncio.sleep(delay)
                continue
            resp.raise_for_status()
            return _extract(provider, resp.json(), tag)
        except httpx.HTTPStatusError as e:
            log.error("%s HTTP %s", tag, e.response.status_code)
            return None
        except (httpx.TimeoutException, httpx.TransportError) as e:
            if attempt < MAX_ATTEMPTS:
                delay = 2.0 * attempt
                log.warning("%s %s, retrying in %.0fs (attempt %d/%d)", tag, type(e).__name__, delay, attempt, MAX_ATTEMPTS)
                await asyncio.sleep(delay)
                continue
            log.error("%s failed after %d attempts: %s", tag, MAX_ATTEMPTS, type(e).__name__)
            return None
        except Exception as e:  # noqa: BLE001 - graceful degradation by design
            log.error("%s failed: %s", tag, type(e).__name__)
            return None
    return None


async def _sse_data(response: httpx.Response) -> AsyncIterator[str]:
    """Read complete SSE data frames, including split and multiline frames."""
    lines: list[str] = []
    size = 0
    async for line in response.aiter_lines():
        if not line:
            if lines:
                yield "\n".join(lines)
                lines = []
                size = 0
        elif line.startswith("data:"):
            value = line[5:].removeprefix(" ")
            size += len(value)
            if size > MAX_SSE_EVENT_CHARS:
                raise ChatError("The model returned an invalid stream. Please try again.")
            lines.append(value)
    # A frame without its terminating blank line is incomplete; never treat it
    # as a successful final answer after an upstream connection drops.


async def stream_chat(
    provider_name: str,
    model: str,
    messages: list[dict[str, str]],
    timeout: float = REQUEST_TIMEOUT,
) -> AsyncIterator[str]:
    """Yield actual provider text deltas; never retry once text was emitted."""
    provider = _provider_for(provider_name, model)
    url = f"{provider['base_url'].rstrip('/')}/chat/completions"
    payload = {"model": provider.get("model_deployments", {}).get(model, model), "messages": messages, "stream": True, "max_completion_tokens": MAX_OUTPUT_TOKENS}
    client = _get_client()
    emitted = False
    nonempty = False
    tag = f"{provider_name}/{model}"
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            async with client.stream("POST", url, headers=_headers(provider), json=payload, timeout=timeout) as response:
                response.raise_for_status()
                async for data in _sse_data(response):
                    if data == "[DONE]":
                        if not nonempty:
                            raise ChatError("The model returned an empty response. Please try again.")
                        return
                    packet = json.loads(data)
                    if packet.get("error"):
                        raise ChatError("The model could not finish this response. Please try again.")
                    choices = packet.get("choices") or []  # Usage-only frames have no choices.
                    if not choices:
                        continue
                    choice = choices[0]
                    delta = choice.get("delta") or {}
                    text = delta.get("content") or delta.get("refusal")
                    if text:
                        if not isinstance(text, str):
                            raise ChatError("The model returned an invalid stream. Please try again.")
                        emitted = True
                        nonempty = nonempty or bool(text.strip())
                        yield text
                    reason = choice.get("finish_reason")
                    if reason == "stop":
                        if not nonempty:
                            raise ChatError("The model returned an empty response. Please try again.")
                        # This is the provider's terminal completion signal.
                        # Waiting for another frame can turn a complete answer
                        # into a false failure when the connection stays open.
                        return
                    elif reason == "length":
                        raise ChatError("The response reached its output limit. Send a follow-up to continue.")
                    elif reason is not None:
                        raise ChatError("The model could not finish this response. Please try again.")
                raise ChatError("The model connection ended before the response finished. Please try again.")
        except httpx.HTTPStatusError as error:
            status = error.response.status_code
            log.warning("%s streaming HTTP %s (attempt %d/%d)", tag, status, attempt, MAX_ATTEMPTS)
            if emitted or status not in RETRY_STATUSES or attempt == MAX_ATTEMPTS:
                raise ChatError("The model is unavailable right now. Please try again.") from None
        except (httpx.TimeoutException, httpx.TransportError) as error:
            log.warning("%s streaming %s (attempt %d/%d)", tag, type(error).__name__, attempt, MAX_ATTEMPTS)
            if emitted or attempt == MAX_ATTEMPTS:
                raise ChatError("The model connection was interrupted. Please try again.") from None
        except (ValueError, KeyError, TypeError, AttributeError):
            raise ChatError("The model returned an invalid stream. Please try again.") from None
        await asyncio.sleep(2.0 * attempt)


async def chat_many(calls: list[tuple[str, str, str, str]]) -> list[Optional[str]]:
    """Run several chat() calls in parallel. Each call is (provider, model, system, user)."""
    return await asyncio.gather(*(chat(*c) for c in calls))
