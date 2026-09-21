"""Durable thread closure queue stored in the existing Discord-backed audit log."""
import asyncio
import time
import discord


async def schedule_archive(bot, channel, delay=5):
    if not isinstance(channel, discord.Thread):
        return None
    await bot.db.queue_thread_archive(channel.guild.id, channel.id, time.time() + delay)
    if not hasattr(bot, '_archive_tasks'):
        bot._archive_tasks = set()
    async def later():
        await asyncio.sleep(delay)
        await process_archives(bot, channel.guild)
    task = asyncio.create_task(later())
    bot._archive_tasks.add(task)
    task.add_done_callback(bot._archive_tasks.discard)
    return task


async def process_archives(bot, guild):
    async with bot.operation_locks[('archive_queue', guild.id)]:
        for row in await bot.db.pending_thread_archives(guild.id, time.time()):
            try:
                channel = await guild.fetch_channel(row['target_id'])
                if not isinstance(channel, discord.Thread) or channel.guild.id != guild.id:
                    print(f'Archive queue invalid thread | guild={guild.id} | thread={row["target_id"]}')
                    continue
                if not channel.archived or not channel.locked:
                    await channel.edit(archived=True, locked=True)
            except discord.NotFound:
                pass  # A deleted thread needs no further work.
            except discord.DiscordException as exc:
                print(f'Archive retry pending | guild={guild.id} | thread={row["target_id"]} | error={type(exc).__name__}')
                continue
            await bot.db.finish_thread_archive(guild.id, row['target_id'])
