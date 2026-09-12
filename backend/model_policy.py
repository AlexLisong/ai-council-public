"""Positive OpenAI model and endpoint policy, independent of user configuration.

Speaking the OpenAI protocol does not establish a model's origin. New model IDs
must be verified and added here before use. Deployment names belong in private
server configuration, never in the public model catalog.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlsplit


OPENAI_MODELS = frozenset({
    "gpt-4", "gpt-4-0613", "gpt-4-turbo", "gpt-4-turbo-2024-04-09",
    "gpt-4o", "gpt-4o-2024-05-13", "gpt-4o-2024-08-06", "gpt-4o-2024-11-20",
    "gpt-4o-mini", "gpt-4o-mini-2024-07-18", "chatgpt-4o-latest",
    "gpt-4.1", "gpt-4.1-2025-04-14", "gpt-4.1-mini", "gpt-4.1-mini-2025-04-14",
    "gpt-4.1-nano", "gpt-4.1-nano-2025-04-14",
    "gpt-5", "gpt-5-2025-08-07", "gpt-5-mini", "gpt-5-mini-2025-08-07",
    "gpt-5-nano", "gpt-5-nano-2025-08-07", "gpt-5-chat-latest",
    "gpt-5.1", "gpt-5.1-2025-11-13", "gpt-5.1-chat-latest",
    "gpt-5.2", "gpt-5.2-2025-12-11", "gpt-5.2-chat-latest",
    "gpt-5.3-chat-latest", "gpt-5.4", "gpt-5.4-mini", "gpt-5.4-nano",
    "gpt-5.5", "gpt-5.6-sol", "gpt-5.6-terra", "gpt-5.6-luna", "gpt-6-astra",
    "o1", "o1-2024-12-17", "o1-mini", "o1-mini-2024-09-12",
    "o3", "o3-2025-04-16", "o3-mini", "o3-mini-2025-01-31",
    "o4-mini", "o4-mini-2025-04-16",
})


def is_openai_model(provider_name: str, model: str) -> bool:
    if provider_name == "foundry-openai":
        return model in OPENAI_MODELS
    if provider_name == "openai":
        return model in OPENAI_MODELS
    if provider_name == "openrouter" and model.startswith("openai/"):
        return model.removeprefix("openai/") in OPENAI_MODELS
    return False


def is_trusted_endpoint(provider_name: str, provider: dict[str, Any]) -> bool:
    """Prevent a compatible proxy or overridden base URL bypassing the policy."""
    try:
        url = urlsplit(provider.get("base_url", ""))
        if (
            url.scheme != "https" or url.port not in {None, 443}
            or url.username or url.password or url.query or url.fragment
        ):
            return False
        path = url.path.rstrip("/")
        if provider_name == "openai":
            return url.hostname == "api.openai.com" and path == "/v1"
        if provider_name == "openrouter":
            return url.hostname == "openrouter.ai" and path == "/api/v1"
        if provider_name == "foundry-openai":
            return bool(re.fullmatch(r"[a-z0-9-]+\.openai\.azure\.com", url.hostname or "")) and path == "/openai/v1"
    except (TypeError, ValueError):
        pass
    return False


def is_allowed_model(provider_name: str, model: str, providers: dict[str, dict[str, Any]]) -> bool:
    provider = providers.get(provider_name)
    return provider is not None and is_openai_model(provider_name, model) and is_trusted_endpoint(provider_name, provider)
