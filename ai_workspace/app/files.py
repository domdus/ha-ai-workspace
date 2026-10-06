from __future__ import annotations

from pathlib import Path
from typing import Any

MAX_FILES = 4
MAX_FILE_BYTES = 256 * 1024

_EXT_LANG = {
    ".yaml": "yaml",
    ".yml": "yaml",
    ".json": "json",
    ".toml": "toml",
    ".ini": "ini",
    ".cfg": "ini",
    ".conf": "ini",
    ".env": "",
    ".txt": "",
    ".log": "",
    ".md": "markdown",
    ".markdown": "markdown",
    ".csv": "csv",
    ".tsv": "tsv",
    ".xml": "xml",
    ".html": "html",
    ".htm": "html",
    ".css": "css",
    ".js": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".ts": "typescript",
    ".tsx": "tsx",
    ".jsx": "jsx",
    ".py": "python",
    ".sh": "bash",
    ".bash": "bash",
    ".sql": "sql",
}

_OK_MIME = {
    "text/plain",
    "text/yaml",
    "text/x-yaml",
    "application/yaml",
    "application/x-yaml",
    "application/json",
    "text/json",
    "text/markdown",
    "text/csv",
    "text/tab-separated-values",
    "text/xml",
    "application/xml",
    "application/toml",
    "text/html",
    "text/css",
    "text/javascript",
    "application/javascript",
    "application/x-javascript",
    "text/x-python",
    "application/x-sh",
}


def _is_text_attachment(name: str, mime: str) -> bool:
    ext = Path(name).suffix.lower()
    if ext in _EXT_LANG:
        return True
    if mime.startswith("text/"):
        return True
    return mime in _OK_MIME


def parse_client_files(raw: Any) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    if not isinstance(raw, list):
        return out
    for item in raw:
        if not isinstance(item, dict) or len(out) >= MAX_FILES:
            continue
        name = Path(str(item.get("name") or "file.txt")).name
        mime = str(item.get("mime") or item.get("type") or "text/plain").split(";")[0].strip().lower()
        if not _is_text_attachment(name, mime):
            continue
        text = str(item.get("text") or "")
        if text.startswith("\ufeff"):
            text = text[1:]
        if not text.strip() or "\0" in text:
            continue
        if len(text.encode("utf-8", "replace")) > MAX_FILE_BYTES:
            continue
        out.append({"name": name, "mime": mime or "text/plain", "text": text})
    return out


def file_events(files: list[dict[str, str]]) -> list[dict[str, str]]:
    return [{"type": "file", "name": item["name"]} for item in files]


def attach_files_to_message(text: str, files: list[dict[str, str]]) -> str:
    if not files:
        return text
    chunks = [str(text).strip()] if str(text or "").strip() else []
    for item in files:
        body = item["text"]
        ticks = "```"
        while ticks in body:
            ticks += "`"
        lang = _EXT_LANG.get(Path(item["name"]).suffix.lower(), "")
        header = f"{ticks}{lang}".rstrip()
        chunks.append(f"Attached file `{item['name']}`:\n{header}\n{body}\n{ticks}")
    return "\n\n".join(chunks)
