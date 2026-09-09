from datetime import datetime, timedelta, timezone
import discord

VOICE_KEYS = ('interview_voice_channel_id', 'interview_voice_2_id', 'interview_voice_3_id')

async def update_assignment_card(message, owner_id):
    if not message.embeds:
        return
    embed = message.embeds[0].copy()
    value = f'<@{owner_id}>' if owner_id else 'Свободна — нажми «Взять заявку»'
    for index, field in enumerate(embed.fields):
        if field.name == 'Ответственный':
            embed.set_field_at(index, name='Ответственный', value=value, inline=False)
            break
    else:
        embed.add_field(name='Ответственный', value=value, inline=False)
    await message.edit(embed=embed, allowed_mentions=discord.AllowedMentions.none())

async def interview_room(bot, guild, cfg, app):
    rooms = [r for key in VOICE_KEYS if isinstance((r := guild.get_channel(cfg.get(key) or 0)), discord.VoiceChannel)]
    candidate = guild.get_member(app['applicant_id'])
    recruiter = guild.get_member(app['assigned_to']) if app.get('assigned_to') else None
    if not candidate or not recruiter:
        raise ValueError('Кандидат или ответственный рекрутер вышел с сервера.')
    now = datetime.now(timezone.utc)
    available = []
    for room in rooms:
        if not all(room.permissions_for(m).view_channel and room.permissions_for(m).connect for m in (candidate,recruiter)):
            continue
        occupants = {m.id for m in room.members}
        own_room = room.id == app.get('interview_room_id') and app.get('interview_until') and app['interview_until'] > now.isoformat()
        if not occupants or (own_room and occupants <= {candidate.id,recruiter.id}):
            available.append(room.id)
    if app.get('interview_room_id') in available:
        available.remove(app['interview_room_id']); available.insert(0,app['interview_room_id'])
    room_id = await bot.db.reserve_interview(app['id'], guild.id, available, now.isoformat(), (now+timedelta(minutes=15)).isoformat())
    return guild.get_channel(room_id) if room_id else None
