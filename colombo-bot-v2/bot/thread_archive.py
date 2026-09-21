"""Durable thread closure queue stored in the existing Discord-backed audit log."""

import asyncio
import time
import logging
import discord

logger = logging.getLogger(__name__)


async def schedule_archive(bot, channel, delay: float = 5) -> asyncio.Task | None:
    if not isinstance(channel, discord.Thread):
        return None
    await bot.db.queue_thread_archive(channel.guild.id, channel.id, time.time() + delay)
    if not hasattr(bot, "_archive_tasks"):
        bot._archive_tasks = set()

    async def later():
        await asyncio.sleep(delay)
        try:
            await process_archives(bot, channel.guild)
        except Exception:
            # Очередь уже в базе: периодический обработчик повторит попытку.
            logger.exception("Archive task failed for guild %s", channel.guild.id)

    task = asyncio.create_task(later())
    bot._archive_tasks.add(task)
    task.add_done_callback(bot._archive_tasks.discard)
    return task


async def process_archives(bot, guild: discord.Guild) -> None:
    async with bot.operation_locks[("archive_queue", guild.id)]:
        for row in await bot.db.pending_thread_archives(guild.id, time.time()):
            try:
                channel = await guild.fetch_channel(row["target_id"])
                if (
                    not isinstance(channel, discord.Thread)
                    or channel.guild.id != guild.id
                ):
                    logger.warning(
                        "Archive target is not a guild thread: guild=%s thread=%s",
                        guild.id,
                        row["target_id"],
                    )
                    continue
                if not channel.archived or not channel.locked:
                    await channel.edit(archived=True, locked=True)
            except discord.NotFound:
                pass  # A deleted thread needs no further work.
            except discord.DiscordException as exc:
                logger.warning(
                    "Archive retry pending: guild=%s thread=%s error=%s",
                    guild.id,
                    row["target_id"],
                    type(exc).__name__,
                )
                continue
            await bot.db.finish_thread_archive(guild.id, row["target_id"])
