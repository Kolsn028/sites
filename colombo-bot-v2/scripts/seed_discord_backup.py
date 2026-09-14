"""Run ONCE in the old running Railway container before the first upgrade.
Does not restart the bot or modify its database. Uses its existing token locally.
"""
import asyncio
import gzip
import hashlib
import io
import json
import os
import sqlite3
from pathlib import Path
import discord

TABLES = ('guild_config', 'applications', 'recruiter_stats', 'vacations',
          'personal_cases', 'family_events', 'event_signups', 'progress_requests',
          'activity_submissions', 'audit_actions')


def read_current():
    path = Path(os.getenv('DATABASE_PATH', 'data/colombo-v9.db')).resolve()
    connection = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute('BEGIN')
        configs = [dict(r) for r in connection.execute('SELECT * FROM guild_config')]
        sequences = [dict(r) for r in connection.execute('SELECT name,seq FROM sqlite_sequence')]
        result = []
        for cfg in configs:
            if not cfg.get('management_category_id'):
                continue
            gid = cfg['guild_id']
            data = {}
            for table in TABLES:
                query = ('SELECT s.* FROM event_signups s JOIN family_events e ON e.id=s.event_id WHERE e.guild_id=? ORDER BY s.event_id,s.member_id'
                         if table == 'event_signups' else f'SELECT * FROM {table} WHERE guild_id=? ORDER BY rowid')
                data[table] = [dict(r) for r in connection.execute(query, (gid,))]
            result.append({'format': 1, 'guild_id': gid, 'tables': data, 'sequences': sequences})
        return result
    finally:
        connection.rollback()
        connection.close()


async def main():
    payloads = read_current()
    if not payloads:
        raise RuntimeError('В текущей базе нет настроенных серверов. Ничего не отправлено.')
    client = discord.Client(intents=discord.Intents.none())
    mapping = {}
    try:
        await client.login(os.environ['DISCORD_TOKEN'])
        for payload in payloads:
            gid = payload['guild_id']
            cfg = payload['tables']['guild_config'][0]
            guild = await client.fetch_guild(gid)
            me = await guild.fetch_member(client.user.id)
            roles = [guild.get_role(cfg.get(k) or 0) for k in
                     ('leader_role_id','dep_leader_role_id','high_staff_role_id')]
            if any(r is None for r in roles):
                raise RuntimeError(f'Не найдены настроенные старшие роли сервера {gid}')
            channels = await guild.fetch_channels()
            category = next((ch for ch in channels if ch.id == cfg['management_category_id']), None)
            if not isinstance(category, discord.CategoryChannel):
                raise RuntimeError('Категория управления не найдена.')
            ow = {guild.default_role: discord.PermissionOverwrite(view_channel=False),
                  me: discord.PermissionOverwrite(view_channel=True, send_messages=True,
                      attach_files=True, embed_links=True, read_message_history=True)}
            for role in roles:
                ow[role] = discord.PermissionOverwrite(view_channel=True, send_messages=False,
                    read_message_history=True, create_public_threads=False, create_private_threads=False)
            topic = f'colombo:backup:v1:{client.user.id}:{gid}'
            matches = [ch for ch in channels if isinstance(ch, discord.TextChannel) and ch.topic == topic]
            if len(matches) > 1:
                raise RuntimeError('Дублирующиеся каналы копий.')
            if matches:
                channel = matches[0]
                await channel.edit(overwrites=ow, category=category)
            else:
                channel = await guild.create_text_channel('данные-бота', category=category,
                    topic=topic, overwrites=ow)
            raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()
            blob = gzip.compress(raw, mtime=0)
            if len(raw) > 64 * 1024 * 1024 or len(blob) > 8 * 1024 * 1024:
                raise RuntimeError('Копия превышает лимит; требуется другой способ переноса.')
            checksum = hashlib.sha256(blob).hexdigest()
            msg = await channel.send(content=f'COLOMBO_BACKUP_V1 {checksum}',
                file=discord.File(io.BytesIO(blob), filename='colombo-state.json.gz'),
                allowed_mentions=discord.AllowedMentions.none())
            if hashlib.sha256(await msg.attachments[0].read()).hexdigest() != checksum:
                raise RuntimeError('Не удалось подтвердить копию.')
            mapping[str(gid)] = channel.id
            print(f'Копия проверена: сервер {gid}, сообщение {msg.id}')
        print('DISCORD_BACKUP_CHANNEL_IDS=' + json.dumps(mapping, separators=(',', ':')))
        print('До деплоя не принимайте новые заявки и решения: копия отражает момент запуска скрипта.')
    finally:
        await client.close()


if __name__ == '__main__':
    asyncio.run(main())
