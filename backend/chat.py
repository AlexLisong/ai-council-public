"""Single-assistant settings and bounded, ordinary multi-turn chat history."""

from __future__ import annotations

from typing import Any

from . import config, discussion
from .discussion import HistoryLimitError, previous_settings

CHAT_SYSTEM = "You are a helpful AI assistant. Answer clearly and accurately, acknowledge uncertainty, and use Markdown when it improves readability."
TITLE_WAIT_SECONDS = 2.0


def fallback_title(content: str) -> str:
    title = " ".join(content.split())
    return title[:47] + "..." if len(title) > 50 else title


def prepare_chat_history(messages: list[dict[str, Any]], contribution: str) -> tuple[list[dict[str, str]], int]:
    human_turns = sum(message.get("role") == "user" for message in messages)
    if human_turns >= discussion.MAX_HUMAN_TURNS:
        raise HistoryLimitError(f"A chat supports up to {discussion.MAX_HUMAN_TURNS} human turns. Start a new chat to continue.")
    history = [{"role": "system", "content": CHAT_SYSTEM}]
    for message in messages:
        role = message.get("role")
        if role == "user":
            history.append({"role": "user", "content": message["content"]})
        elif role == "assistant":
            content = message.get("content") or (message.get("final") or {}).get("response")
            if content:
                history.append({"role": "assistant", "content": content})
    history.append({"role": "user", "content": contribution})
    if sum(len(message["content"]) for message in history) > discussion.MAX_CONTEXT_CHARS:
        raise HistoryLimitError("This chat is too long to continue safely. Start a new chat with a summary of the important points.")
    return history, human_turns + 1


def resolve_chat_config(messages: list[dict[str, Any]], provider: str | None, model: str | None) -> dict[str, str]:
    options = config.model_options()
    if (provider is None) != (model is None):
        raise ValueError("Choose both a provider and a model")
    if provider is not None:
        for option in options:
            if (provider, model) == (option["provider"], option["model"]):
                return {"mode": "chat", **option}
        raise ValueError("The selected OpenAI model is not an available configured choice")
    prior = previous_settings(messages)
    for option in options:
        if (prior.get("provider"), prior.get("model")) == (option["provider"], option["model"]):
            return {"mode": "chat", **option}
    default = config.chat_default(options=options)
    if default is None:
        raise ValueError("No OpenAI chat model is configured on this server")
    return {"mode": "chat", **default}
