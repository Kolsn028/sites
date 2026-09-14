"""Per-guild Discord snapshots. Only bot-authored, checksummed JSON is restored."""
import asyncio
import gzip
import hashlib
import io
import json
import os
from datetime import datetime, timezone
import discord
from .roles import HIGH_KEYS, configured_roles

TABLES = ('guild_config', 'applications', 'recruiter_stats', 'vacations',
          'personal_cases', 'family_events', 'event_signups', 'progress_requests',
          'activity_submissions', 'audit_actions')
MAX_RAW = 64 * 1024 * 1024
MAX_FILE = 8 * 1024 * 1024


async def snapshot(db, guild_id):
    async with db.lock:
        data = {}
        for table in TABLES:
            if table == 'event_signups':
                sql = 'SELECT s.* FROM event_signups s JOIN family_events e ON e.id=s.event_id WHERE e.guild_id=? ORDER BY s.event_id,s.member_id'
            else:
                sql = f'SELECT * FROM {table} WHERE guild_id=? ORDER BY rowid'
            data[table] = await db._all(sql, (guild_id,))
        sequences = await db._all('SELECT name,seq FROM sqlite_sequence')
    return {'format': 1, 'guild_id': guild_id, 'tables': data, 'sequences': sequences}


def encode(payload):
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True,
                     separators=(',', ':')).encode('utf-8')
    if len(raw) > MAX_RAW:
        raise ValueError('Резервная копия превысила лимит 64 МБ.')
    compressed = gzip.compress(raw, mtime=0)
    if len(compressed) > MAX_FILE:
        raise ValueError('Резервная копия превысила лимит вложения 8 МБ.')
    return compressed, hashlib.sha256(compressed).hexdigest()


def decode(blob, checksum, guild_id):
    if len(blob) > MAX_FILE or hashlib.sha256(blob).hexdigest() != checksum:
        raise ValueError('Неверная контрольная сумма резервной копии.')
    with gzip.GzipFile(fileobj=io.BytesIO(blob)) as stream:
        raw = stream.read(MAX_RAW + 1)
    if len(raw) > MAX_RAW:
        raise ValueError('Резервная копия слишком велика.')
    payload = json.loads(raw)
    if payload.get('format') != 1 or payload.get('guild_id') != guild_id:
        raise ValueError('Неверный формат или сервер резервной копии.')
    data = payload.get('tables', {})
    if set(data) != set(TABLES):
        raise ValueError('Неполный список таблиц резервной копии.')
    for table, rows in data.items():
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            raise ValueError('Неверный формат строк.')
        if table != 'event_signups' and any(row.get('guild_id') != guild_id for row in rows):
            raise ValueError('В копии обнаружены данные другого сервера.')
    configs = data['guild_config']
    if len(configs) != 1:
        raise ValueError('Настройки сервера отсутствуют или дублируются.')
    events = {row['id'] for row in data['family_events']}
    if any(row.get('event_id') not in events for row in data['event_signups']):
        raise ValueError('Нарушена связь участников и МП.')
    return payload


async def restore_payload(db, payload):
    gid = payload['guild_id']
    async with db.lock:
        # Never replace existing local records with an older Discord snapshot.
        if await db._one('SELECT guild_id FROM guild_config WHERE guild_id=?', (gid,)):
            return False
        await db.conn.execute('BEGIN IMMEDIATE')
        try:
            for table in TABLES:
                columns = {r['name'] for r in await db._all(f'PRAGMA table_info({table})')}
                for row in payload['tables'][table]:
                    if not row or not set(row).issubset(columns):
                        raise ValueError(f'Несовместимые поля таблицы {table}.')
                    names = list(row)
                    await db.conn.execute(
                        f'INSERT INTO {table} ({",".join(names)}) VALUES ({",".join("?" for _ in names)})',
                        [row[name] for name in names])
            for item in payload.get('sequences', []):
                if item['name'] not in TABLES or not isinstance(item['seq'], int) or item['seq'] < 0:
                    raise ValueError('Неверный счётчик записей.')
                row = await db._one('SELECT seq FROM sqlite_sequence WHERE name=?', (item['name'],))
                if row:
                    await db.conn.execute('UPDATE sqlite_sequence SET seq=MAX(seq,?) WHERE name=?',
                                          (item['seq'], item['name']))
                else:
                    await db.conn.execute('INSERT INTO sqlite_sequence(name,seq) VALUES (?,?)',
                                          (item['name'], item['seq']))
            await db.conn.commit()
        except Exception:
            await db.conn.rollback()
            raise
        db._config_cache.pop(gid, None)
    return True


