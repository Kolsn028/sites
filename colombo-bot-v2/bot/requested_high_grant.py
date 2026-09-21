"""One explicit owner request, consumed durably before changing Discord roles."""
from datetime import datetime, timezone
from .roster import audit

GUILD_ID = 1503854540116721747
MEMBER_ID = 1391572258262089739
ROLE_ID = 1503877899604721725
ACTION = 'requested_high_20260921_1391572258262089739'
EXPIRES = datetime(2026, 9, 22, tzinfo=timezone.utc)


async def apply(bot, guild):
    if guild.id != GUILD_ID or datetime.now(timezone.utc) >= EXPIRES:
        return
    async with bot.operation_locks[(ACTION, guild.id)]:
        if await bot.db._one('SELECT id FROM audit_actions WHERE guild_id=? AND action=?', (guild.id, ACTION)):
            return
        cfg = await bot.db.get_config(guild.id)
        if cfg.get('high_staff_role_id') != ROLE_ID:
            raise ValueError('Configured High role differs from the requested role.')
        role = guild.get_role(ROLE_ID)
        member = await guild.fetch_member(MEMBER_ID)
        if not role or role.managed or role.is_default() or role >= guild.me.top_role:
            raise ValueError('High role is missing or above the bot.')
        if not guild.me.guild_permissions.manage_roles:
            raise ValueError('Bot lacks Manage Roles.')
        # Persist the consumed request first: restarts must not override a later
        # manual removal of High. A failed attempt requires a fresh owner request.
        async with bot.db.lock:
            await audit(bot.db, guild.id, bot.user.id, ACTION, MEMBER_ID,
                        {'role_id': ROLE_ID, 'state': 'consumed', 'source': 'explicit owner request'})
            await bot.db.conn.commit()
        await bot.backups.save(guild)
        if not member.get_role(ROLE_ID):
            await member.add_roles(role, reason='Owner requested High for this Discord ID in chat, 2026-09-21')
        fresh = await guild.fetch_member(MEMBER_ID)
        if not fresh.get_role(ROLE_ID):
            raise ValueError('Discord did not confirm High on the requested member.')
        print(f'Requested High verified | guild={guild.id} | member={MEMBER_ID} | role={ROLE_ID}')
