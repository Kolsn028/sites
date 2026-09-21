"""Expiring, single-use role removal explicitly requested by the server owner."""
import os
from datetime import datetime, timezone
import discord
from .roster import audit

ACTION = 'requested_remove_roles_20260921_once'
EXPIRES = datetime(2026, 9, 22, tzinfo=timezone.utc)


async def apply(bot, guild):
    guild_id = int(os.getenv('REQUESTED_REMOVE_GUILD_ID') or 0)
    member_id = int(os.getenv('REQUESTED_REMOVE_MEMBER_ID') or 0)
    if not guild_id or not member_id or guild.id != guild_id or datetime.now(timezone.utc) >= EXPIRES:
        return
    async with bot.operation_locks[(ACTION, guild.id)]:
        if await bot.db._one('SELECT id FROM audit_actions WHERE guild_id=? AND action=?', (guild.id, ACTION)):
            return
        roles = await guild.fetch_roles()
        me = await guild.fetch_member(bot.user.id)
        member = await guild.fetch_member(member_id)
        if not me.guild_permissions.manage_roles:
            raise ValueError('Bot lacks Manage Roles.')
        own_ids = {r.id for r in me.roles}
        top = max(r for r in roles if r.id in own_ids)
        held_ids = {r.id for r in member.roles}
        removable = [r for r in roles if r.id in held_ids and not r.is_default() and not r.managed and r < top]
        async with bot.db.lock:
            await audit(bot.db, guild.id, bot.user.id, ACTION, member_id,
                        {'state': 'consumed', 'previous_roles': sorted(held_ids),
                         'requested_removals': [r.id for r in removable], 'source': 'explicit owner request'})
            await bot.db.conn.commit()
        # Persist before mutation so a future manual regrant is never undone.
        await bot.backups.save(guild)
        for role in removable:
            try:
                await member.remove_roles(role, reason='One-time role removal requested by server owner', atomic=True)
            except discord.HTTPException as exc:
                print(f'Requested removal failed | role={role.id} | status={exc.status}')
        fresh = await guild.fetch_member(member_id)
        remaining = [r.id for r in fresh.roles if not r.is_default()]
        removed = sorted(held_ids - {r.id for r in fresh.roles})
        print(f'Requested removal verified | guild={guild.id} | member={member_id} | removed={removed} | remaining={remaining}')
