import asyncio
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock,MagicMock
import discord
from bot.database import Database
from bot.events import signup,card,may_manage_events,CreateEventModal,EventView,EventPanelView,parse_time

class Events(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.db=Database(self.tmp.name+'/events.db');await self.db.connect()
        await self.db.conn.execute("INSERT INTO family_events(guild_id,channel_id,message_id,creator_id,kind,title,starts_at,capacity) VALUES (1,2,3,4,'capt','Капт',2000000000,2)")
        await self.db.conn.commit()
    async def asyncTearDown(self): await self.db.close();self.tmp.cleanup()
    async def test_concurrent_last_place_duplicate_and_leave(self):
        results=await asyncio.gather(*(signup(self.db,1,uid) for uid in (10,10,20,30)))
        self.assertEqual(results.count('Ты записан!'),2)
        self.assertIn('Ты уже записан.',results);self.assertIn('Все места заняты.',results)
        await signup(self.db,1,10,True);self.assertEqual(await signup(self.db,1,30),'Ты записан!')
        await self.db.close();await self.db.connect()
        self.assertEqual(len(await self.db._all('SELECT * FROM event_signups')),2)
    async def test_finished_event_immutable_for_signup(self):
        await signup(self.db,1,10)
        await self.db.conn.execute("UPDATE family_events SET status='finished'");await self.db.conn.commit()
        self.assertEqual(await signup(self.db,1,20),'Сбор завершён.')
        self.assertEqual(await signup(self.db,1,10,True),'Сбор завершён.')
        self.assertEqual(len(await self.db._all('SELECT * FROM event_signups')),1)
    async def test_creation_role_checked_again_at_modal_submit(self):
        cfg=dict(leader_role_id=1,dep_leader_role_id=2,high_staff_role_id=3,recruiter_role_id=4)
        for rid in (1,2,3,4,5):
            member=SimpleNamespace(id=10,guild=SimpleNamespace(owner_id=999),get_role=lambda r:r if r==rid else None)
            self.assertEqual(bool(may_manage_events(member,cfg)),rid in (1,2,3))
        i=MagicMock(spec=discord.Interaction);i.guild_id=1;i.user=MagicMock(spec=discord.Member)
        i.user.id=10;i.user.guild.owner_id=999;i.user.get_role.return_value=None
        i.response=SimpleNamespace(send_message=AsyncMock())
        bot=SimpleNamespace(db=SimpleNamespace(get_config=AsyncMock(return_value=cfg)))
        await CreateEventModal(bot,'capt').on_submit(i)
        i.response.send_message.assert_awaited_once()
    async def test_card_capacity_and_persistent_buttons(self):
        await self.db.conn.execute('UPDATE family_events SET capacity=100');await self.db.conn.commit()
        for uid in range(100):await signup(self.db,1,100000000000000000+uid)
        row=await self.db._one('SELECT * FROM family_events WHERE id=1')
        e=await card(self.db,row)
        self.assertLessEqual(len(e),6000)
        self.assertTrue(all(len(f.value)<=1024 for f in e.fields))
        self.assertTrue(EventView(None).is_persistent());self.assertTrue(EventPanelView(None).is_persistent())
    def test_date_validation(self):
        with self.assertRaises(ValueError):parse_time('01.01.2020 12:00')
        with self.assertRaises(ValueError):parse_time('31.02.2030 12:00')
