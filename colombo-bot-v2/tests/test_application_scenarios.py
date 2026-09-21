"""Real SQLite + simulated Discord: full recruitment flow and failure recovery."""
import asyncio
import tempfile
import unittest
from collections import defaultdict
from datetime import datetime, timezone
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import aiosqlite

from bot.database import Database
from bot.forms import applications as forms_applications
from bot.forms.applications import ApplicationModal, RecruiterActionSelect, schedule_archive
from bot.services.applications import decide, ApplicationDecisionError
from bot.profiles import records


class ApplicationScenarios(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(self.tmp.name + '/bot.db')
        await self.db.connect()
        self.cfg = dict(guest_role_id=1, colombo_role_id=2, accepted_role_id=3,
                        recruiter_role_id=4, high_staff_role_id=5,
                        dep_leader_role_id=6, leader_role_id=7,
                        applications_parent_channel_id=20, applications_log_channel_id=21)
        await self.db.set_config(100, **self.cfg)
        self.roles = {}
        for rid in range(1, 8):
            role = MagicMock(spec=discord.Role)
            role.id = rid
            role.managed = False
            role.is_default.return_value = False
            role.__ge__.return_value = False
            role.members = []
            self.roles[rid] = role
        self.guild = MagicMock(spec=discord.Guild)
        self.guild.id = 100
        self.guild.owner_id = 999
        self.guild.chunked = True
        self.guild.me = NS(top_role=object())
        self.guild.get_role.side_effect = self.roles.get
        self.held = {1}
        self.applicant = self.person(10, self.held)
        self.recruit_roles = {4}
        self.recruiter = self.person(11, self.recruit_roles)
        self.guild.get_member.side_effect = {10: self.applicant, 11: self.recruiter}.get
        self.roles[4].members = [self.recruiter]
        async def add(*roles, **kwargs):
            self.held.update(r.id for r in roles)
        async def remove(*roles, **kwargs):
            self.held.difference_update(r.id for r in roles)
        self.add = add
        self.remove = remove
        self.applicant.add_roles = AsyncMock(side_effect=add)
        self.applicant.remove_roles = AsyncMock(side_effect=remove)
        self.bot = NS(db=self.db, operation_locks=defaultdict(asyncio.Lock),
                      now_iso=lambda: datetime.now(timezone.utc).isoformat(),
                      is_recruiter=AsyncMock(return_value=True),
                      can_manage=AsyncMock(return_value=False),
                      send_or_update_leaderboard=AsyncMock())

    async def asyncTearDown(self):
        await self.db.close()
        self.tmp.cleanup()

    def person(self, uid, roles):
        member = MagicMock(spec=discord.Member)
        member.id = uid
        member.guild = self.guild
        member.bot = False
        member.display_name = f'Player {uid}'
        member.mention = f'<@{uid}>'
        member.display_avatar = NS(url='https://example.com/avatar.png')
        member.guild_permissions = NS(administrator=False)
        member.get_role.side_effect = lambda rid: self.roles.get(rid) if rid in roles else None
        return member

    async def submit(self):
        parent = MagicMock(spec=discord.TextChannel)
        log = MagicMock(spec=discord.TextChannel)
        log.send = AsyncMock(return_value=NS(id=31))
        self.guild.get_channel.side_effect = {20: parent, 21: log}.get
        thread = MagicMock(spec=discord.Thread)
        thread.id = 30
        thread.send = AsyncMock(return_value=NS(id=32))
        i = NS(guild=self.guild, guild_id=100, user=self.applicant,
               response=NS(defer=AsyncMock(), send_message=AsyncMock()),
               followup=NS(send=AsyncMock()))
        modal = ApplicationModal(self.bot)
        for field in modal.children:
            field._value = 'Test answer'
        with patch('bot.forms.applications.private_thread', new=AsyncMock(return_value=thread)) as create:
            await modal.on_submit(i)
            await modal.on_submit(i)
            create.assert_awaited_once()
        app = await self.db.get_application_by_thread(100, 30)
        self.assertEqual(app['status'], 'pending')
        thread.guild = self.guild
        self.thread = thread
        return app

    async def claimed(self):
        app = await self.submit()
        self.assertTrue(await self.db.claim_application(app['id'], 11, self.bot.now_iso()))
        return app

    async def test_submit_claim_accept_roles_statistics_and_history(self):
        app = await self.claimed()
        result = await decide(self.bot, self.guild, self.recruiter, 30, accepted=True)
        self.assertEqual(result['status'], 'accepted')
        self.assertEqual(self.held, {2, 3})
        stats = await self.db.leaderboard(100, 10)
        self.assertEqual((stats[0]['accepted_count'], stats[0]['rejected_count']), (1, 0))
        history = await records(self.db, 100, 10)
        self.assertEqual([r['key'] for r in history], [f"application:{app['id']}"])
        with self.assertRaises(ApplicationDecisionError):
            await decide(self.bot, self.guild, self.recruiter, 30, accepted=True)
        self.applicant.add_roles.assert_awaited_once()
        self.assertEqual((await self.db.leaderboard(100, 10))[0]['accepted_count'], 1)

    async def test_concurrent_approval_and_rejection_count_once(self):
        await self.claimed()
        results = await asyncio.gather(
            decide(self.bot, self.guild, self.recruiter, 30, accepted=True),
            decide(self.bot, self.guild, self.recruiter, 30, accepted=False, reason='Недостаточно опыта'),
            return_exceptions=True)
        self.assertEqual(sum(isinstance(x, dict) for x in results), 1)
        stats = (await self.db.leaderboard(100, 10))[0]
        self.assertEqual(stats['accepted_count'] + stats['rejected_count'], 1)

    async def test_rejection_records_reason_without_role_changes(self):
        await self.claimed()
        await decide(self.bot, self.guild, self.recruiter, 30, accepted=False, reason='Недостаточно опыта')
        self.assertEqual(self.held, {1})
        self.applicant.add_roles.assert_not_awaited()
        history = await records(self.db, 100, 10)
        self.assertIn('Недостаточно опыта', history[0]['detail'])
        self.assertEqual((await self.db.leaderboard(100, 10))[0]['rejected_count'], 1)

    async def test_unclaimed_wrong_recruiter_and_revoked_role_are_denied(self):
        app = await self.submit()
        with self.assertRaises(ApplicationDecisionError):
            await decide(self.bot, self.guild, self.recruiter, 30, accepted=True)
        await self.db.claim_application(app['id'], 12, self.bot.now_iso())
        with self.assertRaises(ApplicationDecisionError):
            await decide(self.bot, self.guild, self.recruiter, 30, accepted=True)
        await self.db.update_application(app['id'], assigned_to=11)
        self.recruit_roles.clear()
        with self.assertRaises(ApplicationDecisionError):
            await decide(self.bot, self.guild, self.recruiter, 30, accepted=True)
        self.applicant.add_roles.assert_not_awaited()
        self.assertEqual(await self.db.leaderboard(100, 10), [])

    async def test_role_add_failure_leaves_request_retryable(self):
        await self.claimed()
        self.applicant.add_roles.side_effect = discord.DiscordException('role write failed')
        with self.assertRaises(ApplicationDecisionError):
            await decide(self.bot, self.guild, self.recruiter, 30, accepted=True)
        self.assertEqual(self.held, {1})
        self.assertEqual((await self.db.get_application_by_thread(100, 30))['status'], 'pending')
        self.assertEqual(await self.db.leaderboard(100, 10), [])
        self.applicant.add_roles.side_effect = self.add
        await decide(self.bot, self.guild, self.recruiter, 30, accepted=True)
        self.assertEqual(self.held, {2, 3})

    async def test_guest_removal_failure_then_restart_and_retry(self):
        await self.claimed()
        self.applicant.remove_roles.side_effect = discord.DiscordException('cannot remove guest')
        with self.assertRaises(ApplicationDecisionError):
            await decide(self.bot, self.guild, self.recruiter, 30, accepted=True)
        self.assertEqual(self.held, {1, 2, 3})
        self.assertEqual(await self.db.leaderboard(100, 10), [])
        await self.db.close()
        await self.db.connect()
        self.applicant.remove_roles.side_effect = self.remove
        await decide(self.bot, self.guild, self.recruiter, 30, accepted=True)
        self.assertEqual(self.held, {2, 3})
        self.assertEqual((await self.db.leaderboard(100, 10))[0]['accepted_count'], 1)

    async def test_statistics_failure_rolls_back_decision(self):
        await self.claimed()
        await self.db.conn.execute("CREATE TRIGGER fail_stats BEFORE INSERT ON recruiter_stats BEGIN SELECT RAISE(ABORT, 'forced failure'); END")
        await self.db.conn.commit()
        with self.assertRaises(aiosqlite.IntegrityError):
            await decide(self.bot, self.guild, self.recruiter, 30, accepted=True)
        self.assertEqual((await self.db.get_application_by_thread(100, 30))['status'], 'pending')
        self.assertEqual(await self.db.leaderboard(100, 10), [])
        await self.db.conn.execute('DROP TRIGGER fail_stats')
        await self.db.conn.commit()
        await decide(self.bot, self.guild, self.recruiter, 30, accepted=True)
        self.assertEqual((await self.db.leaderboard(100, 10))[0]['accepted_count'], 1)

    async def test_notification_failure_does_not_repeat_roles_or_statistics(self):
        await self.claimed()
        self.thread.send.side_effect = discord.DiscordException('notification unavailable')
        i = NS(guild=self.guild, guild_id=100, channel=self.thread, channel_id=30,
               user=self.recruiter, response=NS(defer=AsyncMock(), send_message=AsyncMock()),
               followup=NS(send=AsyncMock()))
        action = RecruiterActionSelect(self.bot)
        action._values = ['accept']
        with self.assertRaises(discord.DiscordException):
            await action.callback(i)
        await action.callback(i)
        self.applicant.add_roles.assert_awaited_once()
        self.assertEqual((await self.db.leaderboard(100, 10))[0]['accepted_count'], 1)
        self.assertEqual((await self.db.get_application_by_thread(100, 30))['status'], 'accepted')


class ThreadArchiveIsNotUnderLock(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        # long enough that no awaited db call lets the archive task slip through
        delay = patch.object(forms_applications, 'ARCHIVE_DELAY_SECONDS', 3600)
        delay.start()
        self.addCleanup(delay.stop)
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(self.tmp.name + '/bot.db')
        await self.db.connect()
        self.guild = MagicMock(spec=discord.Guild)
        self.guild.id = 100
        self.thread = MagicMock(spec=discord.Thread)
        self.thread.id = 30
        self.thread.guild = self.guild
        self.recruiter = MagicMock(spec=discord.Member)
        self.recruiter.id = 11
        self.recruiter.guild = self.guild
        self.bot = NS(db=self.db, operation_locks=defaultdict(asyncio.Lock),
                      now_iso=lambda: datetime.now(timezone.utc).isoformat(),
                      is_recruiter=AsyncMock(return_value=True),
                      can_manage=AsyncMock(return_value=False),
                      ensure_personal_case=AsyncMock(return_value=None),
                      send_or_update_leaderboard=AsyncMock())
        await self.db.set_config(100, guest_role_id=1, colombo_role_id=2, accepted_role_id=3,
                                 recruiter_role_id=4, high_staff_role_id=5, dep_leader_role_id=6,
                                 leader_role_id=7, applications_parent_channel_id=20,
                                 applications_log_channel_id=21)
        now = self.bot.now_iso()
        self.app_id = await self.db.create_application(guild_id=100, applicant_id=10,
            applicant_tag='p', real_name_age='x', majestic_experience='x', shooting_skill='x',
            level_online_tz='x', family_experience='x', extra='', status='pending',
            created_at=now, updated_at=now)
        await self.db.update_application(self.app_id, thread_id=30)
        self.assertTrue(await self.db.claim_application(self.app_id, 11, now))
        roles = {rid: MagicMock(spec=discord.Role, id=rid, managed=False, members=[])
                 for rid in range(1, 8)}
        for role in roles.values():
            role.is_default.return_value = False
            role.__ge__ = MagicMock(return_value=False)
        self.guild.get_role.side_effect = roles.get
        self.applicant = MagicMock(spec=discord.Member)
        self.applicant.id = 10
        self.applicant.guild = self.guild
        self.applicant.bot = False
        self.applicant.display_avatar = NS(url='https://example.com/a.png')
        held = {1}
        self.applicant.get_role.side_effect = lambda rid: roles.get(rid) if rid in held else None
        async def add(*r, **kw): held.update(x.id for x in r)
        async def remove(*r, **kw): held.difference_update(x.id for x in r)
        self.applicant.add_roles = AsyncMock(side_effect=add)
        self.applicant.remove_roles = AsyncMock(side_effect=remove)
        self.guild.get_member.side_effect = {10: self.applicant, 11: self.recruiter}.get
        self.guild.me = NS(top_role=MagicMock())
        self.guild.owner_id = 999

    async def asyncTearDown(self):
        await self.drain()
        await self.db.close()
        self.tmp.cleanup()

    async def drain(self):
        for task in list(getattr(self.bot, '_archive_tasks', ())):
            task.cancel()
        await asyncio.gather(*getattr(self.bot, '_archive_tasks', ()), return_exceptions=True)

    async def accept(self):
        i = NS(guild=self.guild, guild_id=100, channel=self.thread, channel_id=30,
               user=self.recruiter, response=NS(defer=AsyncMock(), send_message=AsyncMock()),
               followup=NS(send=AsyncMock()))
        action = RecruiterActionSelect(self.bot)
        action._values = ['accept']
        await action.callback(i)
        return i

    async def test_decision_is_saved_and_lock_released_while_archive_pending(self):
        await self.accept()
        self.assertEqual((await self.db.get_application_by_thread(100, 30))['status'], 'accepted')
        self.assertFalse(self.bot.operation_locks[('recruiter_decision', 100, 30)].locked())
        self.assertEqual(len(self.bot._archive_tasks), 1)
        self.thread.edit.assert_not_awaited()

    async def test_next_action_in_the_thread_is_not_blocked(self):
        await self.accept()
        lock = self.bot.operation_locks[('recruiter_decision', 100, 30)]
        await asyncio.wait_for(lock.acquire(), timeout=1)
        lock.release()

