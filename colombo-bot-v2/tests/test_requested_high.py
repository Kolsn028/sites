import asyncio
import tempfile
import unittest
from collections import defaultdict
from datetime import datetime, timezone
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, MagicMock, patch
import discord
from bot.database import Database
from bot.requested_high_grant import apply
GUILD_ID, MEMBER_ID, ROLE_ID = 100, 200, 300


class RequestedHigh(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.env = patch.dict('os.environ', {'REQUESTED_MAIN_GUILD_ID':str(GUILD_ID),
            'REQUESTED_MAIN_MEMBER_ID':str(MEMBER_ID), 'REQUESTED_MAIN_ROLE_ID':str(ROLE_ID)})
        self.env.start()
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(self.tmp.name + '/db')
        await self.db.connect()
        await self.db.set_config(GUILD_ID, main_role_id=ROLE_ID)
        self.held = set()
        role = MagicMock(spec=discord.Role)
        role.id = ROLE_ID
        role.managed = False
        role.is_default.return_value = False
        role.__ge__.return_value = False
        async def add(r, **kw):
            self.bot.backups.save.assert_awaited_once()
            self.held.add(r.id)
        self.member = NS(get_role=lambda rid: rid in self.held, add_roles=AsyncMock(side_effect=add))
        self.guild = NS(id=GUILD_ID, get_role=lambda rid: role if rid == ROLE_ID else None,
                        fetch_member=AsyncMock(return_value=self.member),
                        me=NS(top_role=object(), guild_permissions=NS(manage_roles=True)))
        self.bot = NS(db=self.db, user=NS(id=999), operation_locks=defaultdict(asyncio.Lock),
                      backups=NS(save=AsyncMock()))
        self.clock = patch('bot.requested_high_grant.datetime')
        self.mock_clock = self.clock.start()
        self.mock_clock.now.return_value = datetime(2026,9,21,12,tzinfo=timezone.utc)

    async def asyncTearDown(self):
        self.clock.stop()
        self.env.stop()
        await self.db.close()
        self.tmp.cleanup()

    async def test_grant_exact_member_once_and_do_not_restore_manual_removal(self):
        await apply(self.bot, self.guild)
        self.assertEqual(self.held, {ROLE_ID})
        self.assertTrue(all(call.args == (MEMBER_ID,) for call in self.guild.fetch_member.call_args_list))
        self.held.clear()
        await self.db.close()
        await self.db.connect()
        await apply(self.bot, self.guild)
        self.member.add_roles.assert_awaited_once()
        self.assertEqual(self.held, set())

    async def test_backup_failure_prevents_role_change(self):
        self.bot.backups.save.side_effect = RuntimeError('backup unavailable')
        with self.assertRaises(RuntimeError): await apply(self.bot, self.guild)
        self.member.add_roles.assert_not_awaited()

    async def test_wrong_guild_and_expired_request_do_nothing(self):
        await apply(self.bot, NS(id=1))
        self.mock_clock.now.return_value = datetime(2026,9,22,tzinfo=timezone.utc)
        await apply(self.bot, self.guild)
        self.guild.fetch_member.assert_not_awaited()
        self.member.add_roles.assert_not_awaited()
