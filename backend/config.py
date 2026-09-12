"""Configuration: providers from environment, council seats from council.config.json."""

from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from .model_policy import OPENAI_MODELS, is_allowed_model, is_trusted_endpoint

load_dotenv()

log = logging.getLogger("council.config")

ROOT_DIR = Path(__file__).resolve().parent.parent
COUNCIL_CONFIG_PATH = Path(os.getenv("COUNCIL_CONFIG", ROOT_DIR / "council.config.json"))
_data_dir = Path(os.getenv("DATA_DIR", "data/conversations"))
DATA_DIR = str(_data_dir if _data_dir.is_absolute() else ROOT_DIR / _data_dir)

DB_PATH = str(ROOT_DIR / os.getenv("DB_PATH", "data/council.db")) if not Path(os.getenv("DB_PATH", "data/council.db")).is_absolute() else os.getenv("DB_PATH")
# Azure App Service's persistent /home share does not support WAL shared memory.
SQLITE_JOURNAL_MODE = os.getenv("SQLITE_JOURNAL_MODE", "WAL").upper()
if SQLITE_JOURNAL_MODE not in {"WAL", "DELETE"}:
    raise ValueError("SQLITE_JOURNAL_MODE must be WAL or DELETE")

# Accounts
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD")  # required to create the first administrator
ALLOW_SIGNUP = os.getenv("ALLOW_SIGNUP", "true").lower() not in {"0", "false", "no"}
SESSION_DAYS = int(os.getenv("SESSION_DAYS", "30"))
HOST = os.getenv("HOST", "127.0.0.1")
PORT = int(os.getenv("PORT", "8001"))

DEFAULT_MAX_ROUNDS = 3
DEFAULT_CONSENSUS = "all"  # "all" | "majority" | fraction string like "2/3" | float 0-1
REQUEST_TIMEOUT = float(os.getenv("REQUEST_TIMEOUT", "360"))
MAX_OUTPUT_TOKENS = int(os.getenv("MAX_OUTPUT_TOKENS", "8192"))


def foundry_deployments() -> dict[str, str]:
    """Map public OpenAI model IDs to operator-verified, private Azure deployments."""
    try:
        mapping = json.loads(os.getenv("FOUNDRY_DEPLOYMENT_MAP", "{}"))
        if not isinstance(mapping, dict) or any(
            model not in OPENAI_MODELS or not isinstance(deployment, str)
            or not re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", deployment)
            for model, deployment in mapping.items()
        ):
            raise ValueError
    except (ValueError, TypeError):
        raise ValueError("FOUNDRY_DEPLOYMENT_MAP must map approved OpenAI model IDs to Azure deployment names") from None
    return mapping


def build_providers() -> dict[str, dict[str, Any]]:
    """Return the provider registry available on this machine, keyed by name.

    Every provider speaks the OpenAI chat-completions protocol:
    {"base_url": str, "api_key": str|None, "auth": "bearer" | "api-key"}.
    Only providers whose credentials are present are registered. This project runs
    OpenAI models only; Anthropic and other partner-model routes are not offered.
    """
    providers: dict[str, dict[str, Any]] = {}

    foundry_resource = os.getenv("FOUNDRY_RESOURCE")
    foundry_key = os.getenv("FOUNDRY_API_KEY")
    if foundry_resource and foundry_key:
        # Azure Foundry / Azure OpenAI: the model id is the deployment name.
        providers["foundry-openai"] = {
            "base_url": f"https://{foundry_resource}.openai.azure.com/openai/v1",
            "api_key": foundry_key,
            "auth": "api-key",
            "model_deployments": foundry_deployments(),
        }

    if os.getenv("OPENROUTER_API_KEY"):
        providers["openrouter"] = {
            "base_url": "https://openrouter.ai/api/v1",
            "api_key": os.getenv("OPENROUTER_API_KEY"),
            "auth": "bearer",
        }

    if os.getenv("OPENAI_API_KEY"):
        providers["openai"] = {
            "base_url": os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"),
            "api_key": os.getenv("OPENAI_API_KEY"),
            "auth": "bearer",
        }

    # A compatible protocol alone cannot establish that the endpoint serves
    # OpenAI models. Generic custom/Ollama routes are deliberately not registered.
    return {name: provider for name, provider in providers.items() if is_trusted_endpoint(name, provider)}


PROVIDERS = build_providers()

# Providers this project no longer offers. Any seat or chairman still pointing at one
# (older saved panels, discussion snapshots, stale config) is moved to the replacement
# so follow-ups keep working.
RETIRED_PROVIDERS = frozenset({"foundry-anthropic", "anthropic"})
RETIRED_MODEL_PREFIXES = (
    "claude", "anthropic/", "google/", "gemini", "x-ai/", "grok", "mistralai/", "mistral",
    "meta-llama/", "llama", "deepseek", "cohere/", "command", "qwen", "moonshotai/", "kimi",
)
REPLACEMENT_MODEL = {
    "provider": os.getenv("REPLACEMENT_PROVIDER", "foundry-openai"),
    "model": os.getenv("REPLACEMENT_MODEL", "gpt-6-astra"),
}
# Preset keys that were renamed; old discussions and links keep working.
PRESET_ALIASES = {"openrouter-frontier": "openai-direct"}
# Extra selectable, positively identified OpenAI models on trusted providers:
# EXTRA_MODELS="openai:gpt-4.1-mini,openrouter:openai/gpt-5.1"
EXTRA_MODELS = [
    tuple(item.split(":", 1)) for item in os.getenv("EXTRA_MODELS", "").split(",") if ":" in item
]


