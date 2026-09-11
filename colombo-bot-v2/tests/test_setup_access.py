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

    async def test_both_commands_gate_roles_and_forward_main(self):
        for name in ('setup', 'setup_auto'):
            command = self.bot.tree.get_command(name)
            self.assertTrue({'main','guest','test','colombo'}.issubset({p.name for p in command.parameters}))
            for role_id in (1, 2, 3):
                self.assertTrue(await command.checks[0](self.interaction(role_id)))
            for role_id in (4, 5, None):
                with self.assertRaises(app_commands.CheckFailure):
                    await command.checks[0](self.interaction(role_id))
            self.assertTrue(await command.checks[0](self.interaction(None, owner=True)))
            selected = object()
            i = self.interaction(3)
            with patch('bot.provisioning.provision', new_callable=AsyncMock) as provision:
                await command.callback(i, main=selected)
                self.assertIs(provision.call_args.args[2]['main_role_id'], selected)
