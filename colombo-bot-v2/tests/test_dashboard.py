import tempfile
import unittest
from datetime import datetime,timezone,date
from types import SimpleNamespace
from unittest.mock import AsyncMock,MagicMock
import discord
from bot.database import Database
from bot.dashboard import request_rows,ManagementView
from bot.events import parse_time,CreateEventModal,DayView

class Comfort(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.db=Database(self.tmp.name+'/db');await self.db.connect()
    async def asyncTearDown(self):await self.db.close();self.tmp.cleanup()
    async def test_owner_and_guild_isolation_all_sources(self):
        for gid,uid in [(1,10),(1,20),(2,10)]:
            await self.db.create_application(guild_id=gid,applicant_id=uid,applicant_tag='x',real_name_age='x',majestic_experience='x',shooting_skill='x',level_online_tz='x',family_experience='x',created_at='2026-09-15',updated_at='2026-09-15',rejection_reason='test',status='rejected')
            await self.db.create_vacation(guild_id=gid,member_id=uid,member_tag='x',reason='private reason',start_date='2026-09-15',end_date='2026-09-22',created_at='2026-09-15',updated_at='2026-09-15')
            await self.db.conn.execute("INSERT INTO progress_requests(guild_id,member_id,kind,thread_id,details,created_at) VALUES (?,?,'contract',?,'x','2026-09-15')",(gid,uid,gid*100+uid))
            await self.db.conn.commit()
        rows,total,_,_=await request_rows(self.db,1,10)
        self.assertEqual(total,3);self.assertTrue(all(r['member_id']==10 for r in rows))
        self.assertIsNone(next(r['reason'] for r in rows if r['kind']=='vacation'))
        queue,total,_,_=await request_rows(self.db,1,pending=True)
        self.assertEqual(total,4);self.assertNotIn('rejected',{r['status'] for r in queue})
        rows,total,_,_=await request_rows(self.db,1,10,kind='contract',page=999)
        self.assertEqual(total,1);self.assertEqual(rows[0]['kind'],'contract')
    async def test_management_rechecks_role(self):
        await self.db.set_config(1,high_staff_role_id=3,leader_role_id=1,dep_leader_role_id=2)
        member=MagicMock(spec=discord.Member);member.id=10;member.guild=SimpleNamespace(owner_id=99)
        i=SimpleNamespace(user=member,guild_id=1,response=SimpleNamespace(send_message=AsyncMock()))
        view=ManagementView(SimpleNamespace(db=self.db))
        member.get_role.return_value=None;self.assertFalse(await view.interaction_check(i))
        member.get_role.side_effect=lambda rid: rid==3;self.assertTrue(await view.interaction_check(i))
    async def test_short_dates_and_template_dont_reuse_time_or_people(self):
        now=datetime(2026,9,15,18,0,tzinfo=timezone.utc)
        with self.assertRaises(ValueError):parse_time('20:00',date(2026,9,15),now)
        ts=parse_time('20:00',date(2026,9,16),now)
        self.assertEqual(datetime.fromtimestamp(ts,timezone.utc).hour,17)
        template={'capacity':20,'reserve_capacity':5,'details':'Место','starts_at':1,'signups':[10]}
        modal=CreateEventModal(None,'capt',date(2026,9,16),template)
        self.assertEqual(modal.limit_input.default,'20');self.assertEqual(modal.reserve_input.default,'5')
        self.assertFalse(modal.date_input.default)
        self.assertFalse(hasattr(modal,'signups'))
