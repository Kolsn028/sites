from __future__ import annotations

import asyncio
import os
import re
from datetime import date, timedelta

import discord

from .ui import base_embed, activity_type_label
from .recruiting import update_assignment_card, interview_room
from .roles import configured_roles, STAFF_KEYS, HIGH_KEYS, notify_recruiters, notify_assistants
from .interactions import SafeModal, SafeView, serialized, private_thread


def _id_from_title(message: discord.Message | None, prefix: str) -> int | None:
    if not message or not message.embeds:
        return None
    m = re.search(rf"{re.escape(prefix)}\s*#(\d+)", message.embeds[0].title or "")
    return int(m.group(1)) if m else None


def _thread_name(name: str, uid: int) -> str:
    name = re.sub(r"[^0-9A-Za-zА-Яа-яЁё _.-]+", "", name).strip()
    name = re.sub(r"\s+", "-", name)[:60] or str(uid)
    return f"заявка-{name}"[:100]


class ApplicationModal(SafeModal, title="Подать заявку"):
    real_name_age = discord.ui.TextInput(label="Имя, возраст IRL и игровой ник", max_length=160)
    majestic_experience = discord.ui.TextInput(label="Ваш опыт на Majestic", max_length=500)
    shooting_skill = discord.ui.TextInput(label="Откат / уровень стрельбы", required=False, max_length=300)
    level_online_tz = discord.ui.TextInput(label="LVL, онлайн и часовой пояс", max_length=200)
    family_experience = discord.ui.TextInput(label="Опыт в семьях — где состояли?", style=discord.TextStyle.paragraph, max_length=900)

    def __init__(self, bot):
        super().__init__(timeout=300)
        self.bot = bot

    @serialized("application_submit", by_user=True)
    async def on_submit(self, interaction: discord.Interaction):
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            return
        cfg = await self.bot.db.get_config(interaction.guild.id)
        parent = interaction.guild.get_channel(cfg.get("applications_parent_channel_id") or 0)
        log_ch = interaction.guild.get_channel(cfg.get("applications_log_channel_id") or 0)
        recruiter_role = interaction.guild.get_role(cfg.get("recruiter_role_id") or 0)
        if not isinstance(parent, discord.TextChannel) or not isinstance(log_ch, discord.TextChannel) or not recruiter_role:
            return await interaction.response.send_message("⚠️ Система заявок не настроена. Выполните `/setup`.", ephemeral=True)

        await interaction.response.defer(ephemeral=True, thinking=True)
        existing = await self.bot.db._one("SELECT id,thread_id FROM applications WHERE guild_id=? AND applicant_id=? AND status IN ('pending','interview') AND thread_id IS NOT NULL ORDER BY id DESC LIMIT 1", (interaction.guild.id, interaction.user.id))
        if existing:
            return await interaction.followup.send(f"Твоя заявка уже рассматривается: <#{existing['thread_id']}>.", ephemeral=True)
        now = self.bot.now_iso()
        app_id = await self.bot.db.create_application(
            guild_id=interaction.guild.id,
            applicant_id=interaction.user.id,
            applicant_tag=str(interaction.user),
            real_name_age=str(self.real_name_age),
            majestic_experience=str(self.majestic_experience),
            shooting_skill=str(self.shooting_skill) or "Не указано",
            level_online_tz=str(self.level_online_tz),
            family_experience=str(self.family_experience),
            extra="",
            status="pending",
            created_at=now,
            updated_at=now,
        )

        try:
            thread = await private_thread(parent, interaction.user, configured_roles(interaction.guild, cfg, STAFF_KEYS),
                                          f"заявка-{app_id}-{interaction.user.display_name}")
        except Exception:
            await self.bot.db.update_application(app_id, status="failed", updated_at=self.bot.now_iso())
            raise

        await self.bot.db.update_application(app_id, thread_id=thread.id)
        e = base_embed(f"📋 Заявка #{app_id} • {interaction.user.display_name}", f"Кандидат: {interaction.user.mention}\nID: `{interaction.user.id}`")
        e.set_thumbnail(url=interaction.user.display_avatar.url)
        e.add_field(name="👤 Имя / возраст / ник", value=str(self.real_name_age)[:1024], inline=False)
        e.add_field(name="🎮 Опыт Majestic", value=str(self.majestic_experience)[:1024], inline=False)
        e.add_field(name="🎯 Стрельба / откат", value=(str(self.shooting_skill) or "Не указано")[:1024], inline=False)
        e.add_field(name="📊 LVL / онлайн / часовой пояс", value=str(self.level_online_tz)[:1024], inline=False)
        e.add_field(name="🏠 Опыт в семьях", value=str(self.family_experience)[:1024], inline=False)
        e.add_field(name="Статус", value="🟡 На рассмотрении", inline=False)
        e.add_field(name="Ответственный", value="Свободна — нажми «Взять заявку»", inline=False)
        try:
            await thread.send(content=None, embed=e, view=RecruiterActionView(self.bot))
        except Exception:
            await self.bot.db.update_application(app_id, status="failed", updated_at=self.bot.now_iso())
            await thread.delete(reason="Colombo: не удалось отправить анкету")
            raise

        log = await notify_recruiters(log_ch, interaction.guild, cfg, base_embed(f"📥 Новая заявка #{app_id}", f"{interaction.user.mention}\nВетка: {thread.mention}"))
        await self.bot.db.update_application(app_id, log_message_id=log.id)
        await interaction.followup.send(f"✅ Заявка **#{app_id}** отправлена: {thread.mention}", ephemeral=True)


