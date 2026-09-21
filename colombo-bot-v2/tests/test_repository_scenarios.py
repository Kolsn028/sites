"""Named data operations with real SQLite, including server boundaries."""
import ast
import aiosqlite
import tempfile
import unittest
from pathlib import Path
from bot.database import Database
from bot import roster
from bot.profiles import records


class RepositoryScenarios(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(self.tmp.name + '/db')
        await self.db.connect()

    async def asyncTearDown(self):
        await self.db.close()
        self.tmp.cleanup()

    async def test_event_report_attendance_and_profile(self):
        eid = await self.db.create_event(1,20,30,'capt','Капт',1000000000,2,'details',1)
        await self.db.set_event_message(eid,40)
        self.assertEqual((await self.db.event_by_message(1,40))['id'],eid)
        self.assertIsNone(await self.db.event_by_message(2,40))
        self.assertEqual((await self.db.event_template(1,'capt'))['id'],eid)
        await roster.join(self.db,eid,10)
        sid = await self.db.create_activity(guild_id=1,member_id=10,case_channel_id=50,
            source_message_id=60,attachment_urls=[],now_iso='2026-09-20')
        await self.db.link_report_event(1,sid,eid,30)
        self.assertEqual((await self.db.get_activity(sid))['event_id'],eid)
        self.assertFalse((await self.db.event_participants(eid))[0]['attended'])
        await roster.confirm(self.db,eid,10,30)
        await self.db.finish_event(eid)
        visits=[r for r in await records(self.db,1,10) if r['kind']=='visit']
        self.assertEqual(len(visits),1)
        self.assertEqual(visits[0]['status'],'approved')
        self.assertEqual(await records(self.db,2,10),[])
        self.assertEqual((await self.db.event_by_id(eid))['status'],'finished')
        with self.assertRaises(ValueError): await self.db.link_report_event(2,sid,eid,30)
        self.assertEqual(len(await self.db._all('SELECT * FROM audit_actions')),2)

    async def test_cleanup_and_failed_write_rollback(self):
        eid=await self.db.create_event(1,20,30,'capt','Капт',1,2,'',1)
        await self.db.delete_event(eid)
        self.assertIsNone(await self.db.event_by_id(eid))
        with self.assertRaises(aiosqlite.IntegrityError):
            await self.db.create_event(1,20,30,'capt','bad',1,0,'',1)
        self.assertFalse(self.db.conn.in_transaction)
        good=await self.db.create_event(1,20,30,'capt','good',1,2,'',1)
        self.assertEqual((await self.db.event_by_id(good))['title'],'good')

    async def test_tier_retry_and_queue_filters(self):
        rid=await self.db.create_progress(1,10,'tier_2',20,'[]','2026-09-20')
        self.assertIsNotNone(await self.db.find_open_tier(1,10))
        self.assertIsNone(await self.db.find_open_tier(2,10))
        self.assertIsNone(await self.db.progress_by_thread(2,20))
        await self.db.set_progress_decision(rid,'applying',30,'checked')
        self.assertIsNotNone(await self.db.find_open_tier(1,10))
        await self.db.set_progress_decision(rid,'approved',30,'checked')
        self.assertIsNone(await self.db.find_open_tier(1,10))
        rows,count,_,_=await self.db.request_rows(1,member_id=10,kind='tier_2')
        self.assertEqual(count,1)
        self.assertEqual(rows[0]['status'],'approved')
        self.assertEqual((await self.db.request_rows(1,member_id=11))[1],0)
        self.assertEqual((await self.db.request_rows(2,member_id=10))[1],0)
        await self.db.delete_progress_thread(20)
        self.assertIsNone(await self.db.progress_by_id(rid))

    async def test_contract_failure(self):
        rid=await self.db.create_progress(1,10,'contract',20,'help','2026-09-20')
        self.assertEqual((await self.db.find_open_progress(1,10,'contract'))['id'],rid)
        await self.db.fail_progress(rid)
        self.assertIsNone(await self.db.find_open_progress(1,10,'contract'))
        self.assertEqual((await self.db.member_contracts(1,10))[0]['status'],'failed')

    def test_ui_does_not_execute_sql(self):
        root=Path(__file__).resolve().parents[1]/'bot'
        files=[*root.joinpath('forms').glob('*.py')]
        files += [root/name for name in ('commands.py','events.py','progression.py',
                                        'tiers.py','leave.py','profiles.py','dashboard.py')]
        for path in files:
            for node in ast.walk(ast.parse(path.read_text())):
                if isinstance(node,ast.Call) and isinstance(node.func,ast.Attribute):
                    with self.subTest(file=path.name,line=node.lineno):
                        self.assertNotIn(node.func.attr,{'_one','_all','execute','executemany','executescript'})
