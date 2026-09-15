import asyncio
import tempfile
import unittest
from collections import defaultdict
from datetime import datetime,timezone,timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock,MagicMock
import discord
from bot.database import Database
from bot.enhancements import decide_application,recruiter_board,find_case,create_case_channel,remind_applications
from bot.profiles import can_view,records
from bot.events import EventView,RosterManageView

class Improvements(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.db=Database(self.tmp.name+'/db')
        await self.db.connect()
    async def asyncTearDown(self):
        await self.db.close();self.tmp.cleanup()
    async def app(self,uid=2):
        t=(datetime.now(timezone.utc)-timedelta(hours=3)).isoformat()
        return await self.db.create_application(guild_id=1,applicant_id=uid,applicant_tag='x',real_name_age='x',majestic_experience='x',shooting_skill='x',level_online_tz='x',family_experience='x',created_at=t,updated_at=t,thread_id=33,assigned_to=3)
    async def test_decisions_atomic_and_periods_exclude_imported_totals(self):
        aid=await self.app();now=datetime.now(timezone.utc).isoformat()
        await self.db.bump_recruiter(1,3,accepted=20)
        r=await asyncio.gather(decide_application(self.db,aid,1,3,'rejected',now,'Причина'),decide_application(self.db,aid,1,3,'accepted',now))
        self.assertEqual(sum(r),1)
        board=await recruiter_board(self.db,1,7)
        self.assertIn('**0** принято',board.description)
        self.assertIn('**1** отказов',board.description)
        full=await recruiter_board(self.db,1,0);self.assertIn('**20** принято',full.description)
        data=await records(self.db,1,2,7);self.assertIn('Причина',data[0]['detail'])
        with self.assertRaises(ValueError): await decide_application(self.db,aid,1,3,'rejected',now,' ')
    async def test_profile_even_self_is_high_only(self):
        cfg={'leader_role_id':1,'dep_leader_role_id':2,'high_staff_role_id':3,'recruiter_role_id':4}
        await self.db.set_config(1,**cfg)
        guild=SimpleNamespace(id=1,owner_id=99)
        viewer=MagicMock(spec=discord.Member);viewer.id=10;viewer.guild=guild
        for role,expected in [(4,False),(3,True),(2,True),(1,True),(None,False)]:
            viewer.get_role.side_effect=lambda rid: rid==role
            self.assertEqual(bool(await can_view(SimpleNamespace(db=self.db),guild,viewer,10)),expected)
    async def test_case_recovers_existing_topic(self):
        ch=MagicMock(spec=discord.TextChannel);ch.id=42;ch.topic='Личное дело • owner=2'
        guild=SimpleNamespace(id=1,fetch_channels=AsyncMock(return_value=[ch]))
        member=SimpleNamespace(id=2,guild=guild)
        bot=SimpleNamespace(db=self.db,now_iso=lambda:'now')
        self.assertIs(await find_case(bot,member),ch)
        self.assertEqual((await self.db.get_case_by_member(1,2))['channel_id'],42)
    async def test_full_category_uses_overflow(self):
        base=MagicMock(spec=discord.CategoryChannel);base.id=10;base.name='Дела';base.overwrites={}
        full=[SimpleNamespace(category_id=10) for _ in range(50)]
        extra=MagicMock(spec=discord.CategoryChannel);extra.id=20;extra.name='Личные дела • 10 • 2'
        guild=SimpleNamespace(id=1,fetch_channels=AsyncMock(return_value=[base,extra,*full]),create_text_channel=AsyncMock(),create_category=AsyncMock())
        bot=SimpleNamespace(operation_locks=defaultdict(asyncio.Lock))
        await create_case_channel(bot,SimpleNamespace(id=2,guild=guild),base,{},'case')
        self.assertIs(guild.create_text_channel.call_args.kwargs['category'],extra)
        guild.create_category.assert_not_awaited()
    async def test_reminder_two_hours_and_no_senior_ping(self):
        aid=await self.app()
        await self.db.set_config(1,leader_role_id=10,dep_leader_role_id=11,high_staff_role_id=12,recruiter_role_id=13)
        guild=SimpleNamespace(id=1,owner_id=99)
        member=SimpleNamespace(id=3,bot=False,guild=guild,mention='<@3>',get_role=lambda rid: rid==13)
        thread=SimpleNamespace(guild=guild,archived=False,send=AsyncMock())
        guild.get_member=lambda _:member;guild.get_thread=lambda _:thread
        bot=SimpleNamespace(db=self.db,operation_locks=defaultdict(asyncio.Lock))
        await remind_applications(bot,guild);thread.send.assert_awaited_once()
        await remind_applications(bot,guild);thread.send.assert_awaited_once()
        await self.db.update_application(aid,last_reminded_at=None)
        member.get_role=lambda rid: rid in (12,13)
        await remind_applications(bot,guild);thread.send.assert_awaited_once()
    async def test_public_mp_only_four_buttons_legacy_still_registered(self):
        ids={c.custom_id for c in EventView(None).children}
        self.assertEqual(ids,{'colombo:event:join','colombo:event:reserve','colombo:event:leave','colombo:event:manage'})
        self.assertEqual(len(EventView(None,legacy=True).children),6)
        self.assertEqual(len(RosterManageView(None,1).children),5)
