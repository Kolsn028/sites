"""Role changes for Main and tiers, independent of review forms."""

from ..access import TIER_GUILD_ID as GUILD_ID

TIER_ROLES = {1: 1549336886886015046, 2: 1549337062497452183, 3: 1549337206139785266}


async def award_main(bot, guild, member):
    cfg = await bot.db.get_config(guild.id)
    main = guild.get_role(cfg.get("main_role_id") or 0)
    novice = guild.get_role(cfg.get("accepted_role_id") or 0)
    if (
        not main
        or not novice
        or main.managed
        or main >= guild.me.top_role
        or novice >= guild.me.top_role
    ):
        raise ValueError(
            "Проверь /setup и подними роль бота выше main и -Novizio-. Повышение пока не подтверждено."
        )
    # Add first so a failed removal never leaves the member without family access.
    await member.add_roles(main, reason="Colombo: одобрено повышение до 3 ранга")
    if member.get_role(novice.id):
        await member.remove_roles(novice, reason="Colombo: Novizio заменена на main")


async def award_tier(guild, member, tier):
    if guild.id != GUILD_ID or tier not in TIER_ROLES:
        raise ValueError("Неизвестный сервер или тир.")
    roles = {n: guild.get_role(rid) for n, rid in TIER_ROLES.items()}
    if not guild.me.guild_permissions.manage_roles:
        raise ValueError("Боту нужно право «Управлять ролями».")
    for r in roles.values():
        if not r or r.managed or r.is_default() or r >= guild.me.top_role:
            raise ValueError("Подними роль бота выше всех трёх тиров.")
    if not member.get_role(roles[tier].id):
        await member.add_roles(roles[tier], reason=f"Colombo: одобрен тир {tier}")
    old = [r for n, r in roles.items() if n != tier and member.get_role(r.id)]
    if old:
        await member.remove_roles(*old, reason=f"Colombo: замена на тир {tier}")
    fresh = await guild.fetch_member(member.id)
    if {r.id for r in fresh.roles} & set(TIER_ROLES.values()) != {TIER_ROLES[tier]}:
        raise ValueError("Discord не подтвердил замену. Повтори одобрение.")
