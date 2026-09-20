from __future__ import annotations

import discord
from ..ui import base_embed, activity_type_label
from ..roles import notify_assistants
from ..interactions import SafeModal, SafeView
from .shared import _id_from_title


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
        from ..profiles import refresh_member
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
