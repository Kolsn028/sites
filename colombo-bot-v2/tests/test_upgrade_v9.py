import asyncio,json,tempfile,unittest
from collections import defaultdict
from datetime import datetime,timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock,MagicMock
import discord
from bot.database import Database
from bot.leave import begin_leave,restore_leave,removable_roles
from bot.roster import join,move,limits,confirm,may_confirm
from bot.profiles import records,render,can_view

class Role:
    def __init__(self,rid,pos,managed=False):
        self.id=rid;self.position=pos;self.managed=managed;self.name=f'role-{rid}';self.permissions=discord.Permissions.none()
    def is_default(self):return self.id==0
    def __le__(self,o):return self.position<=o.position
    def __ge__(self,o):return self.position>=o.position
    def __gt__(self,o):return self.position>o.position

class Upgrade(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.db=Database(self.tmp.name+'/old.db');await self.db.connect()
        self.now=datetime.now(timezone.utc).isoformat()
        await self.db.set_config(1,leader_role_id=40,dep_leader_role_id=30,high_staff_role_id=20,
            recruiter_role_id=10,main_role_id=5,accepted_role_id=4,colombo_role_id=1,vacation_role_id=3)
        self.roles={n:Role(n,n) for n in (0,1,2,3,4,5,10,20,30,40,100)}
        self.held={self.roles[n] for n in (0,1,2,5,10,20,30,40)}
        self.guild=SimpleNamespace(id=1,owner_id=999,get_role=self.roles.get,me=SimpleNamespace(top_role=self.roles[100]))
        self.member=SimpleNamespace(id=7,guild=self.guild,roles=list(self.held),get_role=lambda rid:self.roles[rid] if self.roles.get(rid) in self.held else None)
        async def add(*roles,**kw):self.held.update(roles);self.member.roles=list(self.held)
        async def remove(*roles,**kw):self.held.difference_update(roles);self.member.roles=list(self.held)
        self.member.add_roles=AsyncMock(side_effect=add);self.member.remove_roles=AsyncMock(side_effect=remove)
        self.guild.fetch_member=AsyncMock(return_value=self.member)
        self.bot=SimpleNamespace(db=self.db,now_iso=lambda:self.now,operation_locks=defaultdict(asyncio.Lock))
        self.vid=await self.db.create_vacation(guild_id=1,member_id=7,member_tag='test',reason='test',start_date='2026-01-01',end_date='2026-01-02',status='pending',created_at=self.now,updated_at=self.now)
        await self.db.conn.execute("INSERT INTO family_events(guild_id,channel_id,message_id,creator_id,kind,title,starts_at,capacity,reserve_capacity) VALUES (1,22,33,20,'capt','Капт',1000000000,1,1)")
        await self.db.conn.commit()
    async def asyncTearDown(self):await self.db.close();self.tmp.cleanup()
    async def test_leave_and_return_exact_roles_and_no_auto_expiry(self):
        original={r.id for r in self.held}
        await begin_leave(self.bot,self.guild,await self.db.get_vacation(self.vid))
        self.assertEqual({r.id for r in self.held},{0,3,4,20,30,40})
        snapshot=(await self.db.get_vacation(self.vid))['role_snapshot']
        self.assertEqual({r['id'] for r in json.loads(snapshot)},{1,2,5,10})
        from bot.core import ColomboBot
        self.bot.update_vacation_status=AsyncMock()
        await ColomboBot.expire_vacations(self.bot,self.guild)
        self.assertEqual((await self.db.get_vacation(self.vid))['status'],'approved')
        await self.db.close();await self.db.connect()
        await restore_leave(self.bot,self.guild,await self.db.get_vacation(self.vid))
        self.assertEqual({r.id for r in self.held},original)
        self.assertEqual((await self.db.get_vacation(self.vid))['status'],'returned')
    async def test_failed_removal_snapshot_survives_retry(self):
        saved=self.member.remove_roles.side_effect
        self.member.remove_roles.side_effect=discord.DiscordException('fail')
        with self.assertRaises(discord.DiscordException):await begin_leave(self.bot,self.guild,await self.db.get_vacation(self.vid))
        vac=await self.db.get_vacation(self.vid);snap=vac['role_snapshot']
        self.assertEqual(vac['status'],'applying');self.assertIsNotNone(snap)
        self.member.remove_roles.side_effect=saved
        await begin_leave(self.bot,self.guild,vac)
        self.assertEqual((await self.db.get_vacation(self.vid))['role_snapshot'],snap)
    async def test_changed_or_deleted_role_blocks_restore_before_grant(self):
        await begin_leave(self.bot,self.guild,await self.db.get_vacation(self.vid))
        self.roles[5].permissions=discord.Permissions(administrator=True)
        self.member.add_roles.reset_mock()
        with self.assertRaises(ValueError):await restore_leave(self.bot,self.guild,await self.db.get_vacation(self.vid))
        self.member.add_roles.assert_not_awaited()
        self.assertEqual((await self.db.get_vacation(self.vid))['status'],'approved')
    async def test_existing_novizio_is_kept_on_return(self):
        self.held.add(self.roles[4]);self.member.roles=list(self.held)
        await begin_leave(self.bot,self.guild,await self.db.get_vacation(self.vid))
        await restore_leave(self.bot,self.guild,await self.db.get_vacation(self.vid))
        self.assertIn(self.roles[4],self.held)
    async def test_reserve_limits_and_moves_race(self):
        self.assertEqual(await join(self.db,1,7),'Ты записан!')
        results=await asyncio.gather(join(self.db,1,8,seat='reserve'),join(self.db,1,9,seat='reserve'))
        self.assertEqual(results.count('Ты записан в резерв!'),1)
        with self.assertRaises(ValueError):await move(self.db,1,8,'main',20)
        await limits(self.db,1,2,1,20);await move(self.db,1,8,'main',20)
        row=await self.db._one('SELECT * FROM event_signups WHERE member_id=8');self.assertEqual(row['seat'],'main')
        with self.assertRaises(ValueError):await limits(self.db,1,1,1,20)
        self.assertEqual((await self.db._one('SELECT capacity FROM family_events'))['capacity'],2)
    async def test_attendance_authority_not_any_assistant(self):
        cfg=await self.db.get_config(1);event={'creator_id':70}
        def m(uid,roles):return SimpleNamespace(id=uid,guild=self.guild,get_role=lambda rid:rid if rid in roles else None)
        self.assertTrue(may_confirm(m(70,[20]),cfg,event))
        self.assertFalse(may_confirm(m(71,[20]),cfg,event))
        self.assertFalse(may_confirm(m(70,[10]),cfg,event))
        self.assertTrue(may_confirm(m(71,[30]),cfg,event))
        self.assertTrue(may_confirm(m(71,[40]),cfg,event))
    async def test_attendance_and_reports_never_double_visit(self):
        await join(self.db,1,7);await confirm(self.db,1,7,20)
        aid=await self.db.create_activity(1,7,22,88,[],self.now)
        await self.db.update_activity(aid,status='approved',category='capt',event_id=1)
        await self.db.create_case(1,7,22,self.now)
        rows=await records(self.db,1,7)
        self.assertEqual(sum(r['kind']=='visit' and r['status']=='approved' for r in rows),1)
        self.assertEqual(sum(r['kind']=='report' for r in rows),1)
        self.assertIn('организатора',await join(self.db,1,7,leave=True))
        await confirm(self.db,1,7,20)
        self.assertEqual(sum(r['kind']=='visit' and r['status']=='approved' for r in await records(self.db,1,7)),0)
        self.assertEqual(len(await self.db._all('SELECT * FROM audit_actions')),2)
    async def test_private_profile_and_embed_limits(self):
        m=MagicMock(spec=discord.Member);m.id=7;m.display_name='Colombo';m.roles=[];m.display_avatar.url='https://example.com/a.png'
        self.assertTrue(await can_view(self.bot,self.guild,m,7))
        m.id=8;m.get_role.return_value=None;self.assertFalse(await can_view(self.bot,self.guild,m,7))
        m.id=7
        e,page,pages=await render(self.bot,self.guild,m)
        self.assertLessEqual(len(e),6000);self.assertTrue(all(len(f.value)<=1024 for f in e.fields))
    async def test_schema_upgrade_preserves_old_attendance_on_reconnect(self):
        await join(self.db,1,7);await confirm(self.db,1,7,20)
        await self.db.conn.execute('ALTER TABLE event_signups DROP COLUMN confirmed_by')
        await self.db.conn.execute('ALTER TABLE event_signups DROP COLUMN confirmed_at')
        await self.db.conn.execute('ALTER TABLE event_signups DROP COLUMN seat')
        await self.db.conn.execute('ALTER TABLE family_events DROP COLUMN reserve_capacity')
        await self.db.conn.commit();await self.db.close();await self.db.connect()
        r=await self.db._one('SELECT * FROM event_signups')
        self.assertEqual(r['attended'],1);self.assertEqual(r['seat'],'main');self.assertIsNone(r['confirmed_by'])
        await self.db.close();await self.db.connect()
        self.assertEqual(len(await self.db._all('SELECT * FROM event_signups')),1)
