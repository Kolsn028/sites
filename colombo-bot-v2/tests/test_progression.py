import asyncio
import tempfile
import unittest
from collections import defaultdict
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
import discord
from bot.database import Database
from bot.legacy import merge_overwrite, migrate_legacy
from bot.progression import DecisionModal

class Progression(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.db=Database(self.tmp.name+'/test.db'); await self.db.connect()
        await self.db.conn.execute("INSERT INTO progress_requests(guild_id,member_id,kind,thread_id,details,created_at) VALUES (1,10,'promotion',100,'proofs','2026-09-09')")
        await self.db.conn.commit()
        self.bot=SimpleNamespace(db=self.db,operation_locks=defaultdict(asyncio.Lock),can_promote=AsyncMock(return_value=True),is_high_staff=AsyncMock(return_value=True),is_family_member=AsyncMock(return_value=True))
        self.i=MagicMock(spec=discord.Interaction);self.i.guild_id=1
        self.i.user=MagicMock(spec=discord.Member);self.i.user.id=20;self.i.user.mention='<@20>'
        self.i.guild=MagicMock(spec=discord.Guild)
        self.i.response=SimpleNamespace(defer=AsyncMock(),send_message=AsyncMock());self.i.followup=SimpleNamespace(send=AsyncMock())
        self.i.channel=MagicMock(spec=discord.Thread);self.i.channel.send=AsyncMock();self.i.channel.edit=AsyncMock()
    async def asyncTearDown(self):
        await self.db.close();self.tmp.cleanup()
    async def row(self): return await self.db._one('SELECT * FROM progress_requests WHERE thread_id=100')
    async def test_checklist_required_and_double_decision_blocked(self):
        modal=DecisionModal(self.bot,100,True);modal.reason._value='Проверил доказательства'
        await modal.on_submit(self.i);self.assertEqual((await self.row())['status'],'pending')
        modal.checklist._value='подтверждаю'
        with patch('bot.progression.award_main',new=AsyncMock()) as award, patch('bot.profiles.refresh_member',new=AsyncMock()):
            await asyncio.gather(modal.on_submit(self.i),modal.on_submit(self.i))
            award.assert_awaited_once()
        self.assertEqual((await self.row())['status'],'approved');self.assertEqual(self.i.channel.send.await_count,1)
        await self.db.close();await self.db.connect();self.assertEqual((await self.row())['status'],'approved')
    async def test_cannot_approve_self_or_after_role_revoked(self):
        modal=DecisionModal(self.bot,100,True);modal.checklist._value='подтверждаю'
        self.i.user.id=10;await modal.on_submit(self.i)
        self.assertEqual((await self.row())['status'],'pending')
        self.i.user.id=20;self.bot.can_promote.return_value=False;await modal.on_submit(self.i)
        self.assertEqual((await self.row())['status'],'pending');self.i.channel.send.assert_not_awaited()
    async def test_contract_requires_authors_image(self):
        await self.db.conn.execute("UPDATE progress_requests SET kind='contract'");await self.db.conn.commit()
        async def history(**kwargs):
            yield SimpleNamespace(author=SimpleNamespace(id=99),attachments=[SimpleNamespace(content_type='image/png')])
        self.i.channel.history=history
        await DecisionModal(self.bot,100,True).on_submit(self.i)
        self.assertEqual((await self.row())['status'],'pending')
    def test_conflicting_overwrites_cannot_silently_expand_access(self):
        with self.assertRaises(ValueError):merge_overwrite(discord.PermissionOverwrite(view_channel=True),discord.PermissionOverwrite(view_channel=False))
        merged=merge_overwrite(discord.PermissionOverwrite(attach_files=True),discord.PermissionOverwrite(view_channel=True))
        self.assertTrue(merged.attach_files);self.assertTrue(merged.view_channel)
    async def test_failed_member_transfer_keeps_legacy_role(self):
        old=MagicMock(spec=discord.Role);old.id=1;old.name='Colombo • Recruiter';old.managed=False;old.__ge__.return_value=False;old.permissions=discord.Permissions.none()
        new=MagicMock(spec=discord.Role);new.id=2;new.name='Recruit-';new.__ge__.return_value=False;new.permissions=discord.Permissions.none()
        member=SimpleNamespace(add_roles=AsyncMock(side_effect=discord.DiscordException('denied')));old.members=[member];old.delete=AsyncMock()
        guild=SimpleNamespace(chunked=True,roles=[old,new],channels=[],me=SimpleNamespace(top_role=object()))
        warnings=await migrate_legacy(guild,{'recruiter_role_id':new})
        self.assertTrue(warnings);old.delete.assert_not_awaited()
