from __future__ import annotations

import json
from typing import Any


def compact_json(value: Any, limit: int = 2000) -> str:
    text = json.dumps(value, ensure_ascii=False, default=str)
    return text if len(text) <= limit else text[: limit - 1] + "..."


def profiles_for_storage(profiles: list[dict[str, Any]], persist_previews: bool) -> list[dict[str, Any]]:
    stored_profiles: list[dict[str, Any]] = []
    for profile in profiles:
        stored = {key: value for key, value in profile.items() if key != "sample"}
        if persist_previews:
            stored["sample"] = profile.get("sample", [])[:3]
        stored_profiles.append(stored)
    return stored_profiles
