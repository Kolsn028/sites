from __future__ import annotations

from datetime import date, timedelta
import discord
from ..ui import base_embed
from ..roles import configured_roles, HIGH_KEYS, notify_assistants
from ..interactions import SafeModal, SafeView, serialized, private_thread
from .shared import _id_from_title


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
        await notify_assistants(thread, interaction.guild, cfg, base_embed("🌴 Нужна проверка отдыха", "Новая заявка ожидает решения High или руководства."))
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
        from ..leave import ReturnModal
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
                return await interaction.followup.send('Оформление отдыха уже начато. Повтори одобрение для завершения.',ephemeral=True)
            if approve:
                from ..leave import begin_leave
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