def is_retired(member: dict[str, Any]) -> bool:
    """True for providers/models this project explicitly stopped offering (denylist)."""
    provider = str(member.get("provider", "")).strip().lower()
    model = str(member.get("model", "")).strip().lower()
    return provider in RETIRED_PROVIDERS or model.startswith(RETIRED_MODEL_PREFIXES)


def replacement_available(options: list[dict[str, str]] | None = None) -> bool:
    options = model_options() if options is None else options
    return any(o["provider"] == REPLACEMENT_MODEL["provider"] and o["model"] == REPLACEMENT_MODEL["model"] for o in options)


def retire_models(definition: dict[str, Any], *, offered_only: bool = False) -> list[str]:
    """Rewrite provider/model pairs this project does not offer, in place.

    By default only explicitly retired pairs (see `is_retired`) are replaced; that is the
    conservative rule used for durable data. With `offered_only=True` every pair that is
    not in `model_options()` is replaced as well, which is the allowlist rule applied at
    the moment a run starts so that only configured OpenAI models are ever called.

    Nothing is rewritten unless the replacement itself is a configured, selectable model;
    in that case the definition is left alone and an error is logged, so the panel stays
    "unavailable" (recoverable) instead of being pointed at something that cannot run.
    Returns one "name: old -> new" line per change. The old pair is kept as `replaced_model`.
    """
    options = model_options()
    if not replacement_available(options):
        log.error(
            "REPLACEMENT_MODEL %s/%s is not a configured model; retired seats are left unchanged",
            REPLACEMENT_MODEL["provider"], REPLACEMENT_MODEL["model"],
        )
        return []
    offered = {(o["provider"], o["model"]) for o in options}
    changes: list[str] = []
    members = [*definition.get("seats", [])]
    if definition.get("chairman"):
        members.append(definition["chairman"])
    for member in members:
        pair = (member.get("provider"), member.get("model"))
        if not (is_retired(member) or (offered_only and pair not in offered)):
            continue
        old = f"{pair[0]}/{pair[1]}"
        member["replaced_model"] = old
        member["provider"] = REPLACEMENT_MODEL["provider"]
        member["model"] = REPLACEMENT_MODEL["model"]
        changes.append(f"{member.get('name') or 'Chairman'}: {old} -> {member['provider']}/{member['model']}")
    return changes


def load_council_config() -> dict[str, Any]:
    """Load presets from council.config.json. Re-read on every call so edits apply live."""
    with open(COUNCIL_CONFIG_PATH, encoding="utf-8") as f:
        cfg = json.load(f)
    if "presets" not in cfg or not cfg["presets"]:
        raise ValueError(f"{COUNCIL_CONFIG_PATH} must define at least one preset")
    default = cfg.get("default_preset")
    if default is not None and default not in cfg["presets"]:
        raise ValueError(f"default_preset {default!r} is not one of {sorted(cfg['presets'])}")
    return cfg


def model_options(cfg: dict[str, Any] | None = None) -> list[dict[str, str]]:
    """Only configured and positively identified OpenAI model pairs are offered."""
    cfg = cfg if cfg is not None else load_council_config()
    choices = set()
    for preset in cfg["presets"].values():
        for member in [*preset["seats"], preset["chairman"]]:
            if is_allowed_model(member["provider"], member["model"], PROVIDERS):
                choices.add((member["provider"], member["model"]))
    for provider, model in EXTRA_MODELS:
        if is_allowed_model(provider, model, PROVIDERS):
            choices.add((provider, model))
    return [{"provider": provider, "model": model} for provider, model in sorted(choices)]


def chat_default(cfg: dict[str, Any] | None = None, options: list[dict[str, str]] | None = None) -> dict[str, str] | None:
    cfg = cfg if cfg is not None else load_council_config()
    options = model_options(cfg) if options is None else options
    preferred = cfg.get("chat_default")
    if isinstance(preferred, dict):
        for option in options:
            if all(preferred.get(key) == option[key] for key in ("provider", "model")):
                return dict(option)
    return dict(options[0]) if options else None


def public_config() -> dict[str, Any]:
    """Config safe to expose to the UI: presets, available providers, defaults."""
    cfg = load_council_config()
    options = model_options(cfg)
    offered = {(option["provider"], option["model"]) for option in options}
    presets = []
    for key, preset in cfg["presets"].items():
        missing = sorted({s["provider"] for s in preset["seats"]} - set(PROVIDERS))
        if preset.get("chairman", {}).get("provider") not in PROVIDERS:
            missing.append(preset.get("chairman", {}).get("provider", "?"))
        unavailable = sorted({
            (member["provider"], member["model"])
            for member in [*preset["seats"], preset["chairman"]]
            if (member["provider"], member["model"]) not in offered
        })
        presets.append({
            "key": key,
            "aliases": sorted(alias for alias, target in PRESET_ALIASES.items() if target == key),
            "is_personal": False,
            "title": preset.get("title", key),
            "description": preset.get("description", ""),
            "seats": [
                {"name": s["name"], "model": s["model"], "provider": s["provider"], "persona": s["persona"], "avatar": s.get("avatar")}
                for s in preset["seats"]
            ],
            "chairman": {"name": "Chairman", "persona": "", **preset["chairman"]},
            "available": not unavailable,
            "missing_providers": sorted(set(missing)),
            "unavailable_models": [{"provider": provider, "model": model} for provider, model in unavailable],
        })
    return {
        "default_preset": cfg.get("default_preset", presets[0]["key"]),
        "presets": presets,
        "providers": sorted(name for name, provider in PROVIDERS.items() if is_trusted_endpoint(name, provider)),
        "model_options": options,
        "chat_default": chat_default(cfg, options),
        "defaults": {"max_rounds": DEFAULT_MAX_ROUNDS, "consensus": DEFAULT_CONSENSUS},
    }
