import asyncio
import unittest
from collections import defaultdict
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from datetime import datetime, timezone, timedelta
import discord
from bot.performance import edit_if_changed, coalesced_panel
from bot.interactions import serialized
from bot.tiers import sync_reviewers, GUILD_ID


class Performance(unittest.IsolatedAsyncioTestCase):
    async def test_timestamp_only_is_not_an_edit_but_content_and_buttons_are(self):
        original=discord.Embed(title='Same',timestamp=datetime.now(timezone.utc))
        updated=original.copy();updated.timestamp=original.timestamp+timedelta(seconds=20)
        message=SimpleNamespace(embeds=[original],components=[],edit=AsyncMock())
        await edit_if_changed(message,embed=updated)
        message.edit.assert_not_awaited()
        updated.description='Changed'
        await edit_if_changed(message,embed=updated)
        message.edit.assert_awaited_once()
        view=discord.ui.View();view.add_item(discord.ui.Button(label='New button',custom_id='new'))
        await edit_if_changed(message,embed=original,view=view)
        self.assertEqual(message.edit.await_count,2)

    async def test_refresh_burst_combines_and_change_during_write_is_not_lost(self):
        bot=SimpleNamespace(value=1);guild=SimpleNamespace(id=1)
        entered=asyncio.Event();release=asyncio.Event();rendered=[]
        @coalesced_panel
        async def render(bot,guild):
            rendered.append(bot.value)
            if len(rendered)==1:
                entered.set();await release.wait()
            return bot.value
        first=asyncio.create_task(render(bot,guild))
        second=asyncio.create_task(render(bot,guild))
        await entered.wait()
        bot.value=2
        third=asyncio.create_task(render(bot,guild));await asyncio.sleep(0)
        release.set()
        self.assertEqual(await asyncio.gather(first,second,third),[2,2,2])
        self.assertEqual(rendered,[1,2])
        self.assertFalse(bot._panel_tasks)

    async def test_busy_button_responds_without_waiting_or_running_operation(self):
        obj=SimpleNamespace(bot=SimpleNamespace(operation_locks=defaultdict(asyncio.Lock)))
        i=SimpleNamespace(user=SimpleNamespace(id=1),guild_id=2,channel_id=3,response=SimpleNamespace(send_message=AsyncMock()))
        operation=AsyncMock()
        @serialized('test')
        async def run(self,i):await operation()
        async with obj.bot.operation_locks[('test',2,3)]:
            await asyncio.wait_for(run(obj,i),timeout=0.1)
        operation.assert_not_awaited();i.response.send_message.assert_awaited_once()
        await run(obj,i);operation.assert_awaited_once()

    async def test_repair_double_click_shares_one_task(self):
        bot=SimpleNamespace();guild=SimpleNamespace(id=GUILD_ID);member=SimpleNamespace(id=5)
        entered=asyncio.Event();release=asyncio.Event()
        async def actual(*_):entered.set();await release.wait();return (4,0)
        with patch('bot.tier_system.reviewers._sync_reviewers',new=AsyncMock(side_effect=actual)) as repair:
            first=asyncio.create_task(sync_reviewers(bot,guild,member));await entered.wait()
            second=asyncio.create_task(sync_reviewers(bot,guild,member));await asyncio.sleep(0)
            release.set()
            self.assertEqual(await asyncio.gather(first,second),[(4,0),(4,0)])
            repair.assert_awaited_once()
            self.assertFalse(bot._tier_sync_tasks)
