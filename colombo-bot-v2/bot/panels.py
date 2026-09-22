"""Statistics panels; methods remain available on ColomboBot."""
import os
from datetime import date, datetime, timezone
import discord
from .performance import edit_if_changed, coalesced_panel
from .ui import base_embed


class PanelUpdates:
    @coalesced_panel
    async def send_or_update_leaderboard(self, guild):
        c = await self.db.get_config(guild.id)
        rows = await self.db.leaderboard(guild.id, 10)
        medals = ["🥇", "🥈", "🥉"]
        lines = []
        for i, r in enumerate(rows):
            lines.append(
                f"{medals[i] if i<3 else f'`#{i+1}`'} <@{r['recruiter_id']}> — **{r['accepted_count']}** принято"
                + (f" · {r['rejected_count']} отказов" if r["rejected_count"] else "")
            )
        e = base_embed(
            "🏆 Лидерборд рекрутеров",
            "\n".join(lines) if lines else "Пока нет данных.",
            0xE5B64B,
        )
        ch = guild.get_channel(c.get("leaderboard_channel_id") or 0)
        if not isinstance(ch, discord.TextChannel):
            return None
        mid = c.get("leaderboard_message_id")
        if mid:
            try:
                m = await ch.fetch_message(mid)
                await edit_if_changed(m, embed=e)
                return m
            except discord.NotFound:
                pass
        m = await ch.send(embed=e)
        await self.db.set_config(guild.id, leaderboard_message_id=m.id)
        return m

    @coalesced_panel
    async def update_vacation_status(self, guild):
        c = await self.db.get_config(guild.id)
        rows = await self.db.active_vacations(guild.id)
        today = date.today()
        lines = []
        for r in rows:
            end = date.fromisoformat(r["end_date"])
            lines.append(
                f"🌴 <@{r['member_id']}> — до **{end.strftime('%d.%m.%Y')}** · **{max((end-today).days,0)} дн.** · возврат по заявке"
            )
        e = base_embed(
            "🌴 Кто сейчас в отпуске",
            "\n".join(lines) if lines else "Сейчас активных отпусков нет.",
            0x3BAA72,
        )
        ch = guild.get_channel(c.get("vacation_status_channel_id") or 0)
        if not isinstance(ch, discord.TextChannel):
            return None
        mid = c.get("vacation_status_message_id")
        if mid:
            try:
                m = await ch.fetch_message(mid)
                await edit_if_changed(m, embed=e)
                return m
            except discord.NotFound:
                pass
        m = await ch.send(embed=e)
        await self.db.set_config(guild.id, vacation_status_message_id=m.id)
        return m

    async def inactive_members(self, guild, days):
        rows = await self.db.last_activity_for_cases(guild.id)
        vacations = {x["member_id"] for x in await self.db.active_vacations(guild.id)}
        now = datetime.now(timezone.utc)
        out = []
        for r in rows:
            if r["member_id"] in vacations:
                continue
            m = guild.get_member(r["member_id"])
            if not m:
                continue
            raw = r["last_activity"] or r["case_created_at"]
            dt = datetime.fromisoformat(raw)
            dt = dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
            d = int((now - dt).total_seconds() / 86400)
            if d >= days:
                out.append((m, d, r["last_activity"]))
        return sorted(out, key=lambda x: x[1], reverse=True)

    @coalesced_panel
    async def update_inactivity_report(self, guild):
        c = await self.db.get_config(guild.id)
        days = int(os.getenv("INACTIVITY_DAYS_DEFAULT", "3"))
        rows = await self.inactive_members(guild, days)
        lines = [f"⚠️ {m.mention} — **{d} дн.**" for m, d, _ in rows[:30]]
        e = base_embed(
            f"📉 Контроль неактива • {days}+ дней",
            "\n".join(lines) if lines else "✅ Участников с таким неактивом нет.",
            0xD64045 if lines else 0x3BAA72,
        )
        e.set_footer(
            text="Одобренный отпуск автоматически исключает участника из неактива."
        )
        ch = guild.get_channel(c.get("inactivity_report_channel_id") or 0)
        if not isinstance(ch, discord.TextChannel):
            return None
        mid = c.get("inactivity_report_message_id")
        if mid:
            try:
                m = await ch.fetch_message(mid)
                await edit_if_changed(m, embed=e)
                return m
            except discord.NotFound:
                pass
        m = await ch.send(embed=e)
        await self.db.set_config(guild.id, inactivity_report_message_id=m.id)
        return m

    async def expire_vacations(self, guild):
        # The date is informational: only an approved return restores roles.
        await self.update_vacation_status(guild)
