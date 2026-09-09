import asyncio
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
import discord
from bot.database import Database
from bot.recruiting import interview_room

class Recruiting(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(self.tmp.name+'/test.db')
        await self.db.connect()
        self.now = datetime.now(timezone.utc)
    async def asyncTearDown(self):
        await self.db.close()
        self.tmp.cleanup()
    async def application(self, uid):
        now=self.now.isoformat()
        return await self.db.create_application(guild_id=1,applicant_id=uid,applicant_tag='test',real_name_age='test',
            majestic_experience='test',shooting_skill='test',level_online_tz='test',family_experience='test',
            created_at=now,updated_at=now,thread_id=uid+100)

    async def test_only_one_recruiter_can_claim(self):
        aid=await self.application(1)
        results=await asyncio.gather(*(self.db.claim_application(aid,r,self.now.isoformat()) for r in [10,20,30]))
        self.assertEqual(sum(results),1)
        app=await self.db.get_application_by_thread(1,101)
        self.assertIn(app['assigned_to'],[10,20,30])
        await self.db.release_application(aid,self.now.isoformat())
        self.assertTrue(await self.db.claim_application(aid,40,self.now.isoformat()))
        await self.db.update_application(aid,status='accepted')
        self.assertFalse(await self.db.claim_application(aid,50,self.now.isoformat()))

    async def test_three_rooms_have_unique_reservations_and_fourth_waits(self):
        aids=[await self.application(i) for i in range(4)]
        for aid in aids: await self.db.claim_application(aid,10,self.now.isoformat())
        until=(self.now+timedelta(minutes=15)).isoformat()
        rooms=await asyncio.gather(*(self.db.reserve_interview(aid,1,[100,200,300],self.now.isoformat(),until) for aid in aids))
        self.assertEqual(set(rooms),{100,200,300,None})
        await self.db.release_application(aids[0],self.now.isoformat())
        self.assertEqual(await self.db.reserve_interview(aids[3],1,[100,200,300],self.now.isoformat(),until),rooms[0])

    async def test_expired_booking_becomes_available(self):
        a,b=await self.application(1),await self.application(2)
        for aid in [a,b]: await self.db.claim_application(aid,10,self.now.isoformat())
        before=(self.now-timedelta(minutes=20)).isoformat()
        expired=(self.now-timedelta(minutes=5)).isoformat()
        self.assertEqual(await self.db.reserve_interview(a,1,[100],before,expired),100)
        self.assertEqual(await self.db.reserve_interview(b,1,[100],self.now.isoformat(),(self.now+timedelta(minutes=15)).isoformat()),100)

    async def test_allocator_skips_occupied_and_inaccessible_channels(self):
        aid=await self.application(1)
        await self.db.claim_application(aid,10,self.now.isoformat())
        app=await self.db.get_application_by_thread(1,101)
        rooms={}
        for rid in [100,200,300]:
            room=MagicMock(spec=discord.VoiceChannel);room.id=rid;room.members=[]
            room.permissions_for.return_value=SimpleNamespace(view_channel=True,connect=True)
            rooms[rid]=room
        rooms[100].members=[SimpleNamespace(id=99)]
        rooms[200].permissions_for.return_value=SimpleNamespace(view_channel=False,connect=False)
        guild=SimpleNamespace(id=1,get_channel=rooms.get,get_member=lambda uid:SimpleNamespace(id=uid))
        cfg=dict(interview_voice_channel_id=100,interview_voice_2_id=200,interview_voice_3_id=300)
        selected=await interview_room(SimpleNamespace(db=self.db),guild,cfg,app)
        self.assertEqual(selected.id,300)

    async def test_assignment_survives_reconnect(self):
        aid=await self.application(1)
        await self.db.claim_application(aid,10,self.now.isoformat())
        await self.db.close();await self.db.connect()
        self.assertEqual((await self.db.get_application_by_thread(1,101))['assigned_to'],10)
