from __future__ import annotations
import asyncio
import json
from pathlib import Path
import aiosqlite


class Database:
    def __init__(self, path: str):
        self.path = path
        self.conn: aiosqlite.Connection | None = None
        self.lock = asyncio.Lock()
        self._config_cache: dict[int, dict] = {}

    async def connect(self):
        if self.conn:
            return
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = await aiosqlite.connect(self.path)
        self.conn.row_factory = aiosqlite.Row
        await self.conn.executescript('''
        CREATE TABLE IF NOT EXISTS progress_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL, member_id INTEGER NOT NULL, kind TEXT NOT NULL,
            thread_id INTEGER NOT NULL UNIQUE, details TEXT NOT NULL, created_at TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending', handled_by INTEGER, decision TEXT
        );
        CREATE UNIQUE INDEX IF NOT EXISTS idx_progress_pending
            ON progress_requests(guild_id,member_id,kind) WHERE status='pending';
        CREATE TABLE IF NOT EXISTS family_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT, guild_id INTEGER NOT NULL,
            channel_id INTEGER NOT NULL, message_id INTEGER UNIQUE, creator_id INTEGER NOT NULL,
            kind TEXT NOT NULL, title TEXT NOT NULL, starts_at INTEGER NOT NULL,
            capacity INTEGER NOT NULL CHECK(capacity BETWEEN 1 AND 100), details TEXT,
            status TEXT NOT NULL DEFAULT 'open'
        );
        CREATE TABLE IF NOT EXISTS event_signups (
            event_id INTEGER NOT NULL REFERENCES family_events(id) ON DELETE CASCADE,
            member_id INTEGER NOT NULL, joined_at TEXT NOT NULL, attended INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY(event_id,member_id)
        );
        PRAGMA journal_mode=WAL;
        PRAGMA synchronous=NORMAL;
        PRAGMA foreign_keys=ON;

        CREATE TABLE IF NOT EXISTS guild_config (
            guild_id INTEGER PRIMARY KEY,
            application_panel_channel_id INTEGER,
            applications_log_channel_id INTEGER,
            applications_parent_channel_id INTEGER,
            recruiter_role_id INTEGER,
            interview_channel_id INTEGER,
            interview_voice_channel_id INTEGER,
            accepted_role_id INTEGER,
            vacation_panel_channel_id INTEGER,
            vacation_review_channel_id INTEGER,
            vacation_status_channel_id INTEGER,
            assistant_leader_role_id INTEGER,
            dep_leader_role_id INTEGER,
            vacation_role_id INTEGER,
            leaderboard_channel_id INTEGER,
            leaderboard_message_id INTEGER,
            vacation_status_message_id INTEGER,
            case_panel_channel_id INTEGER,
            case_category_id INTEGER,
            high_staff_role_id INTEGER,
            activity_log_channel_id INTEGER,
            inactivity_report_channel_id INTEGER,
            inactivity_report_message_id INTEGER
        );

        CREATE TABLE IF NOT EXISTS applications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            applicant_id INTEGER NOT NULL,
            applicant_tag TEXT NOT NULL,
            real_name_age TEXT NOT NULL,
            majestic_experience TEXT NOT NULL,
            shooting_skill TEXT NOT NULL,
            level_online_tz TEXT NOT NULL,
            family_experience TEXT NOT NULL,
            extra TEXT,
            status TEXT NOT NULL DEFAULT 'pending',
            thread_id INTEGER,
            log_message_id INTEGER,
            handled_by INTEGER,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_app_thread ON applications(guild_id, thread_id);

        CREATE TABLE IF NOT EXISTS recruiter_stats (
            guild_id INTEGER NOT NULL,
            recruiter_id INTEGER NOT NULL,
            accepted_count INTEGER NOT NULL DEFAULT 0,
            rejected_count INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (guild_id, recruiter_id)
        );

        CREATE TABLE IF NOT EXISTS vacations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            member_id INTEGER NOT NULL,
            member_tag TEXT NOT NULL,
            reason TEXT NOT NULL,
            start_date TEXT NOT NULL,
            end_date TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            review_message_id INTEGER,
            handled_by INTEGER,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_vacation_active ON vacations(guild_id, status, end_date);

        CREATE TABLE IF NOT EXISTS personal_cases (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            member_id INTEGER NOT NULL,
            channel_id INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'active',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(guild_id, member_id),
            UNIQUE(guild_id, channel_id)
        );
        CREATE INDEX IF NOT EXISTS idx_case_channel ON personal_cases(guild_id, channel_id);

        CREATE TABLE IF NOT EXISTS activity_submissions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            member_id INTEGER NOT NULL,
            case_channel_id INTEGER NOT NULL,
            source_message_id INTEGER NOT NULL,
            review_message_id INTEGER,
            attachment_urls TEXT NOT NULL,
            category TEXT NOT NULL DEFAULT 'unclassified',
            points INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'pending_classification',
            note TEXT,
            handled_by INTEGER,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(guild_id, source_message_id)
        );
        CREATE INDEX IF NOT EXISTS idx_activity_member ON activity_submissions(guild_id, member_id, status, created_at);
        CREATE INDEX IF NOT EXISTS idx_activity_review ON activity_submissions(guild_id, status, review_message_id);
        ''')
        cur = await self.conn.execute("PRAGMA table_info(guild_config)")
        existing = {row[1] for row in await cur.fetchall()}
        needed = {
            "main_role_id": "INTEGER",
            "contract_panel_channel_id": "INTEGER",
            "contract_panel_message_id": "INTEGER",
            "promotion_panel_channel_id": "INTEGER",
            "promotion_panel_message_id": "INTEGER",
            "server_layout_version": "INTEGER",
            "case_panel_channel_id": "INTEGER",
            "interview_voice_2_id": "INTEGER",
            "interview_voice_3_id": "INTEGER",
            "recruitment_category_id": "INTEGER",
            "leader_role_id": "INTEGER",
            "role_schema_version": "INTEGER",
            "colombo_role_id": "INTEGER",
            "family_category_id": "INTEGER",
            "management_category_id": "INTEGER",
            "application_panel_message_id": "INTEGER",
            "vacation_panel_message_id": "INTEGER",
            "case_panel_message_id": "INTEGER",
            "case_category_id": "INTEGER",
            "high_staff_role_id": "INTEGER",
            "activity_log_channel_id": "INTEGER",
            "inactivity_report_channel_id": "INTEGER",
            "inactivity_report_message_id": "INTEGER",
        }
        needed['events_category_id'] = 'INTEGER'
        for kind in ('mcl','vzm','vzz','capt'):
            needed[f'{kind}_panel_channel_id'] = 'INTEGER'
            needed[f'{kind}_panel_message_id'] = 'INTEGER'
        for column, sql_type in needed.items():
            if column not in existing:
                await self.conn.execute(f"ALTER TABLE guild_config ADD COLUMN {column} {sql_type}")
        cur = await self.conn.execute("PRAGMA table_info(vacations)")
        if "thread_id" not in {row[1] for row in await cur.fetchall()}:
            await self.conn.execute("ALTER TABLE vacations ADD COLUMN thread_id INTEGER")
        cur = await self.conn.execute("PRAGMA table_info(applications)")
        columns = {row[1] for row in await cur.fetchall()}
        for column, sql_type in {"assigned_to": "INTEGER", "interview_room_id": "INTEGER", "interview_until": "TEXT"}.items():
            if column not in columns:
                await self.conn.execute(f"ALTER TABLE applications ADD COLUMN {column} {sql_type}")
        from .schema_v9 import migrate
        await migrate(self.conn)
        await self.conn.commit()

    async def close(self):
        if self.conn:
            await self.conn.close(); self.conn = None

    async def _one(self, sql, params=()):
        cur = await self.conn.execute(sql, params); row = await cur.fetchone(); return dict(row) if row else None

    async def _all(self, sql, params=()):
        cur = await self.conn.execute(sql, params); return [dict(x) for x in await cur.fetchall()]

    async def ensure_guild(self, guild_id: int):
        async with self.lock:
            await self.conn.execute('INSERT OR IGNORE INTO guild_config (guild_id) VALUES (?)', (guild_id,)); await self.conn.commit()

    async def get_config(self, guild_id: int):
        if guild_id in self._config_cache: return dict(self._config_cache[guild_id])
        await self.ensure_guild(guild_id)
        row = await self._one('SELECT * FROM guild_config WHERE guild_id=?', (guild_id,)) or {'guild_id': guild_id}
        self._config_cache[guild_id] = row; return dict(row)

    async def set_config(self, guild_id: int, **kwargs):
        if not kwargs: return
        await self.ensure_guild(guild_id); cols = ', '.join(f'{k}=?' for k in kwargs)
        async with self.lock:
            await self.conn.execute(f'UPDATE guild_config SET {cols} WHERE guild_id=?', [*kwargs.values(), guild_id]); await self.conn.commit()
        self._config_cache.pop(guild_id, None)

    async def create_application(self, **data):
        async with self.lock:
            cur = await self.conn.execute(f"INSERT INTO applications ({', '.join(data)}) VALUES ({', '.join('?' for _ in data)})", tuple(data.values())); await self.conn.commit(); return cur.lastrowid

    async def update_application(self, application_id: int, **data):
        if not data: return
        cols = ', '.join(f'{k}=?' for k in data)
        async with self.lock:
            await self.conn.execute(f'UPDATE applications SET {cols} WHERE id=?', [*data.values(), application_id]); await self.conn.commit()

    async def get_application_by_thread(self, guild_id: int, thread_id: int):
        return await self._one('SELECT * FROM applications WHERE guild_id=? AND thread_id=? ORDER BY id DESC LIMIT 1', (guild_id, thread_id))

    async def bump_recruiter(self, guild_id, recruiter_id, accepted=0, rejected=0):
        async with self.lock:
            await self.conn.execute('''INSERT INTO recruiter_stats (guild_id,recruiter_id,accepted_count,rejected_count) VALUES (?,?,?,?) ON CONFLICT(guild_id,recruiter_id) DO UPDATE SET accepted_count=accepted_count+excluded.accepted_count,rejected_count=rejected_count+excluded.rejected_count''', (guild_id,recruiter_id,accepted,rejected)); await self.conn.commit()

    async def leaderboard(self, guild_id, limit=10):
        return await self._all('SELECT recruiter_id,accepted_count,rejected_count FROM recruiter_stats WHERE guild_id=? ORDER BY accepted_count DESC,rejected_count ASC LIMIT ?', (guild_id,limit))

    async def create_vacation(self, **data):
        async with self.lock:
            cur = await self.conn.execute(f"INSERT INTO vacations ({', '.join(data)}) VALUES ({', '.join('?' for _ in data)})", tuple(data.values())); await self.conn.commit(); return cur.lastrowid

    async def update_vacation(self, vacation_id, **data):
        if not data: return
        cols=', '.join(f'{k}=?' for k in data)
        async with self.lock:
            await self.conn.execute(f'UPDATE vacations SET {cols} WHERE id=?', [*data.values(), vacation_id]); await self.conn.commit()

    async def get_vacation(self, vacation_id): return await self._one('SELECT * FROM vacations WHERE id=?', (vacation_id,))
    async def active_vacations(self, guild_id): return await self._all("SELECT * FROM vacations WHERE guild_id=? AND status IN ('applying','approved','return_pending','restoring') ORDER BY end_date", (guild_id,))
    async def pending_vacation_for_member(self, guild_id, member_id): return await self._one("SELECT * FROM vacations WHERE guild_id=? AND member_id=? AND status IN ('pending','applying','approved','return_pending','restoring') ORDER BY id DESC LIMIT 1", (guild_id,member_id))

    async def create_case(self, guild_id, member_id, channel_id, now_iso):
        async with self.lock:
            await self.conn.execute('''INSERT INTO personal_cases (guild_id,member_id,channel_id,status,created_at,updated_at) VALUES (?,?,?,'active',?,?) ON CONFLICT(guild_id,member_id) DO UPDATE SET channel_id=excluded.channel_id,status='active',updated_at=excluded.updated_at''', (guild_id,member_id,channel_id,now_iso,now_iso)); await self.conn.commit()

    async def get_case_by_member(self, guild_id, member_id): return await self._one("SELECT * FROM personal_cases WHERE guild_id=? AND member_id=? AND status='active'", (guild_id,member_id))
    async def get_case_by_channel(self, guild_id, channel_id): return await self._one("SELECT * FROM personal_cases WHERE guild_id=? AND channel_id=? AND status='active'", (guild_id,channel_id))

    async def create_activity(self, guild_id, member_id, case_channel_id, source_message_id, attachment_urls, now_iso):
        try:
            async with self.lock:
                cur = await self.conn.execute('''INSERT INTO activity_submissions (guild_id,member_id,case_channel_id,source_message_id,attachment_urls,category,points,status,created_at,updated_at) VALUES (?,?,?,?,?,'unclassified',0,'pending_classification',?,?)''', (guild_id,member_id,case_channel_id,source_message_id,json.dumps(attachment_urls,ensure_ascii=False),now_iso,now_iso)); await self.conn.commit(); return cur.lastrowid
        except aiosqlite.IntegrityError: return None

    async def get_activity(self, submission_id): return await self._one('SELECT * FROM activity_submissions WHERE id=?', (submission_id,))

    async def update_activity(self, submission_id, **data):
        if not data: return
        cols=', '.join(f'{k}=?' for k in data)
        async with self.lock:
            await self.conn.execute(f'UPDATE activity_submissions SET {cols} WHERE id=?', [*data.values(),submission_id]); await self.conn.commit()

    async def member_activity_stats(self, guild_id, member_id, days=None):
        where="guild_id=? AND member_id=? AND status='approved'"; params=[guild_id,member_id]
        if days is not None: where += " AND datetime(created_at)>=datetime('now',?)"; params.append(f'-{days} days')
        rows=await self._all(f'SELECT category,COUNT(*) count,COALESCE(SUM(points),0) points FROM activity_submissions WHERE {where} GROUP BY category', tuple(params))
        last=await self._one("SELECT created_at,category,points FROM activity_submissions WHERE guild_id=? AND member_id=? AND status='approved' ORDER BY created_at DESC LIMIT 1", (guild_id,member_id)); return rows,last

    async def activity_top(self, guild_id, days, limit=10):
        return await self._all('''SELECT member_id,COUNT(*) reports,COALESCE(SUM(points),0) points,MAX(created_at) last_activity FROM activity_submissions WHERE guild_id=? AND status='approved' AND datetime(created_at)>=datetime('now',?) GROUP BY member_id ORDER BY points DESC,reports DESC,last_activity DESC LIMIT ?''', (guild_id,f'-{days} days',limit))

    async def last_activity_for_cases(self, guild_id):
        return await self._all("""SELECT c.member_id,c.channel_id,c.created_at case_created_at,
          (SELECT MAX(ts) FROM (
            SELECT datetime(a.created_at) ts FROM activity_submissions a WHERE a.guild_id=c.guild_id AND a.member_id=c.member_id AND a.status='approved'
            UNION ALL SELECT datetime(e.starts_at,'unixepoch') FROM family_events e JOIN event_signups s ON s.event_id=e.id
              WHERE e.guild_id=c.guild_id AND s.member_id=c.member_id AND s.attended=1
            UNION ALL SELECT datetime(p.created_at) FROM progress_requests p WHERE p.guild_id=c.guild_id AND p.member_id=c.member_id AND p.kind='contract' AND p.status='approved'
          )) last_activity FROM personal_cases c WHERE c.guild_id=? AND c.status='active'""", (guild_id,))


    async def claim_application(self, app_id, recruiter_id, now):
        async with self.lock:
            cur = await self.conn.execute("UPDATE applications SET assigned_to=?,updated_at=? WHERE id=? AND status IN ('pending','interview') AND assigned_to IS NULL", (recruiter_id,now,app_id))
            await self.conn.commit()
            return cur.rowcount == 1

    async def release_application(self, app_id, now):
        async with self.lock:
            await self.conn.execute("UPDATE applications SET assigned_to=NULL,interview_room_id=NULL,interview_until=NULL,status='pending',updated_at=? WHERE id=? AND status IN ('pending','interview')", (now,app_id))
            await self.conn.commit()

    async def reserve_interview(self, app_id, guild_id, available_ids, now, until):
        # Atomic allocation across all applications; empty channels can already be reserved.
        async with self.lock:
            app = await self._one("SELECT * FROM applications WHERE id=? AND guild_id=? AND status IN ('pending','interview')", (app_id,guild_id))
            if not app or not app['assigned_to']:
                return None
            rows = await self._all("SELECT interview_room_id FROM applications WHERE guild_id=? AND id<>? AND status='interview' AND interview_until>?", (guild_id,app_id,now))
            taken = {row['interview_room_id'] for row in rows}
            room = next((rid for rid in available_ids if rid not in taken), None)
            if room is None:
                return None
            await self.conn.execute("UPDATE applications SET interview_room_id=?,interview_until=?,status='interview',updated_at=? WHERE id=?", (room,until,now,app_id))
            await self.conn.commit()
            return room

    async def clear_interview(self, app_id, now):
        async with self.lock:
            await self.conn.execute("UPDATE applications SET interview_room_id=NULL,interview_until=NULL,status='pending',updated_at=? WHERE id=? AND status='interview'", (now,app_id))
            await self.conn.commit()