class ApplicationPanelView(SafeView):
    def __init__(self, bot):
        super().__init__(timeout=None)
        self.bot = bot

    @discord.ui.button(label="Подать заявку", emoji="📝", style=discord.ButtonStyle.success, custom_id="colombo:application:open")
    async def open_application(self, interaction: discord.Interaction, _button):
        await interaction.response.send_modal(ApplicationModal(self.bot))


class RecruiterActionSelect(discord.ui.Select):
    def __init__(self, bot):
        self.bot = bot
        super().__init__(
            placeholder="Действия рекрутера…",
            min_values=1,
            max_values=1,
            custom_id="colombo:recruiter:action",
            options=[
                discord.SelectOption(label="Принять кандидата", value="accept", emoji="✅"),
                discord.SelectOption(label="Вызвать на обзвон", value="interview", emoji="📞"),
                discord.SelectOption(label="Отложить", value="hold", emoji="⏳"),
                discord.SelectOption(label="Отказать", value="reject", emoji="❌"),
            ],
        )

    @serialized("recruiter_decision")
    async def callback(self, interaction: discord.Interaction):
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            return
        if not await self.bot.is_recruiter(interaction.user):
            return await interaction.response.send_message("⛔ Только для рекрутеров.", ephemeral=True)
        app = await self.bot.db.get_application_by_thread(interaction.guild.id, interaction.channel.id)
        if not app:
            return await interaction.response.send_message("Заявка не найдена.", ephemeral=True)

        if app["status"] in ("accepted", "rejected"):
            return await interaction.response.send_message("Эта заявка уже закрыта.", ephemeral=True)
        if not app.get("assigned_to"):
            await interaction.response.send_message("Сначала нажми «Взять заявку».", ephemeral=True)
            await interaction.message.edit(view=RecruiterActionView(self.bot))
            return
        if app['assigned_to'] != interaction.user.id and not await self.bot.can_manage(interaction.user):
            return await interaction.response.send_message(f"Заявка закреплена за <@{app['assigned_to']}>. Решение принимает ответственный рекрутер.", ephemeral=True)
        await interaction.response.defer(ephemeral=True, thinking=True)
        action = self.values[0]
        cfg = await self.bot.db.get_config(interaction.guild.id)
        applicant = interaction.guild.get_member(app["applicant_id"])

        if action == "interview":
            text_ch = interaction.guild.get_channel(cfg.get("interview_channel_id") or 0)
            if not isinstance(text_ch, discord.TextChannel):
                return await interaction.followup.send("⚠️ Канал обзвона не настроен.", ephemeral=True)
            voice_ch = await interview_room(self.bot, interaction.guild, cfg, app)
            if not voice_ch:
                return await interaction.followup.send("Все каналы обзвона заняты, зарезервированы или недоступны кандидату. Повтори вызов позже; для создания трёх каналов используй /setup.", ephemeral=True)
            try:
                await text_ch.send(embed=base_embed(f"📞 Вызов на обзвон • заявка #{app['id']}", f"Кандидат: <@{app['applicant_id']}>\nОтветственный: <@{app['assigned_to']}>\nГолосовой: {voice_ch.mention}\nКанал зарезервирован на 15 минут.", 0x5865F2), allowed_mentions=discord.AllowedMentions.none())
            except discord.DiscordException:
                await self.bot.db.clear_interview(app['id'], self.bot.now_iso())
                raise
            if os.getenv("MOVE_TO_INTERVIEW_VOICE", "false").lower() == "true" and applicant and applicant.voice and isinstance(voice_ch, discord.VoiceChannel):
                try:
                    await applicant.move_to(voice_ch)
                except discord.DiscordException:
                    pass
            if applicant:
                try:
                    await applicant.send(embed=base_embed("Приглашение на обзвон • Colombo", f"Твоя заявка принята на следующий этап.\nКанал беседы: {voice_ch.mention if voice_ch else text_ch.mention}\nВетка: {interaction.channel.jump_url}"))
                except discord.Forbidden:
                    pass
            return await interaction.followup.send(f"📞 Вызов отправлен. Канал: {voice_ch.mention}, резерв — 15 минут.", ephemeral=True)

        if action == "hold":
            await self.bot.db.update_application(app["id"], status="pending", interview_room_id=None, interview_until=None, handled_by=interaction.user.id, updated_at=self.bot.now_iso())
            await interaction.followup.send("⏳ Оставлено на рассмотрении.", ephemeral=True)
            return

        if app["status"] in ("accepted", "rejected"):
            return await interaction.followup.send("Эта заявка уже закрыта.", ephemeral=True)

        accepted = action == "accept"
        status = "accepted" if accepted else "rejected"
        color = 0x3BAA72 if accepted else 0xD64045
        title = "✅ Кандидат принят" if accepted else "❌ По заявке отказ"
        if accepted:
            if not applicant:
                return await interaction.followup.send("Участник вышел с сервера. Решение не сохранено.", ephemeral=True)
            from .membership import accept_member
            try:
                await accept_member(applicant, cfg, f"Заявка #{app['id']}: принят в Colombo")
            except (discord.DiscordException, ValueError) as exc:
                return await interaction.followup.send(f"Не удалось завершить выдачу Colombo + Test и снятие Guest. Проверь роли и права бота, затем повтори приём. {exc}", ephemeral=True)
        await self.bot.db.bump_recruiter(interaction.guild.id, interaction.user.id, accepted=1 if accepted else 0, rejected=0 if accepted else 1)
        await self.bot.db.update_application(app["id"], status=status, interview_room_id=None, interview_until=None, handled_by=interaction.user.id, updated_at=self.bot.now_iso())

        await interaction.followup.send("✅ Решение сохранено.", ephemeral=True)
        await interaction.channel.send(embed=base_embed(title, f"Рекрутер: {interaction.user.mention}\nКандидат: <@{app['applicant_id']}>", color))
        if accepted:
            log_ch = interaction.guild.get_channel(cfg.get("applications_log_channel_id") or 0)
            if isinstance(log_ch, discord.TextChannel):
                await notify_recruiters(log_ch, interaction.guild, cfg,
                    base_embed(f"Принят • заявка #{app['id']}", f"Кандидат: <@{app['applicant_id']}>\nРанг: **Test**\nРешение: {interaction.user.display_name}", 0x3BAA72))
        await self.bot.send_or_update_leaderboard(interaction.guild)

        if accepted and applicant and os.getenv("AUTO_CREATE_CASE_ON_ACCEPT", "true").lower() == "true":
            case_ch = await self.bot.ensure_personal_case(applicant)
            if case_ch:
                await interaction.channel.send(f"📁 Личное дело: {case_ch.mention}")

        await asyncio.sleep(5)
        if isinstance(interaction.channel, discord.Thread):
            try:
                await interaction.channel.edit(archived=True, locked=True)
            except discord.DiscordException:
                pass


