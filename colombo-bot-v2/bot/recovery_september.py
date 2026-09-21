"""One-time, user-authorized recovery from the two independent leaderboard periods."""
import json
import re
from datetime import datetime, timezone

GUILD_ID = 1503854540116721747
ACTION = 'recovery:september-2026:v1'
COMPLETE = 'recovery:september-2026:v1:complete'
ROLES = {
    'guest_role_id': 1544392761493688460,
    'colombo_role_id': 1503855996236337182,
    'accepted_role_id': 1508489953032671273,
    'main_role_id': 1508490711719477288,
    'recruiter_role_id': 1508490505665908797,
    'high_staff_role_id': 1503877899604721725,
    'dep_leader_role_id': 1503856518087442596,
    'leader_role_id': 1503877653101285497,
    'vacation_role_id': 1547672799924060311,
}
BOARD_CHANNEL = 1547672836624089238
OLD_BOARD = 1547980422850289728
NEW_BOARD = 1549116916554277046
LEAVE_CHANNEL = 1547672833868431492
OLD_LEAVE = 1547980424855167067
NEW_LEAVE = 1549116918357819543


def parse_board(text):
    rows = {}
    for line in text.replace('**', '').splitlines():
        if not line.strip():
            continue
        match = re.fullmatch(r'.*?<@!?(\d+)>\s*—\s*(\d+)\s+принято(?:\s*·\s*(\d+)\s+отказ\w*)?\s*', line)
        if not match:
            raise ValueError('Не удалось однозначно прочитать строку лидерборда.')
        uid, accepted, rejected = match.groups()
        uid = int(uid)
        if uid in rows:
            raise ValueError('Повтор участника в исходном лидерборде.')
        rows[uid] = (int(accepted), int(rejected or 0))
    if not rows:
        raise ValueError('Исходный лидерборд пуст.')
    return rows


def parse_leaves(text):
    rows = {}
    for line in text.replace('**', '').splitlines():
        if not line.strip():
            continue
        match = re.fullmatch(r'🌴\s*<@!?(\d+)>\s*—\s*до\s*(\d{2}\.\d{2}\.\d{4}).*', line)
        if not match:
            raise ValueError('Не удалось прочитать исходный список отпусков.')
        uid, end = match.groups()
        if int(uid) in rows:
            raise ValueError('Повтор участника в списке отпусков.')
        rows[int(uid)] = datetime.strptime(end, '%d.%m.%Y').date().isoformat()
    if not rows:
        raise ValueError('Исходный список отпусков пуст.')
    return rows


async def marker(db):
    return await db._one('SELECT * FROM audit_actions WHERE guild_id=? AND action=?', (GUILD_ID, ACTION))


async def completed(db):
    return await db._one('SELECT id FROM audit_actions WHERE guild_id=? AND action=?', (GUILD_ID, COMPLETE))


async def mark_complete(db, bot_id, now):
    # committing here also wakes the backup worker
    async with db.lock:
        await db.conn.execute('INSERT INTO audit_actions(guild_id,actor_id,action,target_id,details,created_at) VALUES (?,?,?,?,?,?)',
                              (GUILD_ID, bot_id, COMPLETE, OLD_BOARD, json.dumps({'migration': ACTION}, ensure_ascii=False), now))
        await db.conn.commit()


