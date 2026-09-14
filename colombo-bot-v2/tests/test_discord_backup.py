import copy
import tempfile
import unittest
from pathlib import Path
from bot.database import Database
from bot.discord_backup import snapshot, encode, decode, restore_payload, change_lines


class DiscordStorage(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(str(Path(self.tmp.name) / 'source.db'))
        self.restored = Database(str(Path(self.tmp.name) / 'restored.db'))
        await self.db.connect()
        await self.restored.connect()
        await self.db.set_config(1, high_staff_role_id=20, recruiter_role_id=10)
        await self.db.set_config(2, high_staff_role_id=200)
        await self.db.bump_recruiter(1, 30, accepted=8, rejected=2)
        await self.db.bump_recruiter(2, 40, accepted=99)
        await self.db.conn.execute("INSERT INTO family_events(guild_id,channel_id,creator_id,kind,title,starts_at,capacity) VALUES(1,50,30,'capt','test',1,10)")
        await self.db.conn.execute("INSERT INTO event_signups(event_id,member_id,joined_at,attended,confirmed_by) VALUES(1,60,'2026-09-14',1,30)")
        await self.db.conn.commit()

    async def asyncTearDown(self):
        await self.db.close()
        await self.restored.close()
        self.tmp.cleanup()

    async def test_restore_counters_config_and_attendance(self):
        payload = await snapshot(self.db, 1)
        blob, checksum = encode(payload)
        verified = decode(blob, checksum, 1)
        self.assertEqual(len(verified['tables']['recruiter_stats']), 1)
        self.assertTrue(await restore_payload(self.restored, verified))
        self.assertEqual((await self.restored.get_config(1))['high_staff_role_id'], 20)
        self.assertEqual((await self.restored.leaderboard(1))[0]['accepted_count'], 8)
        self.assertEqual((await self.restored._one('SELECT * FROM event_signups'))['attended'], 1)
        self.assertEqual(await self.restored.leaderboard(2), [])
        self.assertFalse(await restore_payload(self.restored, verified))

    async def test_checksum_and_other_guild_rejected(self):
        payload = await snapshot(self.db, 1)
        blob, checksum = encode(payload)
        with self.assertRaises(ValueError):
            decode(blob + b'x', checksum, 1)
        with self.assertRaises(ValueError):
            decode(blob, checksum, 2)
        payload['tables']['recruiter_stats'][0]['guild_id'] = 2
        blob, checksum = encode(payload)
        with self.assertRaises(ValueError):
            decode(blob, checksum, 1)

    async def test_invalid_columns_roll_back_all_tables(self):
        payload = await snapshot(self.db, 1)
        payload['tables']['event_signups'][0]['unknown_column'] = 1
        with self.assertRaises(ValueError):
            await restore_payload(self.restored, payload)
        self.assertIsNone(await self.restored._one('SELECT * FROM guild_config WHERE guild_id=1'))
        self.assertEqual(await self.restored.leaderboard(1), [])

    async def test_logs_include_recruiter_counters_and_attendance(self):
        payload = await snapshot(self.db, 1)
        text = '\n'.join(change_lines(None, payload))
        self.assertIn('принято 8', text)
        self.assertIn('отказов 2', text)
        self.assertIn('присутствие: да', text)
        self.assertEqual(change_lines(payload, payload), [])