class RecruiterActionView(SafeView):
    def __init__(self, bot):
        super().__init__(timeout=None)
        self.bot = bot
        self.add_item(RecruiterActionSelect(bot))

    @discord.ui.button(label="Взять заявку", emoji="🙋", style=discord.ButtonStyle.primary, custom_id="colombo:recruiter:claim", row=1)
    @serialized("recruiter_decision")
    async def claim(self, interaction, _button):
        if not isinstance(interaction.user, discord.Member) or not await self.bot.is_recruiter(interaction.user):
            return await interaction.response.send_message("Только Recruit- и руководство.", ephemeral=True)
        await interaction.response.defer(ephemeral=True, thinking=True)
        app = await self.bot.db.get_application_by_thread(interaction.guild.id, interaction.channel.id)
        if not app or app['status'] not in ('pending', 'interview'):
            return await interaction.followup.send("Заявка уже закрыта или не найдена.", ephemeral=True)
        claimed = await self.bot.db.claim_application(app['id'], interaction.user.id, self.bot.now_iso())
        current = await self.bot.db.get_application_by_thread(interaction.guild.id, interaction.channel.id)
        from .membership import sync_application_members
        await sync_application_members(self.bot, interaction.channel, current)
        await update_assignment_card(interaction.message, current['assigned_to'])
        if not claimed:
            return await interaction.followup.send(f"Ответственный уже назначен: <@{current['assigned_to']}>.", ephemeral=True)
        await interaction.followup.send("Заявка закреплена за тобой. Теперь доступны вызов, приём и отказ.", ephemeral=True)

    @discord.ui.button(label="Освободить заявку", emoji="↩️", style=discord.ButtonStyle.secondary, custom_id="colombo:recruiter:release", row=1)
    @serialized("recruiter_decision")
    async def release(self, interaction, _button):
        if not isinstance(interaction.user, discord.Member) or not await self.bot.is_recruiter(interaction.user):
            return await interaction.response.send_message("Только Recruit- и руководство.", ephemeral=True)
        await interaction.response.defer(ephemeral=True, thinking=True)
        app = await self.bot.db.get_application_by_thread(interaction.guild.id, interaction.channel.id)
        if not app or app['status'] not in ('pending', 'interview'):
            return await interaction.followup.send("Заявка уже закрыта или не найдена.", ephemeral=True)
        if app.get('assigned_to') != interaction.user.id and not await self.bot.can_manage(interaction.user):
            return await interaction.followup.send("Освободить заявку может ответственный рекрутер.", ephemeral=True)
        await self.bot.db.release_application(app['id'], self.bot.now_iso())
        from .membership import sync_application_members
        await sync_application_members(self.bot, interaction.channel, {**app, 'assigned_to': None})
        await update_assignment_card(interaction.message, None)
        await interaction.followup.send("Заявка свободна. Резерв голосового канала снят.", ephemeral=True)


