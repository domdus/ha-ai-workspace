from __future__ import annotations

import base64
import re
from pathlib import Path
from typing import Any

MAX_IMAGES = 4
MAX_BYTES = 4 * 1024 * 1024
_MIME = {
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
}


def caption_for(text: str, count: int = 0, file_count: int = 0) -> str:
    raw = str(text or "").strip()
    if raw:
        return raw
    if count > 0 and file_count > 0:
        return "Look at these attachments."
    if count == 1:
        return "Look at this image."
    if count > 1:
        return f"Look at these {count} images."
    if file_count == 1:
        return "Look at this file."
    if file_count > 1:
        return f"Look at these {file_count} files."
    return ""


def parse_client_images(raw: Any) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    if not isinstance(raw, list):
        return out
    for item in raw:
        if not isinstance(item, dict) or len(out) >= MAX_IMAGES:
            continue
        mime = str(item.get("mime") or item.get("type") or "image/jpeg").split(";")[0].strip().lower()
        if mime == "image/jpg":
            mime = "image/jpeg"
        if mime not in _MIME:
            continue
        data = str(item.get("data") or "").strip()
        if data.startswith("data:"):
            data = data.split(",", 1)[-1]
        data = re.sub(r"\s+", "", data)
        try:
            blob = base64.b64decode(data, validate=False)
        except (ValueError, TypeError):
            continue
        if not blob or len(blob) > MAX_BYTES:
            continue
        name = Path(str(item.get("name") or f"image{_MIME[mime]}")).name
        encoded = base64.b64encode(blob).decode("ascii")
        out.append({"name": name, "mime": mime, "data": encoded})
    return out


def image_events(images: list[dict[str, str]]) -> list[dict[str, str]]:
    return [
        {
            "type": "image",
            "name": item["name"],
            "src": f"data:{item['mime']};base64,{item['data']}",
        }
        for item in images
    ]


def cursor_payload(text: str, images: list[dict[str, str]] | None):
    if not images:
        return text
    packed = [{"data": item["data"], "mime_type": item["mime"]} for item in images]
    try:
        from cursor_sdk import SDKImage, UserMessage
    except ImportError:
        return {"text": text, "images": packed}
    factory = getattr(SDKImage, "data_image", None)
    if factory is None:
        return {"text": text, "images": packed}
    try:
        return UserMessage(text=text, images=[factory(item["data"], mime_type=item["mime_type"]) for item in packed])
    except Exception:
        return {"text": text, "images": packed}
