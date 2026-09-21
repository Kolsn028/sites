import asyncio
import tempfile
import unittest
from collections import defaultdict
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, MagicMock
import discord
from bot.database import Database
from bot.thread_archive import process_archives
from bot.discord_backup import snapshot, encode, decode


class DurableArchives(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.db=Database(self.tmp.name+'/db');await self.db.connect()
        await self.db.set_config(100, management_category_id=2)
        self.thread=MagicMock(spec=discord.Thread)
        self.thread.guild=NS(id=100);self.thread.archived=False;self.thread.locked=False
        self.guild=NS(id=100,fetch_channel=AsyncMock(return_value=self.thread))
        self.bot=NS(db=self.db,operation_locks=defaultdict(asyncio.Lock))
    async def asyncTearDown(self):
        await self.db.close();self.tmp.cleanup()
    async def test_reopen_database_and_backup_keep_pending_jobs(self):
        await self.db.queue_thread_archive(100,30,0)
        await self.db.queue_thread_archive(100,30,0)
        blob,digest=encode(await snapshot(self.db,100))
        payload=decode(blob,digest,100)
        self.assertTrue(any(x['action']=='thread_archive:pending' for x in payload['tables']['audit_actions']))
        await self.db.close();await self.db.connect()
        await process_archives(self.bot,self.guild)
        self.thread.edit.assert_awaited_once_with(archived=True,locked=True)
        await process_archives(self.bot,self.guild)
        self.thread.edit.assert_awaited_once()
    async def test_discord_failure_keeps_job_for_retry(self):
        await self.db.queue_thread_archive(100,30,0)
        self.thread.edit.side_effect=discord.DiscordException('temporary failure')
        await process_archives(self.bot,self.guild)
        self.assertEqual(len(await self.db.pending_thread_archives(100,1)),1)
        self.thread.edit.side_effect=None
        await process_archives(self.bot,self.guild)
        self.assertEqual(await self.db.pending_thread_archives(100,1),[])
    async def test_not_due_and_other_guild_are_ignored(self):
        await self.db.queue_thread_archive(101,30,0)
        await self.db.queue_thread_archive(100,31,99999999999)
        await process_archives(self.bot,self.guild)
        self.guild.fetch_channel.assert_not_awaited()

    async def test_failed_enqueue_rolls_back_before_next_write(self):
        from unittest.mock import patch
        with patch.object(self.db.conn, 'commit', AsyncMock(side_effect=RuntimeError('commit failed'))):
            with self.assertRaises(RuntimeError):
                await self.db.queue_thread_archive(100,30,0)
        self.assertEqual(await self.db.pending_thread_archives(100,1),[])
        await self.db.queue_thread_archive(100,30,0)
        self.assertEqual(len(await self.db.pending_thread_archives(100,1)),1)