class VacationModal(SafeModal, title="Заявка на отдых"):
    reason = discord.ui.TextInput(label="Причина отдыха", style=discord.TextStyle.paragraph, max_length=700)
    days = discord.ui.TextInput(label="На сколько дней?", placeholder="Напр.: 7", max_length=3)

    def __init__(self, bot):
        super().__init__(timeout=300)
        self.bot = bot

    @serialized("vacation_submit", by_user=True)
    async def on_submit(self, interaction: discord.Interaction):
        try:
            days = int(str(self.days).strip())
        except ValueError:
            return await interaction.response.send_message("Укажи количество дней числом.", ephemeral=True)
        if not 1 <= days <= 60:
            return await interaction.response.send_message("Допустимо от 1 до 60 дней.", ephemeral=True)
        if await self.bot.db.pending_vacation_for_member(interaction.guild.id, interaction.user.id):
            return await interaction.response.send_message("У тебя уже есть активная заявка/отпуск.", ephemeral=True)
        cfg = await self.bot.db.get_config(interaction.guild.id)
        review_ch = interaction.guild.get_channel(cfg.get("vacation_review_channel_id") or 0)
        if not isinstance(review_ch, discord.TextChannel):
            return await interaction.response.send_message("Канал отпусков не настроен.", ephemeral=True)
        accepted = cfg.get("accepted_role_id")
        if not await self.bot.is_family_member(interaction.user):
            return await interaction.response.send_message("Отдых доступен участникам семьи.", ephemeral=True)
        await interaction.response.defer(ephemeral=True, thinking=True)
        start, end = date.today(), date.today() + timedelta(days=days)
        vid = await self.bot.db.create_vacation(guild_id=interaction.guild.id, member_id=interaction.user.id, member_tag=str(interaction.user), reason=str(self.reason), start_date=start.isoformat(), end_date=end.isoformat(), status="pending", created_at=self.bot.now_iso(), updated_at=self.bot.now_iso())
        e = base_embed(f"🌴 Заявка на отдых #{vid}", f"Участник: {interaction.user.mention}", 0xD5A43A)
        e.add_field(name="Причина", value=str(self.reason)[:1024], inline=False)
        e.add_field(name="Период", value=f"{start.strftime('%d.%m.%Y')} → {end.strftime('%d.%m.%Y')} ({days} дн.)", inline=False)
        e.add_field(name="Статус", value="🟡 Ожидает решения", inline=False)
        leaders = configured_roles(interaction.guild, cfg, HIGH_KEYS)
        if not any(leaders):
            await self.bot.db.update_vacation(vid, status="failed", updated_at=self.bot.now_iso())
            raise ValueError("Настрой роли руководства через `/setup_auto`.")
        try:
            thread = await private_thread(review_ch, interaction.user, leaders, f"отдых-{vid}-{interaction.user.display_name}")
        except Exception:
            await self.bot.db.update_vacation(vid, status="failed", updated_at=self.bot.now_iso())
            raise
        await self.bot.db.update_vacation(vid, thread_id=thread.id)
        try:
            msg = await thread.send(embed=e, view=VacationDecisionView(self.bot))
        except Exception:
            await self.bot.db.update_vacation(vid, status="failed", updated_at=self.bot.now_iso())
            await thread.delete(reason="Colombo: не удалось отправить заявку отдыха")
            raise
        await self.bot.db.update_vacation(vid, review_message_id=msg.id)
        await notify_assistants(thread, interaction.guild, cfg, base_embed("🌴 Нужна проверка отдыха", "Новая заявка ожидает решения Ass.Deputy или руководства."))
        await interaction.followup.send(f"Заявка на отдых **#{vid}** отправлена: {thread.mention}", ephemeral=True)


