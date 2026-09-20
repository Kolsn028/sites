from __future__ import annotations

import asyncio
import os
import discord
from ..ui import base_embed
from ..recruiting import update_assignment_card, interview_room
from ..roles import notify_recruiters, application_recruiters
from ..interactions import SafeModal, SafeView, serialized, private_thread


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

        if not interaction.guild.chunked:
            await interaction.guild.chunk(cache=True)
        try:
            thread = await private_thread(parent, interaction.user, [],
                                          f"заявка-{app_id}-{interaction.user.display_name}",
                                          reviewers=application_recruiters(interaction.guild, cfg))
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

        await notify_recruiters(thread, interaction.guild, cfg, base_embed("📥 Новая заявка", "Рекруты, возьмите заявку на проверку."))
        log = await log_ch.send(allowed_mentions=discord.AllowedMentions.none(), embed=base_embed(f"📥 Новая заявка #{app_id}", f"{interaction.user.mention}\nВетка: {thread.mention}"))
        await self.bot.db.update_application(app_id, log_message_id=log.id)
        await interaction.followup.send(f"✅ Заявка **#{app_id}** отправлена: {thread.mention}", ephemeral=True)


class ApplicationPanelView(SafeView):
    def __init__(self, bot):
        super().__init__(timeout=None)
        self.bot = bot

    @discord.ui.button(label="Подать заявку", emoji="📝", style=discord.ButtonStyle.success, custom_id="colombo:application:open")
    async def open_application(self, interaction: discord.Interaction, _button):
        await interaction.response.send_modal(ApplicationModal(self.bot))

    @discord.ui.button(label="Мои заявки",emoji="📬",style=discord.ButtonStyle.secondary,custom_id="colombo:application:mine")
    async def mine(self,interaction,_button):
        from ..dashboard import open_requests
        await open_requests(self.bot,interaction,own=True)


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
        action = self.values[0]
        if action == "reject":
            from ..enhancements import RejectionModal
            return await interaction.response.send_modal(RejectionModal(self.bot, app["id"]))
        await interaction.response.defer(ephemeral=True, thinking=True)
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
            from ..membership import accept_member
            try:
                await accept_member(applicant, cfg, f"Заявка #{app['id']}: принят в Colombo")
            except (discord.DiscordException, ValueError) as exc:
                return await interaction.followup.send(f"Не удалось завершить выдачу Colombo + Test и снятие Guest. Проверь роли и права бота, затем повтори приём. {exc}", ephemeral=True)
        from ..enhancements import decide_application
        if not await decide_application(self.bot.db, app['id'], interaction.guild_id, interaction.user.id, status, self.bot.now_iso()):
            return await interaction.followup.send('Решение уже сохранено.', ephemeral=True)

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
        from ..membership import sync_application_members
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
        from ..membership import sync_application_members
        await sync_application_members(self.bot, interaction.channel, {**app, 'assigned_to': None})
        await update_assignment_card(interaction.message, None)
        await interaction.followup.send("Заявка свободна. Резерв голосового канала снят.", ephemeral=True)
