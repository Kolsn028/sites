import copy
import tempfile
import unittest
import asyncio
from collections import defaultdict
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from pathlib import Path
from bot.database import Database
from bot.discord_backup import snapshot, encode, decode, restore_payload, change_lines, DiscordBackups


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

    async def test_throttled_auto_save_manual_bypass_and_log_retry(self):
        bot = SimpleNamespace(db=self.db, operation_locks=defaultdict(asyncio.Lock))
        backups = DiscordBackups(bot)
        guild = SimpleNamespace(id=1)
        backup_channel, log_channel = SimpleNamespace(send=AsyncMock()), SimpleNamespace(send=AsyncMock())
        async def upload(**kwargs):
            blob = kwargs['file'].fp.getvalue()
            return SimpleNamespace(attachments=[SimpleNamespace(read=AsyncMock(return_value=blob))])
        backup_channel.send.side_effect = upload
        backups.ensure_channels = AsyncMock(return_value={'backup': backup_channel, 'logs': log_channel})
        with patch('bot.discord_backup.monotonic', return_value=100):
            log_channel.send.side_effect = RuntimeError('temporary log failure')
            with self.assertRaises(RuntimeError):
                await backups.save(guild, automatic=True)
            self.assertIn(1, backups.hashes)
            await backups.save(guild, automatic=True)
            backup_channel.send.assert_awaited_once()
            log_channel.send.side_effect = None
            await backups.save(guild)  # retry log without uploading identical data
            backup_channel.send.assert_awaited_once()
            self.assertNotIn(1, backups.pending_logs)
            await self.db.bump_recruiter(1, 30, accepted=1)
            await backups.save(guild, automatic=True)
            backup_channel.send.assert_awaited_once()
            await backups.save(guild)  # explicit save bypasses interval
            self.assertEqual(backup_channel.send.await_count, 2)
        await self.db.bump_recruiter(1, 30, accepted=1)
        with patch('bot.discord_backup.monotonic', return_value=161):
            await backups.save(guild, automatic=True)
            self.assertEqual(backup_channel.send.await_count, 3)

    async def test_large_log_uses_one_message_and_complete_attachment(self):
        backups = DiscordBackups(SimpleNamespace())
        lines = [f'Изменение {n} ' + 'x' * 100 for n in range(50)]
        backups.pending_logs[1] = lines.copy()
        channel = SimpleNamespace(send=AsyncMock())
        await backups.flush_logs(1, channel)
        channel.send.assert_awaited_once()
        call = channel.send.call_args
        self.assertLess(len(call.args[0]), 2000)
        self.assertEqual(call.kwargs['file'].fp.getvalue().decode(), '\n'.join(lines))
