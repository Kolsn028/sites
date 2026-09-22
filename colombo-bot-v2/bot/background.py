"""Scheduled work; the bot owns startup and shutdown of these loops."""
from discord.ext import tasks


class BackgroundTasks:
    @tasks.loop(hours=1)
    async def housekeeping(self):
        for g in self.guilds:
            try:
                await self.expire_vacations(g)
                await self.update_inactivity_report(g)
            except Exception as e:
                print(f"housekeeping[{g.id}]", e)

    @housekeeping.before_loop
    async def before_housekeeping(self):
        await self.wait_until_ready()

    @tasks.loop(minutes=5)
    async def application_reminders(self):
        from .enhancements import remind_applications

        for guild in self.guilds:
            try:
                await remind_applications(self, guild)
            except Exception as exc:
                print(f"Application reminders failed | guild={guild.id}: {exc}")

    @application_reminders.before_loop
    async def before_application_reminders(self):
        await self.wait_until_ready()

    @tasks.loop(minutes=1)
    async def archive_worker(self):
        from .thread_archive import process_archives

        for guild in self.guilds:
            try:
                await process_archives(self, guild)
            except Exception as exc:
                print(
                    f"Archive queue error | guild={guild.id}: {type(exc).__name__}: {exc}"
                )

    @archive_worker.before_loop
    async def before_archive_worker(self):
        await self.wait_until_ready()
