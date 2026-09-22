"""Integration seams that can break when Discord handlers move between modules."""
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
import discord
from bot.core import ColomboBot
from bot import tiers
from bot.tier_system.applications import TierPanelView
from bot.tier_system.review import TierReviewView


class ModuleBoundaries(unittest.IsolatedAsyncioTestCase):
    async def test_old_imports_keep_persistent_component_ids(self):
        self.assertIs(tiers.TierPanelView, TierPanelView)
        self.assertIs(tiers.TierReviewView, TierReviewView)
        bot=SimpleNamespace()
        panel=tiers.TierPanelView(bot)
        review=tiers.TierReviewView(bot)
        self.assertEqual({item.custom_id for item in panel.children},
                         {'colombo:tier:apply','colombo:tier:restore_access'})
        self.assertEqual({item.custom_id for item in review.children},
                         {'colombo:tier:approve','colombo:tier:reject'})
        self.assertTrue(panel.is_persistent())
        self.assertTrue(review.is_persistent())

    async def test_inherited_loops_are_bound_per_bot_and_call_moved_panels(self):
        bots=[ColomboBot(command_prefix='!', intents=discord.Intents.none(),
                        db=SimpleNamespace(close=AsyncMock())) for _ in range(2)]
        try:
            first,second=bots
            self.assertIsNot(first.housekeeping,second.housekeeping)
            first._connection._guilds={100:SimpleNamespace(id=100)}
            first.expire_vacations=AsyncMock()
            first.update_inactivity_report=AsyncMock()
            await first.housekeeping()
            first.expire_vacations.assert_awaited_once()
            first.update_inactivity_report.assert_awaited_once()
            with patch('bot.thread_archive.process_archives',new=AsyncMock()) as process:
                await first.archive_worker()
                process.assert_awaited_once_with(first,first.guilds[0])
            self.assertEqual(first.housekeeping.hours,1)
            self.assertEqual(first.application_reminders.minutes,5)
            self.assertEqual(first.archive_worker.minutes,1)
            self.assertTrue(callable(first.send_or_update_leaderboard))
            self.assertTrue(callable(first.update_vacation_status))
        finally:
            for bot in bots:
                await bot.close()
