import asyncio
import json
import tempfile
import unittest
from collections import defaultdict
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, MagicMock

import discord

from bot.database import Database
from bot.recovery_september import (ACTION, COMPLETE, GUILD_ID, OLD_BOARD, ROLES, apply_records,
                                    completed, marker, parse_board, parse_leaves, recover)


class Parsing(unittest.TestCase):
    def test_discord_mentions_and_markdown(self):
        self.assertEqual(parse_board('🥇 <@123> — **9** принято · 1 отказов\n`#2` <@!456> — **1** принято'), {123: (9, 1), 456: (1, 0)})
        self.assertEqual(parse_leaves('🌴 <@123> — до **22.09.2026** · **8 дн.** · возврат по заявке'), {123: '2026-09-22'})

    def test_invalid_inputs_abort(self):
        for text in ('', '<@123> — 4 принято\nunknown row', '<@123> — 4 принято\n<@123> — 1 принято'):
            with self.assertRaises(ValueError):
                parse_board(text)
        with self.assertRaises(ValueError):
            parse_leaves('🌴 <@123> — до 31.02.2026')


class Recovery(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(self.tmp.name + '/db.sqlite')
        await self.db.connect()
        await self.db.set_config(GUILD_ID, management_category_id=500)
        await self.db.bump_recruiter(GUILD_ID, 1, accepted=4, rejected=2)
        await self.db.bump_recruiter(999, 1, accepted=30)

    async def asyncTearDown(self):
        await self.db.close()
        self.tmp.cleanup()

    async def test_add_old_once_keep_current_and_other_guild(self):
        args = (self.db, {1: (7, 1), 2: (9, 1)}, {1: (2, 1), 3: (1, 2)}, {2: '2026-09-22'}, 42, '2026-09-15T00:00:00+00:00')
        self.assertTrue(await apply_records(*args))
        self.assertFalse(await apply_records(*args))
        row = await self.db._one('SELECT * FROM recruiter_stats WHERE guild_id=? AND recruiter_id=1', (GUILD_ID,))
        self.assertEqual((row['accepted_count'], row['rejected_count']), (11, 3))
        other = await self.db._one('SELECT accepted_count FROM recruiter_stats WHERE guild_id=999')
        self.assertEqual(other['accepted_count'], 30)
        floor = await self.db._one('SELECT * FROM recruiter_stats WHERE guild_id=? AND recruiter_id=3', (GUILD_ID,))
        self.assertEqual((floor['accepted_count'], floor['rejected_count']), (1, 2))
        cfg = await self.db.get_config(GUILD_ID)
        self.assertTrue(all(cfg[k] == v for k, v in ROLES.items()))
        leave = await self.db._one('SELECT * FROM vacations WHERE guild_id=?', (GUILD_ID,))
        self.assertEqual(leave['end_date'], '2026-09-22')
        self.assertEqual(json.loads(leave['role_snapshot'])['mode'], 'role_only')
        self.assertIsNotNone(await marker(self.db))

    async def test_transaction_rolls_back_on_invalid_leave_date_payload(self):
        with self.assertRaises(Exception):
            await apply_records(self.db, {1: (7, 1)}, {}, {2: None}, 42, 'now')
        self.assertIsNone(await marker(self.db))
        cfg = await self.db.get_config(GUILD_ID)
        self.assertIsNone(cfg['guest_role_id'])
        row = await self.db._one('SELECT accepted_count FROM recruiter_stats WHERE guild_id=?', (GUILD_ID,))
        self.assertEqual(row['accepted_count'], 4)

    async def test_recorded_return_is_not_reopened(self):
        await self.db.conn.execute("INSERT INTO vacations(guild_id,member_id,member_tag,reason,start_date,end_date,status,created_at,updated_at) VALUES (?,2,'2','x','2026-09-14','2026-09-22','returned','x','x')", (GUILD_ID,))
        await self.db.conn.commit()
        await apply_records(self.db, {1: (1, 0)}, {}, {2: '2026-09-22'}, 42, 'now')
        rows = await self.db._all('SELECT status FROM vacations')
        self.assertEqual(rows, [{'status': 'returned'}])


class RecoveryVerification(unittest.IsolatedAsyncioTestCase):
    """A verified recovery must not repeat its Discord effects on later startups."""

    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(self.tmp.name + '/db.sqlite')
        await self.db.connect()
        await self.db.set_config(GUILD_ID, management_category_id=500)
        self.guild = MagicMock(spec=discord.Guild)
        self.guild.id = GUILD_ID
        self.guild.get_member.return_value = None
        self.bot = NS(db=self.db, user=NS(id=42), operation_locks=defaultdict(asyncio.Lock),
                      send_or_update_leaderboard=AsyncMock(), update_vacation_status=AsyncMock(),
                      backups=NS(save=AsyncMock(), saved_at={}))

    async def asyncTearDown(self):
        await self.db.close()
        self.tmp.cleanup()

    async def seed(self, action):
        await self.db.conn.execute(
            "INSERT INTO audit_actions(guild_id,actor_id,action,target_id,details,created_at) VALUES (?,?,?,?,?,?)",
            (GUILD_ID, 42, action, OLD_BOARD, json.dumps({'imported_vacations': []}), '2026-09-15T00:00:00+00:00'))
        await self.db.conn.commit()

    async def test_verified_recovery_runs_once_then_stays_silent(self):
        await self.seed(ACTION)
        self.assertIsNone(await completed(self.db))
        await recover(self.bot, self.guild)
        self.bot.backups.save.assert_awaited_once()
        self.bot.send_or_update_leaderboard.assert_awaited_once()
        self.bot.update_vacation_status.assert_awaited_once()
        self.assertIsNotNone(await completed(self.db))
        # Later restarts: no panels, no snapshot upload.
        for _ in range(2):
            await recover(self.bot, self.guild)
        self.bot.backups.save.assert_awaited_once()
        self.bot.send_or_update_leaderboard.assert_awaited_once()

    async def test_unapplied_migration_is_not_marked_complete(self):
        # Missing source messages/roles abort before verification, so retries stay possible.
        with self.assertRaises(ValueError):
            await recover(self.bot, self.guild)
        self.assertIsNone(await completed(self.db))
        self.bot.backups.save.assert_not_awaited()
        self.bot.send_or_update_leaderboard.assert_not_awaited()

    async def test_other_guild_is_ignored(self):
        await self.seed(ACTION)
        self.guild.id = 7
        await recover(self.bot, self.guild)
        self.bot.backups.save.assert_not_awaited()
        self.assertIsNone(await completed(self.db))

    async def test_concurrent_recovery_finishes_once(self):
        await self.seed(ACTION)
        await asyncio.gather(recover(self.bot, self.guild), recover(self.bot, self.guild))
        self.bot.send_or_update_leaderboard.assert_awaited_once()
        rows = await self.db._all('SELECT id FROM audit_actions WHERE guild_id=? AND action=?', (GUILD_ID, COMPLETE))
        self.assertEqual(len(rows), 1)
