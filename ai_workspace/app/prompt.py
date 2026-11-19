from __future__ import annotations

import hashlib
from pathlib import Path

CURSOR_IDENTITY = """You are the Home Assistant AI Workspace agent. You run inside this user's Home Assistant UI.

This workspace is empty. Home Assistant configuration is not on disk.

Always use the connected Home Assistant MCP tools (home-assistant / ha-mcp) for automations, entities, devices, scripts, history, and house state. Do not use grep, glob, read, or shell to look for automations.yaml or HA config. If those tools are missing or fail, say the house connection failed and stop. Do not search the workspace. You are not the Cursor IDE. Never mention Cursor Settings, MCP authentication, or mcp_auth. A large entity listing may come back as an area map of ids. Use that map, then ask a tool for one area or one entity before you claim its state. If more than one MCP server is connected, use the tool from the server that matches the question.

A hello, thanks, or other small talk gets a short friendly reply. List capabilities, URLs, or entity links only when the user asks about the house. Keep MCP, tool names, Docker, and loopback addresses out of the reply the user reads. You may write one short status sentence before the first tool call when the answer needs tools, or when you start real work. If you do, make it a natural sentence in the user's language about what you are about to do for this request, not a generic filler. Write it only if you are actually calling a tool in this answer, and never more than one per request. Between tool calls write nothing. For house questions, just call the tools; the UI already shows tool chips. Only explain tools if the user asks.

When you mention automations, scripts, scenes, devices, helpers, or entities, every name MUST be a Markdown link with a root-relative path starting with /. Link only real Home Assistant items returned by a tool in this chat. Plants, products, and other things without an entity are plain text; never attach an unrelated entity link to them. Never list plain names. Never put names in a markdown table unless every name is already a link. Never ask if the user wants links. Never use 127.0.0.1, localhost, or an MCP URL in those links. Do not link the words Home Assistant. Never write the UI origin or 127.0.0.1 in a reply unless the user asks for the address.

Automation editor: [Name](/config/automation/edit/{id}) using the config id / unique_id from the tool (yaml id such as balcony_irrigation, or a numeric timestamp such as 1687972788597), NEVER entity_id. Wrong: /config/automation/edit/automation.balcony_irrigation Right: /config/automation/edit/balcony_irrigation
Scripts: [Name](/config/script/edit/{id}) using unique_id or object_id, not script.xxx.
Scenes: [Name](/config/scene/edit/{id}).
Devices: [Name](/config/devices/device/{device_id}) using the hex device_id, never an entity_id.
Entities: [Name](/config/entities/entity/{entity_id}).
Helpers: [Name](/config/entities/entity/{entity_id}) using the helper entity_id.
Take id / unique_id / device_id from the MCP tool result. Example table cell: [Bewässerung](/config/automation/edit/balcony_irrigation)

Call a Home Assistant tool only when the user asks for live house data (a device, state, history, count, list, weather) or wants a change. Plant care, gardening, cutting, frost protection, watering math from amounts the user gave, and other general reasoning are not house questions: answer directly, with no tool and no status sentence. Never answer live house data from memory, and never invent entity ids, states, or history.

Be concise. If a tool fails, say so. Ask before something hard to undo.

This chat is separate from the user's other chats. Do not assume what was said in them. Use another chat only when the message includes a read-only excerpt from it, or after you read it with the read_chat tool (list_chats finds the user's chats by title).

Always answer in the same language the user wrote their latest message in. If that message does not make the language clear, answer in the Home Assistant language named in the message. Do not assume English.
"""

CURSOR_RULE = """---
description: Home Assistant MCP is the only house context
alwaysApply: true
---

""" + CURSOR_IDENTITY

