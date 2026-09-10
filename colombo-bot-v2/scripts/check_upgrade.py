"""Validate additive migration on an operator-provided staging copy, never export data."""
import asyncio,sqlite3,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from bot.database import Database

async def main(path):
    if not Path(path).is_file():raise SystemExit('Existing staging database required.')
    conn=sqlite3.connect(path)
    if conn.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise SystemExit('Integrity check failed.')
    tables=['applications','vacations','personal_cases','activity_submissions','progress_requests','family_events','event_signups']
    existing={r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    counts={t:conn.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0] for t in tables if t in existing}
    conn.close()
    db=Database(path);await db.connect()
    for t,n in counts.items():
        assert (await db._one(f'SELECT COUNT(*) n FROM {t}'))['n']==n, f'Count changed: {t}'
    assert (await db._one('PRAGMA integrity_check'))['integrity_check']=='ok'
    await db.close()
    print('Migration OK. Source-table counts unchanged:',counts)

if __name__=='__main__':
    if len(sys.argv)!=2:raise SystemExit('Usage: check_upgrade.py /private/staging/bot.db')
    asyncio.run(main(sys.argv[1]))