class VacationPanelView(SafeView):
    def __init__(self, bot):
        super().__init__(timeout=None)
        self.bot = bot

    @discord.ui.button(label="Подать заявку на отдых", emoji="🌴", style=discord.ButtonStyle.primary, custom_id="colombo:vacation:open")
    async def open_vacation(self, interaction, _button):
        await interaction.response.send_modal(VacationModal(self.bot))

    @discord.ui.button(label="Вернуться из отпуска", emoji="↩️", style=discord.ButtonStyle.success, custom_id="colombo:vacation:return")
    async def return_vacation(self, interaction, _button):
        from .leave import ReturnModal
        await interaction.response.send_modal(ReturnModal(self.bot))


class VacationDecisionView(SafeView):
    def __init__(self, bot):
        super().__init__(timeout=None)
        self.bot = bot

    @serialized("vacation_decision")
    async def _handle(self, interaction: discord.Interaction, approve: bool):
        if not isinstance(interaction.user, discord.Member) or not await self.bot.can_review_vacation(interaction.user):
            return await interaction.response.send_message("⛔ Недостаточно прав.", ephemeral=True)
        vid = _id_from_title(interaction.message, "Заявка на отдых")
        vac = await self.bot.db.get_vacation(vid) if vid else None
        if not vac or vac['guild_id'] != interaction.guild_id or vac["status"] not in ('pending','applying'):
            return await interaction.response.send_message("Заявка уже обработана или не найдена.", ephemeral=True)
        await interaction.response.defer()
        async with self.bot.operation_locks[('leave',interaction.guild_id,vac['member_id'])]:
            vac=await self.bot.db.get_vacation(vac['id'])
            if vac['status'] not in ('pending','applying'):
                return await interaction.followup.send('Заявка уже обработана.',ephemeral=True)
            if vac['status']=='applying' and not approve:
                return await interaction.followup.send('Снятие ролей уже начато. Повтори одобрение для завершения.',ephemeral=True)
            if approve:
                from .leave import begin_leave
                await begin_leave(self.bot,interaction.guild,vac)
            else:
                await self.bot.db.update_vacation(vac['id'],status='rejected',updated_at=self.bot.now_iso())
            await self.bot.db.update_vacation(vac['id'],handled_by=interaction.user.id)
        e = interaction.message.embeds[0].copy()
        e.color = 0x3BAA72 if approve else 0xD64045
        e.set_field_at(2, name="Статус", value=("✅ Одобрено" if approve else "❌ Отклонено") + f" • {interaction.user.mention}", inline=False)
        await interaction.edit_original_response(embed=e, view=None)
        await self.bot.update_vacation_status(interaction.guild)
        await self.bot.update_inactivity_report(interaction.guild)
        if isinstance(interaction.channel, discord.Thread):
            await interaction.channel.edit(archived=True, locked=True, reason="Colombo: решение по отдыху принято")

    @discord.ui.button(label="Одобрить", emoji="✅", style=discord.ButtonStyle.success, custom_id="colombo:vacation:approve")
    async def approve(self, interaction, _button):
        await self._handle(interaction, True)

    @discord.ui.button(label="Отклонить", emoji="❌", style=discord.ButtonStyle.danger, custom_id="colombo:vacation:reject")
    async def reject(self, interaction, _button):
        await self._handle(interaction, False)


