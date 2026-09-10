"""Additive migration: keeps source records and old attendance confirmations intact."""
async def migrate(conn):
    additions = {
        'family_events': {'reserve_capacity': 'INTEGER NOT NULL DEFAULT 0'},
        'event_signups': {'seat': "TEXT NOT NULL DEFAULT 'main'", 'confirmed_by': 'INTEGER', 'confirmed_at': 'TEXT'},
        'vacations': {'role_snapshot': 'TEXT', 'added_novice': 'INTEGER NOT NULL DEFAULT 0',
                      'return_reason': 'TEXT', 'return_comment': 'TEXT', 'return_thread_id': 'INTEGER',
                      'return_message_id': 'INTEGER'},
        'personal_cases': {'profile_message_id': 'INTEGER'},
        'activity_submissions': {'event_id': 'INTEGER'},
    }
    for table, columns in additions.items():
        cur = await conn.execute(f'PRAGMA table_info({table})')
        existing = {r[1] for r in await cur.fetchall()}
        for name, kind in columns.items():
            if name not in existing:
                await conn.execute(f'ALTER TABLE {table} ADD COLUMN {name} {kind}')
    await conn.executescript('''
        CREATE TABLE IF NOT EXISTS audit_actions (
            id INTEGER PRIMARY KEY AUTOINCREMENT, guild_id INTEGER NOT NULL,
            actor_id INTEGER NOT NULL, action TEXT NOT NULL, target_id INTEGER NOT NULL,
            details TEXT NOT NULL, created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_signups_member ON event_signups(member_id,attended);
        CREATE INDEX IF NOT EXISTS idx_events_guild ON family_events(guild_id,starts_at);
    ''')
