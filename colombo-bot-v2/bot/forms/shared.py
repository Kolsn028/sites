from __future__ import annotations

import re
import discord


def _id_from_title(message: discord.Message | None, prefix: str) -> int | None:
    if not message or not message.embeds:
        return None
    m = re.search(rf"{re.escape(prefix)}\s*#(\d+)", message.embeds[0].title or "")
    return int(m.group(1)) if m else None


def _thread_name(name: str, uid: int) -> str:
    name = re.sub(r"[^0-9A-Za-zА-Яа-яЁё _.-]+", "", name).strip()
    name = re.sub(r"\s+", "-", name)[:60] or str(uid)
    return f"заявка-{name}"[:100]