def change_lines(previous, current):
    lines = []
    labels = {'applications': 'Заявка', 'vacations': 'Отдых', 'activity_submissions': 'Отчёт',
              'progress_requests': 'Контракт/повышение', 'family_events': 'МП',
              'personal_cases': 'Личное дело', 'audit_actions': 'Действие'}
    old_tables = previous['tables'] if previous else {}
    for table, label in labels.items():
        old = {r['id']: r for r in old_tables.get(table, [])}
        for row in current['tables'][table]:
            if old.get(row['id']) == row:
                continue
            actor = row.get('handled_by') or row.get('actor_id') or row.get('creator_id')
            user = row.get('member_id') or row.get('applicant_id')
            status = row.get('status') or row.get('action') or 'обновлено'
            lines.append(f'{label} #{row["id"]}: {status}' +
                         (f' · участник <@{user}>' if user else '') +
                         (f' · ответственный <@{actor}>' if actor else ''))
    old_signups = {(r['event_id'], r['member_id']): r for r in old_tables.get('event_signups', [])}
    for row in current['tables']['event_signups']:
        if old_signups.get((row['event_id'], row['member_id'])) != row:
            lines.append(f'МП #{row["event_id"]} · <@{row["member_id"]}> · {row["seat"]} · присутствие: {"да" if row["attended"] else "нет"}')
    if current['tables']['recruiter_stats'] != old_tables.get('recruiter_stats'):
        lines.append('Статистика рекрутов:')
        for row in current['tables']['recruiter_stats']:
            lines.append(f'<@{row["recruiter_id"]}> · принято {row["accepted_count"]} · отказов {row["rejected_count"]}')
    if current['tables']['guild_config'] != old_tables.get('guild_config'):
        lines.append('Настройки сервера сохранены.')
    return lines


