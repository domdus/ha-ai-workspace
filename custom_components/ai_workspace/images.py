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


# Prompt sent when the user attaches images or files without text, in the chat's language
# (same words as attach_prompt_* in www/i18n.js): image, {count} images, file, {count} files, mixed.
CAPTIONS: dict[str, tuple[str, str, str, str, str]] = {
    "en": (
        "Look at this image.",
        "Look at these {count} images.",
        "Look at this file.",
        "Look at these {count} files.",
        "Look at these attachments.",
    ),
    "de": (
        "Sieh dir dieses Bild an.",
        "Sieh dir diese {count} Bilder an.",
        "Sieh dir diese Datei an.",
        "Sieh dir diese {count} Dateien an.",
        "Sieh dir diese Anhänge an.",
    ),
    "fr": (
        "Regarde cette image.",
        "Regarde ces {count} images.",
        "Regarde ce fichier.",
        "Regarde ces {count} fichiers.",
        "Regarde ces pièces jointes.",
    ),
    "es": (
        "Mira esta imagen.",
        "Mira estas {count} imágenes.",
        "Mira este archivo.",
        "Mira estos {count} archivos.",
        "Mira estos adjuntos.",
    ),
    "it": (
        "Guarda questa immagine.",
        "Guarda queste {count} immagini.",
        "Guarda questo file.",
        "Guarda questi {count} file.",
        "Guarda questi allegati.",
    ),
    "nl": (
        "Bekijk deze afbeelding.",
        "Bekijk deze {count} afbeeldingen.",
        "Bekijk dit bestand.",
        "Bekijk deze {count} bestanden.",
        "Bekijk deze bijlagen.",
    ),
    "pl": (
        "Spójrz na ten obraz.",
        "Spójrz na te obrazy ({count}).",
        "Spójrz na ten plik.",
        "Spójrz na te pliki ({count}).",
        "Spójrz na te załączniki.",
    ),
    "cs": (
        "Podívej se na tento obrázek.",
        "Podívej se na tyto obrázky ({count}).",
        "Podívej se na tento soubor.",
        "Podívej se na tyto soubory ({count}).",
        "Podívej se na tyto přílohy.",
    ),
    "sv": (
        "Titta på den här bilden.",
        "Titta på de här {count} bilderna.",
        "Titta på den här filen.",
        "Titta på de här {count} filerna.",
        "Titta på de här bilagorna.",
    ),
    "ru": (
        "Посмотри на это изображение.",
        "Посмотри на эти изображения ({count}).",
        "Посмотри на этот файл.",
        "Посмотри на эти файлы ({count}).",
        "Посмотри на эти вложения.",
    ),
    "ko": (
        "이 이미지를 봐 주세요.",
        "이 이미지 {count}개를 봐 주세요.",
        "이 파일을 봐 주세요.",
        "이 파일 {count}개를 봐 주세요.",
        "이 첨부 파일들을 봐 주세요.",
    ),
    "zh-Hans": (
        "请看这张图片。",
        "请看这 {count} 张图片。",
        "请看这个文件。",
        "请看这 {count} 个文件。",
        "请看这些附件。",
    ),
    "zh-Hant": (
        "請看這張圖片。",
        "請看這 {count} 張圖片。",
        "請看這個檔案。",
        "請看這 {count} 個檔案。",
        "請看這些附件。",
    ),
    "az": (
        "Bu şəklə bax.",
        "Bu {count} şəklə bax.",
        "Bu fayla bax.",
        "Bu {count} fayla bax.",
        "Bu qoşmalara bax.",
    ),
    "eo": (
        "Rigardu ĉi tiun bildon.",
        "Rigardu ĉi tiujn {count} bildojn.",
        "Rigardu ĉi tiun dosieron.",
        "Rigardu ĉi tiujn {count} dosierojn.",
        "Rigardu ĉi tiujn kunsendaĵojn.",
    ),
}


def _captions(language: str = "") -> tuple[str, str, str, str, str]:
    """Exact code first (zh-Hant), then its base (de-CH -> de), then English."""
    code = str(language or "").strip().replace("_", "-")
    if code in CAPTIONS:
        return CAPTIONS[code]
    lowered = code.lower()
    if lowered.startswith("zh"):
        traditional = any(tag in lowered for tag in ("hant", "-tw", "-hk", "-mo"))
        return CAPTIONS["zh-Hant" if traditional else "zh-Hans"]
    return CAPTIONS.get(lowered.split("-")[0], CAPTIONS["en"])


def is_default_caption(text: str) -> bool:
    """True when the message is only the auto-generated attachment prompt (in any language)."""
    value = str(text or "").strip()
    if not value:
        return False
    for row in CAPTIONS.values():
        for item in row:
            if "{count}" in item:
                head, tail = item.split("{count}", 1)
                if re.fullmatch(re.escape(head) + r"\d+" + re.escape(tail), value):
                    return True
            elif value == item:
                return True
    return False


def caption_for(text: str, count: int = 0, file_count: int = 0, language: str = "") -> str:
    raw = str(text or "").strip()
    if raw:
        return raw
    one_image, images, one_file, files, mixed = _captions(language)
    if count > 0 and file_count > 0:
        return mixed
    if count == 1:
        return one_image
    if count > 1:
        return images.replace("{count}", str(count))
    if file_count == 1:
        return one_file
    if file_count > 1:
        return files.replace("{count}", str(file_count))
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


def openai_user_content(text: str, images: list[dict[str, str]]) -> str | list[dict[str, Any]]:
    if not images:
        return text
    parts: list[dict[str, Any]] = []
    if text:
        parts.append({"type": "text", "text": text})
    for item in images:
        parts.append(
            {
                "type": "image_url",
                "image_url": {"url": f"data:{item['mime']};base64,{item['data']}"},
            }
        )
    return parts


def anthropic_user_content(text: str, images: list[dict[str, str]]) -> str | list[dict[str, Any]]:
    if not images:
        return text
    parts: list[dict[str, Any]] = []
    for item in images:
        parts.append(
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": item["mime"],
                    "data": item["data"],
                },
            }
        )
    if text:
        parts.append({"type": "text", "text": text})
    return parts
