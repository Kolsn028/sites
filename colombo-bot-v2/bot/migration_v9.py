"""Upgrade existing Discord UI using preserved DB records; no guessing lost data."""
import discord
from .events import EventView, card
from .profiles import refresh_member
from .leave import begin_leave


async def migrate_guild(bot,guild):
    # Recover case-channel mapping from stable topics, keeping all original messages.
    for ch in guild.text_channels:
        topic=ch.topic or ''
        if topic.startswith('Личное дело • owner='):
            raw=topic.partition('owner=')[2]
            if raw.isdigit() and not await bot.db.get_case_by_member(guild.id,int(raw)):
                await bot.db.create_case(guild.id,int(raw),ch.id,bot.now_iso())
    events=await bot.db._all('SELECT * FROM family_events WHERE guild_id=?',(guild.id,))
    for row in events:
        ch=guild.get_channel(row['channel_id'])
        if not isinstance(ch,discord.TextChannel) or not row['message_id']:continue
        try:
            msg=await ch.fetch_message(row['message_id'])
            if msg.author.id!=bot.user.id:continue
            view=EventView(bot)
            if row['status']!='open':
                for item in view.children:item.disabled=item.custom_id!='colombo:event:attendance'
            await msg.edit(embed=await card(bot.db,row),view=view,allowed_mentions=discord.AllowedMentions.none())
        except discord.NotFound:
            print(f'Old event message missing: {row["id"]}; database retained')
    # Apply the new leave rule once, capturing roles still present before removing them.
    for vac in await bot.db.active_vacations(guild.id):
        if vac['role_snapshot'] is None and vac['status']=='approved':
            async with bot.operation_locks[('leave',guild.id,vac['member_id'])]:
                await begin_leave(bot,guild,vac)
    ids={r['member_id'] for r in await bot.db._all('SELECT member_id FROM personal_cases WHERE guild_id=?',(guild.id,))}
    ids.update(r['member_id'] for r in await bot.db._all('''SELECT DISTINCT s.member_id FROM event_signups s
        JOIN family_events e ON e.id=s.event_id WHERE e.guild_id=?''',(guild.id,)))
    ids.update(r['member_id'] for r in await bot.db._all('SELECT DISTINCT member_id FROM progress_requests WHERE guild_id=?',(guild.id,)))
    for uid in ids:await refresh_member(bot,guild,uid)
    print(f'Colombo v9 migration: guild={guild.id} events={len(events)} profiles={len(ids)}')