class DiscordBackups:
    def __init__(self, bot):
        self.bot = bot
        self.wake = asyncio.Event()
        self.mutex = asyncio.Lock()
        self.task = None
        self.last = {}
        self.hashes = {}
        self.errors = {}
        self.saved_at = {}

    def topic(self, guild_id, kind):
        return f'colombo:{kind}:v1:{self.bot.user.id}:{guild_id}'

    async def restore(self):
        expected = json.loads(os.getenv('DISCORD_BACKUP_CHANNEL_IDS', '{}'))
        seen = set()
        # REST is available in setup_hook, before Gateway events and UI handlers.
        async for guild in self.bot.fetch_guilds(limit=None):
            seen.add(str(guild.id))
            if await self.bot.db._one('SELECT guild_id FROM guild_config WHERE guild_id=?', (guild.id,)):
                continue
            channels = await guild.fetch_channels()
            matches = [ch for ch in channels if isinstance(ch, discord.TextChannel)
                       and ch.topic == self.topic(guild.id, 'backup')]
            if len(matches) > 1:
                raise RuntimeError(f'Duplicate backup channels for guild {guild.id}')
            if str(guild.id) in expected and (not matches or matches[0].id != int(expected[str(guild.id)])):
                raise RuntimeError(f'Expected backup channel missing for guild {guild.id}')
            if not matches:
                continue
            restored = False
            async for msg in matches[0].history(limit=50):
                if msg.author.id != self.bot.user.id or len(msg.attachments) != 1:
                    continue
                parts = msg.content.split()
                if len(parts) != 2 or parts[0] != 'COLOMBO_BACKUP_V1':
                    continue
                if msg.attachments[0].size > MAX_FILE:
                    continue
                try:
                    payload = decode(await msg.attachments[0].read(), parts[1], guild.id)
                except (ValueError, OSError, EOFError, KeyError, TypeError):
                    continue
                # Database conflicts stop startup rather than silently dropping data.
                await restore_payload(self.bot.db, payload)
                self.last[guild.id] = payload
                self.hashes[guild.id] = parts[1]
                self.saved_at[guild.id] = msg.created_at.isoformat()
                restored = True
                print(f'Discord backup restored | guild={guild.id} | message={msg.id}')
                break
            if not restored:
                raise RuntimeError(f'No valid backup in channel {matches[0].id}; refusing empty startup')

        if set(expected) - seen:
            raise RuntimeError('Нет доступа к одному из серверов с обязательной копией.')

    async def ensure_channels(self, guild):
        cfg = await self.bot.db.get_config(guild.id)
        category = guild.get_channel(cfg.get('management_category_id') or 0)
        roles = configured_roles(guild, cfg, HIGH_KEYS)
        if not isinstance(category, discord.CategoryChannel) or len(roles) != len(HIGH_KEYS):
            raise ValueError('Для логов нужны настроенные High, Deputy Leader, Leader и категория управления.')
        ow = {guild.default_role: discord.PermissionOverwrite(view_channel=False),
              guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True,
                  attach_files=True, embed_links=True, read_message_history=True)}
        for role in roles:
            ow[role] = discord.PermissionOverwrite(view_channel=True, send_messages=False,
                read_message_history=True, create_public_threads=False, create_private_threads=False)
        channels = await guild.fetch_channels()
        result = {}
        for kind, name in (('backup', 'данные-бота'), ('logs', 'логи-бота')):
            matches = [ch for ch in channels if isinstance(ch, discord.TextChannel)
                       and ch.topic == self.topic(guild.id, kind)]
            if len(matches) > 1:
                raise ValueError('Найдены дубликаты служебных каналов.')
            if matches:
                channel = matches[0]
                if channel.category_id != category.id or channel.overwrites != ow:
                    await channel.edit(category=category, overwrites=ow, reason='Colombo: доступ High и выше')
            else:
                channel = await guild.create_text_channel(name, category=category,
                    topic=self.topic(guild.id, kind), overwrites=ow, reason='Colombo: хранение данных')
            result[kind] = channel
        return result

    def watch_commits(self):
        connection = self.bot.db.conn
        original = connection.commit
        previous = connection.total_changes
        async def commit():
            nonlocal previous
            await original()
            if connection.total_changes != previous:
                previous = connection.total_changes
                self.wake.set()
        connection.commit = commit
        self.task = asyncio.create_task(self.worker())

    async def save(self, guild):
        async with self.mutex:
            if self.bot.operation_locks[('setup', guild.id)].locked():
                raise ValueError('Настройка выполняется; копия будет сохранена после её завершения.')
            channels = await self.ensure_channels(guild)
            payload = await snapshot(self.bot.db, guild.id)
            blob, checksum = encode(payload)
            if self.hashes.get(guild.id) == checksum:
                return
            message = await channels['backup'].send(
                content=f'COLOMBO_BACKUP_V1 {checksum}',
                file=discord.File(io.BytesIO(blob), filename='colombo-state.json.gz'),
                allowed_mentions=discord.AllowedMentions.none())
            if not message.attachments or hashlib.sha256(await message.attachments[0].read()).hexdigest() != checksum:
                raise RuntimeError('Не удалось подтвердить сохранённую копию.')
            lines = change_lines(self.last.get(guild.id), payload)
            # Backup is already durable even if the human-readable log fails.
            text = ''
            for line in lines:
                if len(text) + len(line) > 1800:
                    await channels['logs'].send(text, allowed_mentions=discord.AllowedMentions.none())
                    text = ''
                text += line[:500] + '\n'
            if text:
                await channels['logs'].send(text, allowed_mentions=discord.AllowedMentions.none())
            self.last[guild.id] = payload
            self.hashes[guild.id] = checksum
            self.saved_at[guild.id] = datetime.now(timezone.utc).isoformat()
            self.errors.pop(guild.id, None)

    async def worker(self):
        while True:
            try:
                await asyncio.wait_for(self.wake.wait(), timeout=60)
            except asyncio.TimeoutError:
                pass
            self.wake.clear()
            await asyncio.sleep(3)  # combine commits from one interaction
            for guild in self.bot.guilds:
                cfg = await self.bot.db.get_config(guild.id)
                if not cfg.get('management_category_id'):
                    continue
                try:
                    await self.save(guild)
                except Exception as exc:
                    self.errors[guild.id] = str(exc)
                    print(f'Discord backup failed | guild={guild.id}: {exc}')
            # Failed writes retry on the periodic wake, never a tight loop.

    async def close(self):
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
        for guild in self.bot.guilds:
            if guild.id in self.last:
                try:
                    await asyncio.wait_for(self.save(guild), timeout=10)
                except Exception as exc:
                    print(f'Final Discord backup failed | guild={guild.id}: {exc}')
