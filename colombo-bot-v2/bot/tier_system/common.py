"""Shared tier identifiers, channel binding and review policy."""
import discord
from ..access import TIER_GUILD_ID as GUILD_ID, TIERCHECK_ROLE_ID, may_review_tiers
from ..services.ranks import TIER_ROLES
from ..ui import base_embed
KINDS = ("tier_1", "tier_2", "tier_3")


def tier_channel_topic(tier: int, bot_id: int, guild_id: int) -> str:
    # Тема связывает канал с конкретным ботом и сервером; имя можно менять.
    return f"colombo:tier:{tier}:{bot_id}:{guild_id}"

def tier_from_channel(channel, bot_id: int, guild_id: int) -> int | None:
    topic = getattr(channel, "topic", None)
    for tier in TIER_ROLES:
        if topic == tier_channel_topic(tier, bot_id, guild_id):
            return tier
    return None

async def can_review(bot, interaction: discord.Interaction) -> bool:
    return isinstance(interaction.user, discord.Member) and may_review_tiers(
        interaction.user, interaction.guild_id
    )

def panel(tier: int) -> discord.Embed:
    return base_embed(
        f"Повышение на тир {tier}",
        "Прикрепи ссылки на откаты и расскажи, зачем тебе нужен тир.\nДля каждой заявки создаётся отдельная приватная ветка; уведомления находятся внутри неё.\nРассматривают **tiercheck**. При одобрении другие тиры заменяются выбранным.",
        0xA82D40,
    )
