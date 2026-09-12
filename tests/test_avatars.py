"""Raster avatar validation uses embedded real 1px images and no image-library dependency."""

import base64
import unittest
import zlib
from unittest.mock import patch

from pydantic import ValidationError

from backend import config, debate, panels
from model_fixtures import provider_registry


PNG = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGMIq5gAAAKGAV+8gX7hAAAAAElFTkSuQmCC"
JPEG = "/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAAgGBgcGBQgHBwcJCQgKDBQNDAsLDBkSEw8UHRofHh0aHBwgJC4nICIsIxwcKDcpLDAxNDQ0Hyc5PTgyPC4zNDL/2wBDAQkJCQwLDBgNDRgyIRwhMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjL/wAARCAABAAEDASIAAhEBAxEB/8QAHwAAAQUBAQEBAQEAAAAAAAAAAAECAwQFBgcICQoL/8QAtRAAAgEDAwIEAwUFBAQAAAF9AQIDAAQRBRIhMUEGE1FhByJxFDKBkaEII0KxwRVS0fAkM2JyggkKFhcYGRolJicoKSo0NTY3ODk6Q0RFRkdISUpTVFVWV1hZWmNkZWZnaGlqc3R1dnd4eXqDhIWGh4iJipKTlJWWl5iZmqKjpKWmp6ipqrKztLW2t7i5usLDxMXGx8jJytLT1NXW19jZ2uHi4+Tl5ufo6erx8vP09fb3+Pn6/8QAHwEAAwEBAQEBAQEBAQAAAAAAAAECAwQFBgcICQoL/8QAtREAAgECBAQDBAcFBAQAAQJ3AAECAxEEBSExBhJBUQdhcRMiMoEIFEKRobHBCSMzUvAVYnLRChYkNOEl8RcYGRomJygpKjU2Nzg5OkNERUZHSElKU1RVVldYWVpjZGVmZ2hpanN0dXZ3eHl6goOEhYaHiImKkpOUlZaXmJmaoqOkpaanqKmqsrO0tba3uLm6wsPExcbHyMnK0tPU1dbX2Nna4uPk5ebn6Onq8vP09fb3+Pn6/9oADAMBAAIRAxEAPwChRRRXoHnH/9k="
WEBP = "UklGRjIAAABXRUJQVlA4ICYAAACQAQCdASoBAAEAAUAmJQBOl0AAcwAA/ueL/xQCkcFJ+K31AzSAAA=="


def member(avatar=None, chairman=False):
    cls = panels.PanelChairman if chairman else panels.PanelMember
    return cls(name="Test", provider="test", model="test", persona="Test evidence.", avatar=avatar)


def padded_png(size):
    original = base64.b64decode(PNG)
    text = b"Comment\0" + b"x" * (size - len(original) - 12 - 8)
    chunk = len(text).to_bytes(4, "big") + b"tEXt" + text + zlib.crc32(b"tEXt" + text).to_bytes(4, "big")
    return original[:-12] + chunk + original[-12:]


class AvatarValidationTests(unittest.TestCase):
    def test_automatic_presets_and_real_png_jpeg_webp_are_supported_for_members_and_chairman(self):
        for avatar in [None, *panels.AVATAR_PRESETS, f"data:image/png;base64,{PNG}", f"data:image/jpeg;base64,{JPEG}", f"data:image/webp;base64,{WEBP}"]:
            for chairman in (False, True):
                self.assertEqual(member(avatar, chairman).avatar, avatar)
        legacy = panels.PanelMember(name="Legacy", provider="test", model="test", persona="Legacy guidance.")
        self.assertIsNone(legacy.avatar)

    def test_external_svg_malformed_and_mismatched_images_are_rejected(self):
        invalid = [
            "https://example.com/avatar.png", "file:///tmp/avatar.png", "unknown-preset", "",
            "data:image/svg+xml;base64,PHN2Zz48L3N2Zz4=", "data:image/png;base64,****", "data:image/png;base64,AAAA",
            f"data:image/jpeg;base64,{PNG}", f"data:image/webp;base64,{JPEG}",
            "data:image/jpeg;base64," + base64.b64encode(base64.b64decode(JPEG)[:-2]).decode(),
            "data:image/png;base64," + base64.b64encode(base64.b64decode(PNG)[:-12]).decode(),
            "data:image/webp;base64," + base64.b64encode(b"RIFF\x00\x00\x00\x00" + base64.b64decode(WEBP)[8:]).decode(),
        ]
        for avatar in invalid:
            with self.subTest(avatar=avatar[:40]):
                for chairman in (False, True):
                    with self.assertRaises(ValidationError):
                        member(avatar, chairman)

    def test_decoded_size_limit_accepts_100_kib_and_rejects_one_byte_more(self):
        for size, accepted in ((panels.MAX_AVATAR_BYTES, True), (panels.MAX_AVATAR_BYTES + 1, False)):
            image = padded_png(size)
            self.assertEqual(len(image), size)
            avatar = "data:image/png;base64," + base64.b64encode(image).decode()
            if accepted:
                self.assertEqual(member(avatar).avatar, avatar)
            else:
                with self.assertRaises(ValidationError):
                    member(avatar)

    @patch.object(config, "PROVIDERS", provider_registry("foundry-openai", "openai"))
    @patch.object(config, "EXTRA_MODELS", [])
    def test_builtin_avatar_identity_is_explicit_in_public_config_and_turn_snapshots(self):
        settings = config.public_config()
        for preset in settings["presets"]:
            for seat in preset["seats"]:
                self.assertIn(seat["avatar"], panels.AVATAR_PRESETS)
            self.assertEqual(preset["chairman"]["avatar"], "chairman")
            snapshot = debate.resolve_debate_config(preset["key"])
            self.assertEqual([seat["avatar"] for seat in snapshot["seats"]], [seat["avatar"] for seat in preset["seats"]])
            self.assertEqual(snapshot["chairman"]["avatar"], "chairman")
        mixed = next(preset for preset in settings["presets"] if preset["key"] == "foundry-mixed")
        self.assertEqual([seat["avatar"] for seat in mixed["seats"]], ["skeptic", "builder", "historian", "systems"])


if __name__ == "__main__":
    unittest.main()
