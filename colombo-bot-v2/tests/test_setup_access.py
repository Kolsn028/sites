import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
import discord
from discord.ext import commands
from discord import app_commands
from bot.commands import register_commands


class SetupAccess(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.bot = commands.Bot(command_prefix='!', intents=discord.Intents.none())
        self.cfg = dict(role_schema_version=2, leader_role_id=1,
                        dep_leader_role_id=2, high_staff_role_id=3,
                        recruiter_role_id=4, main_role_id=5)
        self.bot.db = SimpleNamespace(get_config=AsyncMock(return_value=self.cfg))
        register_commands(self.bot)

    async def asyncTearDown(self):
        await self.bot.close()

    def interaction(self, role_id, owner=False):
        member = MagicMock(spec=discord.Member)
        member.id = 99 if owner else 10
        member.guild = SimpleNamespace(owner_id=99)
        member.get_role.side_effect = lambda rid: object() if rid == role_id else None
        return SimpleNamespace(user=member, guild_id=100, guild=member.guild,
            response=SimpleNamespace(defer=AsyncMock()),
            followup=SimpleNamespace(send=AsyncMock()))

    async def test_only_leader_can_setup_and_auto_is_removed(self):
        self.assertIsNone(self.bot.tree.get_command('setup_auto'))
        command = self.bot.tree.get_command('setup')
        self.assertTrue({'main','guest','test','colombo','high'}.issubset({p.name for p in command.parameters}))
        self.assertTrue(await command.checks[0](self.interaction(1)))
        for role_id in (2, 3, 4, 5, None):
            for owner in (False, True):
                i = self.interaction(role_id, owner=owner)
                i.user.guild_permissions = discord.Permissions(administrator=True)
                with self.assertRaises(app_commands.CheckFailure):
                    await command.checks[0](i)
        selected = object()
        with patch('bot.provisioning.provision', new_callable=AsyncMock) as provision:
            await command.callback(self.interaction(1), main=selected)
            self.assertIs(provision.call_args.args[2]['main_role_id'], selected)

    async def test_guild_sync_removes_old_auto_command(self):
        from collections import defaultdict
        import asyncio
        from bot.core import ColomboBot
        guild = SimpleNamespace(id=100)
        stale = SimpleNamespace(name='setup_auto', options=[])
        setup = SimpleNamespace(name='setup', options=[SimpleNamespace(name=n) for n in ('main','guest','test','colombo')])
        registered = [setup, stale]
        async def sync(**kwargs):
            registered[:] = [setup]
        tree = SimpleNamespace(copy_global_to=MagicMock(), sync=AsyncMock(side_effect=sync),
                               fetch_commands=AsyncMock(side_effect=lambda **kw: registered))
        bot = SimpleNamespace(tree=tree, operation_locks=defaultdict(asyncio.Lock))
        await ColomboBot.sync_guild_commands(bot, guild)
        self.assertEqual([c.name for c in registered], ['setup'])
        self.assertEqual(bot._commands_synced, {100})