class CasePanelView(SafeView):
    def __init__(self, bot):
        super().__init__(timeout=None)
        self.bot = bot

    @discord.ui.button(label="Создать / открыть личное дело", emoji="📁", style=discord.ButtonStyle.primary, custom_id="colombo:case:open")
    async def open_case(self, interaction, _button):
        if not isinstance(interaction.user, discord.Member):
            return
        cfg = await self.bot.db.get_config(interaction.guild.id)
        accepted = cfg.get("accepted_role_id")
        if not await self.bot.is_family_member(interaction.user):
            return await interaction.response.send_message("⛔ Личное дело доступно участникам семьи.", ephemeral=True)
        await interaction.response.defer(ephemeral=True, thinking=True)
        ch = await self.bot.ensure_personal_case(interaction.user)
        await interaction.followup.send(f"📁 Твоё личное дело: {ch.mention}" if ch else "⚠️ Не удалось создать дело. Проверь `/setup` и права бота.", ephemeral=True)


class ActivityTypeSelect(discord.ui.Select):
    def __init__(self, bot):
        self.bot = bot
        super().__init__(placeholder="Выбрать тип активности…", min_values=1, max_values=1, custom_id="colombo:activity:type", options=[
            discord.SelectOption(label="Капт", value="capt", emoji="⚔️"),
            discord.SelectOption(label="MCL",value="mcl",emoji="🟥"),
            discord.SelectOption(label="VZM",value="vzm",emoji="🟩"),
            discord.SelectOption(label="VZZ",value="vzz",emoji="🟦"),
            discord.SelectOption(label="Контракт",value="contract",emoji="🟠"),
            discord.SelectOption(label="МП", value="mp", emoji="🎯"),
            discord.SelectOption(label="МШ", value="msh", emoji="🛡️"),
            discord.SelectOption(label="Тренировка", value="training", emoji="🏋️"),
            discord.SelectOption(label="Другое", value="other", emoji="📌"),
        ])

    async def callback(self, interaction: discord.Interaction):
        sid = _id_from_title(interaction.message, "Активность")
        sub = await self.bot.db.get_activity(sid) if sid else None
        if not sub:
            return await interaction.response.send_message("Отчёт не найден.", ephemeral=True)
        if interaction.user.id != sub["member_id"] and not await self.bot.is_high_staff(interaction.user):
            return await interaction.response.send_message("⛔ Только владелец дела или Recruit- и выше.", ephemeral=True)
        if sub["status"] != "pending_classification":
            return await interaction.response.send_message("Тип уже выбран или отчёт обработан.", ephemeral=True)
        cat = self.values[0]
        points = self.bot.activity_points(cat)
        await self.bot.db.update_activity(sub["id"], category=cat, points=points, status="pending_review", updated_at=self.bot.now_iso())
        e = interaction.message.embeds[0].copy()
        e.color = 0x5865F2
        e.set_field_at(0, name="Тип", value=activity_type_label(cat), inline=True)
        e.set_field_at(1, name="Баллы", value=f"**{points}**", inline=True)
        e.set_field_at(2, name="Статус", value="🔵 Ожидает проверки Recruit- и выше", inline=False)
        await interaction.response.edit_message(embed=e, view=ActivityReviewView(self.bot))
        cfg = await self.bot.db.get_config(interaction.guild.id)
        await notify_assistants(interaction.channel, interaction.guild, cfg,
            base_embed('📊 Отчёт готов к проверке', f'Отчёт #{sub["id"]} — выбрана категория.'))