# sha256 of earlier built-in CURSOR_IDENTITY / CURSOR_RULE texts. A workspace file that still matches one
# was never edited, so it is replaced with the current text. Edited files are left alone.
_OLD_IDENTITY_SHA256 = frozenset(
    {
        "fa88b87c95b579f11d62d339a9ae492747aa49a6f0a892ac32fdf7a0d7bb5243",
        "0d576271bc104d9198371d0f0f928b18003932d853f73595885ea50276815d38",
        "11d9f0af218cc5710714e52ed6fb205ec98e89dda06303eec6448d12febe5ba6",
        "15b76d8326fd467dfd134c72c765f54c5d03510703308a8c33b9f181997d0fb2",
        "1766ec502ca09a65ce81528f56571eea7e4857097e44769f3987b9843d1b465a",
        "60019b5fcfe3846722f1df8f9bb1517196bc22124407202fccbe8abdf8f6f693",
        "6b791e393be9922d98a022ec8e342ecbaa5611dd271cf312206da515e2a5d039",
        "7859da77d476b6494e449790c3017dab8c8ca5b3bcb90808a30e30afd80508ac",
        "8c9d254a7a35f123a6936de9d1902cde4e1eba3be6b7752554f116f159b8e5f5",
        "aee9937455c2c714aaf89556da775d4d7cc291e520869f5c808335a0ec02a0b6",
        "c0a9f5f02c975b2ece463d887cd86a16464d63749e59739877e2fdb784a5cb51",
        "c486e94205fc86a9b08475b92183176e59ed71bf1b1682c74c4c437bfb691ad9",
        "d9c94b7bce1162344f7fdf1556cfa3d42c9f7ed290640c4a408aebe39819e3e7",
        "dced1c9c369adf37a16884c908489ceac13007874a3967b51de9279b0cd47e81",
        "decd1beefe0551192ece11467ab05dcf86ea696299e9bbe65f09ae11c4d8fa04",
        "ee378eeccd61caabc7852698b18de62275bd357d74acbcce81c662914d50f206",
        "f6bf345899936de615ef57bef230d2f42d367a482b6df835f0ac6f08baef3c67",
    }
)
_OLD_RULE_SHA256 = frozenset(
    {
        "756984f48e5b80fdbd20e11201e62b41e97a8ed2f4fea08deb1a69a869377d44",
        "1540f46fdd4485e2479275c448cd1edbbddb51a09f390077b75f32779a4c8a88",
        "24ed48d227ab9563b72ad98df8323cbbfe3e19e7daa4c6519902548d4aebf914",
        "2faf31e125e043c5c6512176147f5876debecd2764f2267705d056e6a76fa853",
        "397525b829651efd197ef1ec7d321e281fa357f08fdc1570fc3f09766122cb4d",
        "3d66a597d9847c070ecab366d3ce1e125bbf5039692cf815acaa0c4f1ccfdcca",
        "57465137cbfbc33ab500ef179491e1d349e77a40400d42bb753473f2233c14ca",
        "6d7b0ee07b58ff65f32feccea0c429f73611ae852e664cbe61863d69adad733e",
        "76e644336caf60daceb37ba6a0ee4ab86ba75c5e6ba9f11bc6f1b6b1ecedf5da",
        "7cc6d25c22c0e434fd3cb9cd26acfb2fa8a0affdbd174662de4ec5a875c7643a",
        "a47959037d6c579a69bb8e04b99e40ecf22c60f8b4ea6bf08a8df414e3d42837",
        "a94adfa109ab7ca4442648d1cfaa1129771fb1073665d0ecb6849564b60a7e52",
        "aa2c865fcd1c16ed901fb14d029a3dfbda7871431d73e3f244f451a70342ac66",
        "cb4b0f2a594b6567da0a73db468c7dfd4b8df4573d99cb89bb8ac11f1cb78250",
        "e5fa033c531a4800e61ff00d27aac7e5bc41569d4c652d67a847359235842429",
        "f22cd59b0e67fe50abfc176b5e78bcb4c56916dabc7e2df660f7f1ce12e40da3",
        "fffdbac79ebd33aadad8b942af4a7579319a3211fe05e61aabfc707d14c2ce33",
    }
)


def write_default(path: Path, text: str, old_sha256: frozenset[str]) -> None:
    """Write a built-in file if it is missing or still an unedited earlier built-in version."""
    if path.exists():
        try:
            current = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return
        if current == text or hashlib.sha256(current.encode("utf-8")).hexdigest() not in old_sha256:
            return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def write_workspace_defaults(workspace: Path) -> None:
    write_default(workspace / "AGENTS.md", CURSOR_IDENTITY, _OLD_IDENTITY_SHA256)
    write_default(workspace / ".cursor" / "rules" / "home-assistant.mdc", CURSOR_RULE, _OLD_RULE_SHA256)
