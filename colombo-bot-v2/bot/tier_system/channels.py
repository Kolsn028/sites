"""Repeatable installation of tier channels and application panels."""
import discord
from ..performance import edit_if_changed
from ..roles import STAFF_KEYS, configured_roles
from .common import GUILD_ID, TIERCHECK_ROLE_ID, TIER_ROLES, tier_channel_topic, panel
from .applications import TierPanelView
from .reviewers import sync_reviewers


async def install(bot, guild):
    if guild.id != GUILD_ID:
        return
    config = await bot.db.get_config(guild.id)
    category = guild.get_channel(config.get("family_category_id") or 0)
    if not isinstance(category, discord.CategoryChannel):
        raise ValueError("Не найдена настроенная категория COLOMBO • СОСТАВ.")
    if any(not guild.get_role(role_id) for role_id in TIER_ROLES.values()):
        raise ValueError("Не найдены указанные роли тиров.")
    reviewer_role = guild.get_role(TIERCHECK_ROLE_ID)
    if not reviewer_role:
        raise ValueError("Не найдена роль tiercheck.")
    family = [reviewer_role] + configured_roles(
        guild,
        config,
        STAFF_KEYS + ("colombo_role_id", "accepted_role_id", "main_role_id"),
    )
    ow = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False),
        guild.me: discord.PermissionOverwrite(
            view_channel=True,
            send_messages=True,
            embed_links=True,
            read_message_history=True,
            create_private_threads=True,
            send_messages_in_threads=True,
            manage_threads=True,
        ),
    }
    for r in family:
        ow[r] = discord.PermissionOverwrite(
            view_channel=True,
            send_messages=False,
            read_message_history=True,
            send_messages_in_threads=True,
        )
    channels = await guild.fetch_channels()
    for tier in TIER_ROLES:
        name = f"повышение-на-тир-{tier}"
        topic = tier_channel_topic(tier, bot.user.id, guild.id)
        matches = [
            c
            for c in channels
            if isinstance(c, discord.TextChannel)
            and (c.topic == topic or (c.category_id == category.id and c.name == name))
        ]
        if len(matches) > 1:
            raise ValueError(f"Найдены дубли канала {name}.")
        channel = (
            matches[0]
            if matches
            else await guild.create_text_channel(
                name, category=category, topic=topic, overwrites=ow
            )
        )
        if matches and (
            channel.category_id != category.id
            or channel.topic != topic
            or channel.overwrites != ow
        ):
            await channel.edit(category=category, topic=topic, overwrites=ow)
        message = None
        async for m in channel.history(limit=50):
            if m.author.id == bot.user.id and any(
                getattr(c, "custom_id", None) == "colombo:tier:apply"
                for row in m.components
                for c in row.children
            ):
                message = m
                break
        if message:
            await edit_if_changed(
                message,
                embed=panel(tier),
                view=TierPanelView(bot),
                allowed_mentions=discord.AllowedMentions.none(),
            )
        else:
            await channel.send(
                embed=panel(tier),
                view=TierPanelView(bot),
                allowed_mentions=discord.AllowedMentions.none(),
            )
        print(
            f"Tier channel ready | guild={guild.id} | tier={tier} | channel={channel.id}"
        )

    await sync_reviewers(bot, guild)
