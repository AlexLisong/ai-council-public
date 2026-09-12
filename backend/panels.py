"""Validation, ownership, and immutable turn selection for personal panels."""

from __future__ import annotations

import base64
import binascii
import re
from copy import deepcopy
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator

from . import config, db

AVATAR_PRESETS = frozenset({"skeptic", "builder", "historian", "systems", "chairman", "analyst", "visionary", "mediator"})
MAX_AVATAR_BYTES = 100 * 1024
MAX_AVATAR_CHARS = len("data:image/jpeg;base64,") + 4 * ((MAX_AVATAR_BYTES + 2) // 3)
AVATAR_DATA_URL = re.compile(r"data:image/(png|jpeg|webp);base64,([A-Za-z0-9+/]+={0,2})")


def _matches_image_type(kind: str, image: bytes) -> bool:
    """Check raster signatures and container boundaries without a decoding dependency."""
    if kind == "png":
        return (
            len(image) >= 45 and image.startswith(b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR")
            and b"IDAT" in image[16:-12] and image.endswith(b"\x00\x00\x00\x00IEND\xaeB`\x82")
        )
    if kind == "jpeg":
        return len(image) >= 20 and image.startswith(b"\xff\xd8\xff") and b"\xff\xda" in image and image.endswith(b"\xff\xd9")
    return (
        len(image) >= 20 and image[:4] == b"RIFF" and image[8:12] == b"WEBP"
        and int.from_bytes(image[4:8], "little") + 8 == len(image)
        and image[12:16] in {b"VP8 ", b"VP8L", b"VP8X"}
        and 0 < int.from_bytes(image[16:20], "little") <= len(image) - 20
    )


def validate_avatar(value: str | None) -> str | None:
    if value is None or value in AVATAR_PRESETS:
        return value
    match = AVATAR_DATA_URL.fullmatch(value)
    if match is None:
        raise ValueError("Avatar must be an automatic choice, a supported preset, or a base64 PNG, JPEG, or WebP image")
    try:
        image = base64.b64decode(match[2], validate=True)
    except (binascii.Error, ValueError):
        raise ValueError("Avatar image has malformed base64 data")
    if len(image) > MAX_AVATAR_BYTES:
        raise ValueError("Avatar image must be at most 100 KiB")
    if base64.b64encode(image).decode("ascii") != match[2] or not _matches_image_type(match[1], image):
        raise ValueError("Avatar image is malformed or does not match its PNG, JPEG, or WebP media type")
    return value


class PanelMember(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=80)
    provider: str = Field(min_length=1, max_length=80)
    model: str = Field(min_length=1, max_length=200)
    persona: str = Field(min_length=1, max_length=4000)
    avatar: str | None = Field(default=None, max_length=MAX_AVATAR_CHARS)
    # Provenance written by the retired-model remap; accepted so GET output round-trips to PUT.
    replaced_model: str | None = Field(default=None, max_length=200)

    @field_validator("avatar")
    @classmethod
    def _avatar_valid(cls, value: str | None) -> str | None:
        return validate_avatar(value)

    @field_validator("name", "provider", "model", "persona")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be blank")
        return value


class PanelChairman(PanelMember):
    persona: str = Field(default="", max_length=4000)

    @field_validator("persona", mode="before")
    @classmethod
    def _optional_persona(cls, value: str) -> str:
        return value.strip() if isinstance(value, str) else value

    @field_validator("name", "provider", "model", "persona")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        # The chairman may use the standard synthesis role without extra guidance.
        return value.strip()

    @field_validator("name", "provider", "model")
    @classmethod
    def _required_identity(cls, value: str) -> str:
        if not value:
            raise ValueError("must not be blank")
        return value


class PanelRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=100)
    seats: list[PanelMember] = Field(min_length=1, max_length=8)
    chairman: PanelChairman

    @field_validator("title")
    @classmethod
    def _title_not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be blank")
        return value


def validate_models(definition: dict[str, Any]) -> None:
    choices = {(choice["provider"], choice["model"]) for choice in config.model_options()}
    for member in [*definition["seats"], definition["chairman"]]:
        if (member["provider"], member["model"]) not in choices:
            raise ValueError(f"Model {member['provider']}/{member['model']} is not an available configured choice")


def public_panel(panel: dict[str, Any]) -> dict[str, Any]:
    definition = deepcopy(panel["definition"])
    choices = {(choice["provider"], choice["model"]) for choice in config.model_options()}
    members = [*definition["seats"], definition["chairman"]]
    missing_providers = sorted({member["provider"] for member in members if member["provider"] not in config.PROVIDERS})
    unavailable_models = sorted({(member["provider"], member["model"]) for member in members if (member["provider"], member["model"]) not in choices})
    return {
        **definition, "key": f"personal:{panel['id']}", "id": panel["id"], "is_personal": True,
        "description": "Your saved personal panel", "created_at": panel["created_at"], "updated_at": panel["updated_at"],
        "available": not unavailable_models, "missing_providers": missing_providers,
        "unavailable_models": [{"provider": provider, "model": model} for provider, model in unavailable_models],
    }


def owned_panel(panel_id: str, owner_id: int) -> dict[str, Any]:
    try:
        panel_id = str(UUID(panel_id))
    except ValueError:
        raise HTTPException(status_code=404, detail="Panel not found")
    panel = db.get_panel(panel_id, owner_id)
    if panel is None:
        raise HTTPException(status_code=404, detail="Panel not found")
    return panel


def select_panel(
    owner_id: int,
    requested_key: str | None,
    previous: dict[str, Any],
    use_latest: bool,
) -> tuple[str | None, dict[str, Any] | None]:
    """Use a saved turn snapshot unless the user explicitly selects a newer panel."""
    key = requested_key or previous.get("preset")
    personal = owned_panel(key.removeprefix("personal:"), owner_id) if key and key.startswith("personal:") else None
    if personal is not None:
        key = f"personal:{personal['id']}"
    same_panel = requested_key is None or key == previous.get("preset")
    if same_panel and not use_latest and previous.get("seats") and previous.get("chairman"):
        selected = {
            "title": previous.get("preset_title", key),
            "seats": deepcopy(previous["seats"]), "chairman": deepcopy(previous["chairman"]),
        }
    elif personal is not None:
        selected = deepcopy(personal["definition"])
    else:
        return key, None
    config.retire_models(selected, offered_only=True)
    if personal is not None:
        validate_models(selected)
    return key, selected