async def apply_records(db, old, recent, leaves, bot_id, now):
    """One transaction includes role bindings, counters, leave records and dedup marker."""
    async with db.lock:
        if await marker(db):
            return False
        await db.conn.execute('BEGIN IMMEDIATE')
        try:
            cfg = await db._one('SELECT * FROM guild_config WHERE guild_id=?', (GUILD_ID,))
            if not cfg or not cfg.get('management_category_id'):
                raise ValueError('Нет сохранённых настроек: сначала нужна проверенная копия /backup_now.')
            bindings = dict(ROLES, assistant_leader_role_id=ROLES['high_staff_role_id'],
                            role_schema_version=3, leaderboard_channel_id=BOARD_CHANNEL,
                            leaderboard_message_id=NEW_BOARD, vacation_status_channel_id=LEAVE_CHANNEL,
                            vacation_status_message_id=NEW_LEAVE)
            await db.conn.execute('UPDATE guild_config SET ' + ','.join(k+'=?' for k in bindings) + ' WHERE guild_id=?',
                                  [*bindings.values(), GUILD_ID])
            totals = {}
            for uid in old.keys() | recent.keys():
                current = await db._one('SELECT * FROM recruiter_stats WHERE guild_id=? AND recruiter_id=?', (GUILD_ID, uid))
                current = current or {'accepted_count': 0, 'rejected_count': 0}
                baseline = recent.get(uid, (0, 0))
                prior = old.get(uid, (0, 0))
                # The new message describes the same period as the current DB, not an extra period.
                totals[uid] = (max(current['accepted_count'], baseline[0]) + prior[0],
                               max(current['rejected_count'], baseline[1]) + prior[1])
                await db.conn.execute('''INSERT INTO recruiter_stats VALUES (?,?,?,?)
                    ON CONFLICT(guild_id,recruiter_id) DO UPDATE SET
                    accepted_count=excluded.accepted_count,rejected_count=excluded.rejected_count''',
                    (GUILD_ID, uid, *totals[uid]))
            imported = []
            for uid, end in leaves.items():
                existing = await db._one('SELECT * FROM vacations WHERE guild_id=? AND member_id=? ORDER BY id DESC LIMIT 1', (GUILD_ID, uid))
                # Preserve an existing leave or a recorded return; don't resurrect completed leave.
                if existing:
                    continue
                snap = json.dumps({'mode': 'role_only', 'leave_role_id': ROLES['vacation_role_id']})
                cur = await db.conn.execute('''INSERT INTO vacations
                    (guild_id,member_id,member_tag,reason,start_date,end_date,status,created_at,updated_at,role_snapshot)
                    VALUES (?,?,?,?,?,?,'approved',?,?,?)''',
                    (GUILD_ID, uid, str(uid), 'Восстановлено по сообщению '+str(OLD_LEAVE),
                     '2026-09-14', end, now, now, snap))
                imported.append(cur.lastrowid)
            details = json.dumps({'old_message': OLD_BOARD, 'new_message': NEW_BOARD,
                                  'totals': totals, 'imported_vacations': imported}, ensure_ascii=False)
            await db.conn.execute('INSERT INTO audit_actions(guild_id,actor_id,action,target_id,details,created_at) VALUES (?,?,?,?,?,?)',
                                  (GUILD_ID, bot_id, ACTION, OLD_BOARD, details, now))
            await db.conn.commit()
        except Exception:
            await db.conn.rollback()
            raise
        db._config_cache.pop(GUILD_ID, None)
    return True


async def source(bot, guild, channel_id, message_id, title):
    channel = await bot.fetch_channel(channel_id)
    if channel.guild.id != guild.id:
        raise ValueError('Исходный канал относится к другому серверу.')
    msg = await channel.fetch_message(message_id)
    if msg.author.id != bot.user.id or len(msg.embeds) != 1 or msg.embeds[0].title != title:
        raise ValueError('Неожиданный автор или формат исходного сообщения.')
    return msg.embeds[0].description or ''


async def recover(bot, guild):
    if guild.id != GUILD_ID:
        return
    async with bot.operation_locks[('setup', guild.id)]:
        if await completed(bot.db):
            return
        if not await marker(bot.db):
            # No migration against empty state: keep the new period and other records.
            cfg = await bot.db.get_config(guild.id)
            if not cfg.get('management_category_id'):
                raise ValueError('Для восстановления нужна копия действующих настроек.')
            for key, rid in ROLES.items():
                role = guild.get_role(rid)
                if not role or role.managed or role.is_default():
                    raise ValueError(f'Недоступна обычная роль {key}: {rid}')
            leave_role = guild.get_role(ROLES['vacation_role_id'])
            if not guild.me.guild_permissions.manage_roles or leave_role >= guild.me.top_role:
                raise ValueError('Роль бота должна быть выше Отдых, с правом управления ролями.')
            old = parse_board(await source(bot, guild, BOARD_CHANNEL, OLD_BOARD, '🏆 Лидерборд рекрутеров'))
            recent = parse_board(await source(bot, guild, BOARD_CHANNEL, NEW_BOARD, '🏆 Лидерборд рекрутеров'))
            leaves = parse_leaves(await source(bot, guild, LEAVE_CHANNEL, OLD_LEAVE, '🌴 Кто сейчас в отпуске'))
            await apply_records(bot.db, old, recent, leaves, bot.user.id, datetime.now(timezone.utc).isoformat())
        record = await marker(bot.db)
        # Finish idempotent Discord effects if an API error interrupted the previous attempt.
        for vid in json.loads(record['details'])['imported_vacations']:
            row = await bot.db._one('SELECT * FROM vacations WHERE id=? AND guild_id=?', (vid, GUILD_ID))
            if row and row['status'] == 'approved':
                member = guild.get_member(row['member_id']) or await guild.fetch_member(row['member_id'])
                role = guild.get_role(json.loads(row['role_snapshot'])['leave_role_id'])
                if role and not member.get_role(role.id):
                    await member.add_roles(role, reason='Colombo: восстановление одобренного отпуска')
        await bot.send_or_update_leaderboard(guild)
        await bot.update_vacation_status(guild)
        await mark_complete(bot.db, bot.user.id, datetime.now(timezone.utc).isoformat())
    await bot.backups.save(guild)
    print(f'September recovery verified | guild={guild.id} | backup={bot.backups.saved_at.get(guild.id)}')
