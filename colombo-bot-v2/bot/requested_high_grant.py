"""One explicit owner request, consumed durably before changing Discord roles."""
import os
from datetime import datetime, timezone
from .roster import audit

ACTION = 'requested_colombo_20260921_once'
EXPIRES = datetime(2026, 9, 22, tzinfo=timezone.utc)


async def apply(bot, guild):
    guild_id = int(os.getenv('REQUESTED_COLOMBO_GUILD_ID') or 0)
    member_id = int(os.getenv('REQUESTED_COLOMBO_MEMBER_ID') or 0)
    role_id = int(os.getenv('REQUESTED_COLOMBO_ROLE_ID') or 0)
    if not all((guild_id, member_id, role_id)):
        return
    if guild.id != guild_id or datetime.now(timezone.utc) >= EXPIRES:
        return
    async with bot.operation_locks[(ACTION, guild.id)]:
        if await bot.db._one('SELECT id FROM audit_actions WHERE guild_id=? AND action=?', (guild.id, ACTION)):
            return
        cfg = await bot.db.get_config(guild.id)
        if cfg.get('colombo_role_id') != role_id:
            raise ValueError('Configured Colombo role differs from the requested role.')
        role = guild.get_role(role_id)
        member = await guild.fetch_member(member_id)
        if not role:
            raise ValueError('Requested Colombo role not found.')
        if role.managed or role.is_default():
            raise ValueError('Requested Colombo role cannot be assigned manually.')
        if role >= guild.me.top_role:
            raise ValueError(f'Colombo position={role.position}; bot top position={guild.me.top_role.position}: Colombo must be below bot.')
        if not guild.me.guild_permissions.manage_roles:
            raise ValueError('Bot lacks Manage Roles.')
        # Persist the consumed request first: restarts must not override a later
        # manual removal of Colombo. A failed attempt requires a fresh owner request.
        async with bot.db.lock:
            await audit(bot.db, guild.id, bot.user.id, ACTION, member_id,
                        {'role_id': role_id, 'state': 'consumed', 'source': 'explicit owner request'})
            await bot.db.conn.commit()
        await bot.backups.save(guild)
        if not member.get_role(role_id):
            await member.add_roles(role, reason='Owner requested Colombo for this Discord ID in chat, 2026-09-21')
        fresh = await guild.fetch_member(member_id)
        if not fresh.get_role(role_id):
            raise ValueError('Discord did not confirm Colombo on the requested member.')
        print(f'Requested Colombo verified | guild={guild.id} | member={member_id} | role={role_id}')
