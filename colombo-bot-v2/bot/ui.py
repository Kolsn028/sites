import os
import discord

FAMILY_NAME = os.getenv("FAMILY_NAME", "Colombo Famq")
EMBED_COLOR = int(os.getenv("EMBED_COLOR", "0xB11F2D"), 16)
BANNER_URL = os.getenv("BANNER_URL", "").strip()
FOOTER_TEXT = os.getenv("FOOTER_TEXT", f"{FAMILY_NAME} • Management System")


def base_embed(title: str, description: str = "", color: int | None = None) -> discord.Embed:
    e = discord.Embed(title=title, description=description, color=color if color is not None else EMBED_COLOR)
    if BANNER_URL:
        e.set_image(url=BANNER_URL)
    e.set_footer(text=FOOTER_TEXT)
    return e


def application_panel_embed() -> discord.Embed:
    return base_embed(
        "⚔️ Вступление в семью",
        "**Добро пожаловать. Начало твоего пути в семью.**\n\n"
        "• После отправки создаётся приватная ветка с рекрутерами.\n"
        "• Решение и вызов на обзвон приходят автоматически.\n"
        "• После принятия может автоматически создаться личное дело.\n\n"
        f"**{FAMILY_NAME}**",
    )


def vacation_panel_embed() -> discord.Embed:
    return base_embed(
        "🌴 Отдых / отпуск",
        "Подай заявку на отдых. Её обработает **Assistant GP Leader**, **Dep Leader** или администратор. "
        "После одобрения бот добавит тебя в общий статус отпусков и будет показывать остаток дней.",
        0xD5A43A,
    )


def case_panel_embed() -> discord.Embed:
    return base_embed(
        "📁 Личное дело участника",
        "Нажми кнопку ниже — бот создаст или откроет приватное личное дело.\n\n"
        "Туда можно отправлять **скрины каптов, МП, МШ, тренировок и другой активности**. "
        "После скрина выбирается тип, затем High Staff подтверждает или отклоняет отчёт.\n\n"
        "В статистику попадает только подтверждённая активность.",
        0x6E56CF,
    )


def activity_type_label(value: str) -> str:
    return {
        "capt": "⚔️ Капт",
        "mp": "🎯 МП",
        "msh": "🛡️ МШ",
        "training": "🏋️ Тренировка",
        "other": "📌 Другое",
        "unclassified": "❔ Не выбран",
    }.get(value, value)
