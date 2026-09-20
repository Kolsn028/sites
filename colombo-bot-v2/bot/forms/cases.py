from __future__ import annotations

import discord
from ..interactions import SafeView


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
