import asyncio
import inspect
import tempfile
import unittest
from collections import defaultdict
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import discord
from bot.database import Database
from bot.interactions import private_thread
from bot.provisioning import provision, ROLE_SPECS
from bot.ui import application_panel_embed, vacation_panel_embed, case_panel_embed

class Workflows(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(self.tmp.name + '/bot.db')
        await self.db.connect()
    async def asyncTearDown(self):
        await self.db.close()
        self.tmp.cleanup()

    async def test_migration_preserves_existing_data(self):
        await self.db.create_case(10, 20, 30, '2026-09-08T00:00:00+00:00')
        await self.db.set_config(10, recruiter_role_id=77)
        await self.db.close()
        fresh = Database(self.tmp.name + '/bot.db')
        await fresh.connect()
        self.assertEqual((await fresh.get_config(10))['recruiter_role_id'], 77)
        self.assertEqual((await fresh.get_case_by_member(10,20))['channel_id'],30)
        await fresh.set_config(10, application_panel_message_id=88)
        await fresh.close()

    async def test_private_thread_correct_api_and_members(self):
        parent = MagicMock(spec=discord.TextChannel)
        parent.guild.chunked = True
        parent.permissions_for.return_value = discord.Permissions.all()
        member = SimpleNamespace(id=1)
        reviewer = SimpleNamespace(id=2, bot=False)
        thread = MagicMock(spec=discord.Thread)
        thread.add_user = AsyncMock()
        # The real signature rejects unsupported keyword arguments.
        async def create(**kwargs):
            inspect.signature(discord.TextChannel.create_thread).bind(parent, **kwargs)
            return thread
        parent.create_thread = AsyncMock(side_effect=create)
        result = await private_thread(parent, member, [SimpleNamespace(members=[reviewer])], 'заявка-1')
        self.assertIs(result,thread)
        self.assertEqual(parent.create_thread.call_args.kwargs['type'],discord.ChannelType.private_thread)
        self.assertFalse(parent.create_thread.call_args.kwargs['invitable'])
        self.assertNotIn('message',parent.create_thread.call_args.kwargs)
        self.assertEqual(thread.add_user.await_count,2)
        parent.send.assert_not_called()

    async def test_private_thread_denies_inaccessible_parent(self):
        parent = MagicMock(spec=discord.TextChannel)
        member = SimpleNamespace(id=1)
        parent.permissions_for.side_effect = lambda m: discord.Permissions.none() if m is member else discord.Permissions.all()
        with self.assertRaises(ValueError):
            await private_thread(parent,member,[],'отдых-1')
        parent.create_thread.assert_not_called()

    async def test_setup_twice_has_no_duplicate_channels_or_panels(self):
        guild = MagicMock(spec=discord.Guild)
        guild.id=1
        guild.roles=[]; guild.channels=[]; guild.categories=[]; guild.members=[]; guild.chunked=True
        guild.default_role=MagicMock(spec=discord.Role)
        guild.me=MagicMock(spec=discord.Member)
        guild.me.guild_permissions=discord.Permissions.all()
        channels={}; roles={}; messages={}; sequence=iter(range(100,1000))
        guild.get_channel.side_effect=channels.get
        guild.get_role.side_effect=roles.get
        async def create_role(**kwargs):
            role=MagicMock(spec=discord.Role)
            role.id=next(sequence); role.name=kwargs['name']; role.mention=f'<@&{role.id}>'
            role.is_default.return_value=False; role.managed=False; role.__ge__.return_value=False
            role.__lt__.return_value=True; role.position=role.id
            role.edit=AsyncMock(return_value=role)
            guild.roles.append(role)
            roles[role.id]=role
            return role
        guild.create_role=AsyncMock(side_effect=create_role)
        async def create_channel(name, **kwargs):
            spec=discord.TextChannel
            if name.startswith('COLOMBO'): spec=discord.CategoryChannel
            if name.startswith('Обзвон'): spec=discord.VoiceChannel
            ch=MagicMock(spec=spec); ch.id=next(sequence); ch.name=name; ch.mention=f'<#{ch.id}>'
            ch.topic=kwargs.get('topic'); ch.overwrites=kwargs.get('overwrites')
            ch.edit=AsyncMock()
            async def send(**kw):
                if kw.get('file'): kw['file'].close()
                msg=MagicMock(spec=discord.Message); msg.id=next(sequence); msg.author.id=999
                async def edit(**kwargs):
                    for file in kwargs.get('attachments', []): file.close()
                msg.edit=AsyncMock(side_effect=edit); messages[msg.id]=msg; return msg
            ch.send=AsyncMock(side_effect=send)
            ch.fetch_message=AsyncMock(side_effect=lambda mid:messages[mid])
            if spec is discord.CategoryChannel:
                ch.text_channels=[]; guild.categories.append(ch)
            channels[ch.id]=ch; guild.channels.append(ch); return ch
        guild.create_category=AsyncMock(side_effect=create_channel)
        guild.create_text_channel=AsyncMock(side_effect=create_channel)
        guild.create_voice_channel=AsyncMock(side_effect=create_channel)
        bot=SimpleNamespace(db=self.db,operation_locks=defaultdict(asyncio.Lock),
            user=SimpleNamespace(id=999,display_avatar=SimpleNamespace(url='https://example.com/avatar.png')),
            send_or_update_leaderboard=AsyncMock(),update_vacation_status=AsyncMock(),update_inactivity_report=AsyncMock())
        await provision(bot,guild,{})
        initial=len(channels)
        await provision(bot,guild,{})
        self.assertEqual(len(channels),initial)
        self.assertEqual(guild.create_role.await_count,8)
        self.assertEqual(len(messages),9)
        self.assertTrue(all(m.edit.await_count==1 for m in messages.values()))
        cfg=await self.db.get_config(1)
        staff=channels[cfg['applications_log_channel_id']]
        self.assertFalse(staff.overwrites[guild.default_role].view_channel)
        parent=channels[cfg['applications_parent_channel_id']]
        self.assertTrue(parent.overwrites[guild.default_role].view_channel)
        self.assertFalse(parent.overwrites[guild.default_role].send_messages)

    async def test_vacation_creates_thread_and_prevents_duplicate(self):
        from bot.views import VacationModal
        from datetime import datetime, timezone
        guild=MagicMock(spec=discord.Guild); guild.id=11
        parent=MagicMock(spec=discord.TextChannel); parent.id=22
        leader=MagicMock(spec=discord.Role); leader.id=33
        guild.get_channel.return_value=parent; guild.get_role.return_value=leader
        await self.db.set_config(11,vacation_review_channel_id=22,high_staff_role_id=33)
        i=MagicMock(spec=discord.Interaction)
        i.guild=guild; i.guild_id=11; i.user=MagicMock(spec=discord.Member); i.user.id=44
        i.response=SimpleNamespace(defer=AsyncMock(),send_message=AsyncMock())
        i.followup=SimpleNamespace(send=AsyncMock())
        bot=SimpleNamespace(db=self.db,operation_locks=defaultdict(asyncio.Lock),now_iso=lambda:datetime.now(timezone.utc).isoformat(), is_family_member=AsyncMock(return_value=True))
        modal=VacationModal(bot); modal.reason._value='Поездка'; modal.days._value='7'
        thread=MagicMock(spec=discord.Thread); thread.id=55
        thread.send=AsyncMock(return_value=SimpleNamespace(id=66))
        with patch('bot.views.private_thread',new=AsyncMock(return_value=thread)) as create:
            await modal.on_submit(i)
            row=await self.db.pending_vacation_for_member(11,44)
            self.assertEqual(row['thread_id'],55)
            self.assertEqual(row['review_message_id'],66)
            await modal.on_submit(i)
            self.assertEqual(create.await_count,1)

    async def test_panels_fit_discord_limits(self):
        for factory in (application_panel_embed,vacation_panel_embed,case_panel_embed):
            e=factory(); self.assertLessEqual(len(e),6000)
            for f in e.fields:
                self.assertLessEqual(len(f.name),256)
                self.assertLessEqual(len(f.value),1024)

if __name__=='__main__': unittest.main()
