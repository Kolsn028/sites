"""Restore private-thread access for current tier reviewers."""
import asyncio
import discord
from .common import GUILD_ID, TIERCHECK_ROLE_ID, TIER_ROLES, tier_channel_topic


async def sync_reviewers(bot, guild, member=None):
    if guild.id != GUILD_ID:
        return
    if not hasattr(bot, "_tier_sync_tasks"):
        bot._tier_sync_tasks = {}
    key = (guild.id, member.id if member else None)
    existing = bot._tier_sync_tasks.get(key)
    if existing:
        return await asyncio.shield(existing)

    async def run():
        try:
            return await _sync_reviewers(bot, guild, member)
        finally:
            bot._tier_sync_tasks.pop(key, None)

    task = asyncio.create_task(run())
    bot._tier_sync_tasks[key] = task
    return await asyncio.shield(task)

async def _sync_reviewers(bot, guild, member=None):
    if guild.id != GUILD_ID:
        return
    role = guild.get_role(TIERCHECK_ROLE_ID)
    if not role:
        return
    if member is None and not guild.chunked:
        await guild.chunk(cache=True)
    reviewers = [member] if member else list(role.members)
    reviewers = [m for m in reviewers if not m.bot and m.get_role(TIERCHECK_ROLE_ID)]
    rows = await bot.db.tier_threads(guild.id)
    added = 0
    failed = 0
    for row in rows:
        async with bot.operation_locks[("tier_member", guild.id, row["member_id"])]:
            try:
                thread = await guild.fetch_channel(row["thread_id"])
                if not isinstance(thread, discord.Thread) or not thread.parent:
                    continue
                valid = {
                    tier_channel_topic(tier, bot.user.id, guild.id)
                    for tier in TIER_ROLES
                }
                if thread.parent.topic not in valid:
                    continue
                if member is None:
                    members = {m.id for m in await thread.fetch_members()}
                else:
                    try:
                        await thread.fetch_member(member.id)
                        members = {member.id}
                    except discord.NotFound:
                        members = set()
                missing = [
                    m
                    for m in reviewers
                    if m.id not in members
                    and (guild.get_member(m.id) or m).get_role(TIERCHECK_ROLE_ID)
                ]
                if not missing:
                    continue
                archived, locked = thread.archived, thread.locked
                try:
                    if archived:
                        await thread.edit(
                            archived=False,
                            reason="Colombo: восстановление доступа tiercheck",
                        )
                    for m in missing:
                        await thread.add_user(m)
                        added += 1
                finally:
                    if archived:
                        await thread.edit(
                            archived=True,
                            locked=locked,
                            reason="Colombo: сохранение архива заявки",
                        )
            except discord.NotFound:
                continue
            except discord.DiscordException as exc:
                failed += 1
                print(
                    f'Tiercheck access error | guild={guild.id} | thread={row["thread_id"]}: {exc}'
                )
    print(
        f"Tiercheck access restored | guild={guild.id} | applications={len(rows)} | added={added} | failed={failed}"
    )
    return added, failed