class ActivityClassifyView(SafeView):
    def __init__(self, bot):
        super().__init__(timeout=None)
        self.add_item(ActivityTypeSelect(bot))


class RejectActivityModal(SafeModal, title="Отклонить активность"):
    reason = discord.ui.TextInput(label="Причина", style=discord.TextStyle.paragraph, max_length=500)

    def __init__(self, bot, sid: int, message: discord.Message):
        super().__init__(timeout=180)
        self.bot, self.sid, self.message = bot, sid, message

    async def on_submit(self, interaction: discord.Interaction):
        if not isinstance(interaction.user, discord.Member) or not await self.bot.is_high_staff(interaction.user):
            return await interaction.response.send_message("Отчёты проверяют Recruit- и выше.", ephemeral=True)
        sub = await self.bot.db.get_activity(self.sid)
        if not sub or sub["status"] in ("approved", "rejected"):
            return await interaction.response.send_message("Отчёт уже обработан.", ephemeral=True)
        await self.bot.db.update_activity(sub["id"], status="rejected", note=str(self.reason), handled_by=interaction.user.id, updated_at=self.bot.now_iso())
        e = self.message.embeds[0].copy()
        e.color = 0xD64045
        e.set_field_at(2, name="Статус", value=f"❌ Отклонено • {interaction.user.mention}\nПричина: {str(self.reason)[:500]}", inline=False)
        await interaction.response.edit_message(embed=e, view=None)


class ActivityReviewView(SafeView):
    def __init__(self, bot):
        super().__init__(timeout=None)
        self.bot = bot

    async def _sub(self, interaction):
        if not isinstance(interaction.user, discord.Member) or not await self.bot.is_high_staff(interaction.user):
            await interaction.response.send_message("⛔ Проверять активность может только Recruit- и выше.", ephemeral=True)
            return None
        sid = _id_from_title(interaction.message, "Активность")
        return await self.bot.db.get_activity(sid) if sid else None

    @discord.ui.button(label="Засчитать", emoji="✅", style=discord.ButtonStyle.success, custom_id="colombo:activity:approve")
    async def approve(self, interaction, _button):
        sub = await self._sub(interaction)
        if not sub:
            return
        if sub["status"] in ("approved", "rejected"):
            return await interaction.response.send_message("Отчёт уже обработан.", ephemeral=True)
        await self.bot.db.update_activity(sub["id"], status="approved", handled_by=interaction.user.id, updated_at=self.bot.now_iso())
        e = interaction.message.embeds[0].copy()
        e.color = 0x3BAA72
        e.set_field_at(2, name="Статус", value=f"✅ Засчитано • {interaction.user.mention}", inline=False)
        await interaction.response.edit_message(embed=e, view=None)
        await self.bot.update_inactivity_report(interaction.guild)
        from .profiles import refresh_member
        await refresh_member(self.bot,interaction.guild,sub["member_id"])

    @discord.ui.button(label="Отклонить", emoji="❌", style=discord.ButtonStyle.danger, custom_id="colombo:activity:reject")
    async def reject(self, interaction, _button):
        sub = await self._sub(interaction)
        if not sub:
            return
        await interaction.response.send_modal(RejectActivityModal(self.bot, sub["id"], interaction.message))

    @discord.ui.button(label="Сменить тип", emoji="🔄", style=discord.ButtonStyle.secondary, custom_id="colombo:activity:reclassify")
    async def reclassify(self, interaction, _button):
        sub = await self._sub(interaction)
        if not sub:
            return
        if sub["status"] in ("approved", "rejected"):
            return await interaction.response.send_message("Обработанный отчёт менять нельзя.", ephemeral=True)
        await self.bot.db.update_activity(sub["id"], category="unclassified", points=0, status="pending_classification", updated_at=self.bot.now_iso())
        e = interaction.message.embeds[0].copy()
        e.color = 0xD5A43A
        e.set_field_at(0, name="Тип", value="❔ Не выбран", inline=True)
        e.set_field_at(1, name="Баллы", value="—", inline=True)
        e.set_field_at(2, name="Статус", value="🟡 Нужно выбрать тип", inline=False)
        await interaction.response.edit_message(embed=e, view=ActivityClassifyView(self.bot))

