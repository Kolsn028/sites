"""Tier decisions: reviewer authorization, role replacement and result."""
import discord
from ..interactions import SafeModal, SafeView
from ..services.ranks import award_tier
from ..ui import base_embed
from .common import KINDS, can_review


class TierDecision(SafeModal):
    reason = discord.ui.TextInput(
        label="Комментарий / причина отказа",
        style=discord.TextStyle.paragraph,
        max_length=700,
        min_length=3,
    )

    def __init__(self, bot, accepted):
        super().__init__(
            title="Одобрить тир" if accepted else "Причина отказа", timeout=300
        )
        self.bot = bot
        self.accepted = accepted

    async def on_submit(self, interaction):
        if not await can_review(self.bot, interaction):
            return await interaction.response.send_message(
                "Рассматривают только участники с ролью tiercheck.", ephemeral=True
            )
        reason = str(self.reason).strip()
        if len(reason) < 3:
            return await interaction.response.send_message(
                "Напиши комментарий не короче трёх символов.", ephemeral=True
            )
        await interaction.response.defer(ephemeral=True)
        row = await self.bot.db.progress_by_thread(
            interaction.guild_id, interaction.channel_id
        )
        if not row or row["kind"] not in KINDS:
            return await interaction.followup.send("Заявка не найдена.", ephemeral=True)
        async with self.bot.operation_locks[
            ("tier_member", interaction.guild_id, row["member_id"])
        ]:
            row = await self.bot.db.progress_by_id(row["id"])
            if row["status"] not in ("pending", "applying"):
                return await interaction.followup.send(
                    "Заявка уже закрыта.", ephemeral=True
                )
            if row["member_id"] == interaction.user.id:
                return await interaction.followup.send(
                    "Свою заявку рассматривать нельзя.", ephemeral=True
                )
            if row["status"] == "applying" and not self.accepted:
                return await interaction.followup.send(
                    "Замена роли уже началась. Заверши одобрение.", ephemeral=True
                )
            tier = int(row["kind"][-1])
            if self.accepted:
                member = await interaction.guild.fetch_member(row["member_id"])
                if not await self.bot.is_family_member(member):
                    return await interaction.followup.send(
                        "Игрок больше не состоит в Colombo.", ephemeral=True
                    )
                await self.bot.db.set_progress_decision(
                    row["id"], "applying", interaction.user.id, reason
                )
                try:
                    await award_tier(interaction.guild, member, tier)
                except (discord.DiscordException, ValueError) as exc:
                    return await interaction.followup.send(
                        f"Замена тира не завершена: {exc} Исправь права и повтори одобрение.",
                        ephemeral=True,
                    )
            status = "approved" if self.accepted else "rejected"
            embed = base_embed(
                (
                    f"✅ Тир {tier} одобрен"
                    if self.accepted
                    else f"❌ Отказ в тире {tier}"
                ),
                f"Участник: <@{row['member_id']}>\nРассмотрел: {interaction.user.mention}\n"
                + ("Комментарий: " if self.accepted else "Причина отказа: ")
                + discord.utils.escape_markdown(reason),
                0x3BAA72 if self.accepted else 0xD64045,
            )
            await interaction.channel.send(
                embed=embed, allowed_mentions=discord.AllowedMentions.none()
            )
            await self.bot.db.set_progress_decision(
                row["id"], status, interaction.user.id, reason
            )
            from ..thread_archive import schedule_archive

            await schedule_archive(self.bot, interaction.channel)
            dm_sent = True
            try:
                member = await interaction.guild.fetch_member(row["member_id"])
                await member.send(
                    embed=embed, allowed_mentions=discord.AllowedMentions.none()
                )
            except discord.DiscordException:
                dm_sent = False
            await interaction.followup.send(
                "Решение сохранено. "
                + (
                    "Игроку отправлено личное сообщение."
                    if dm_sent
                    else "Личные сообщения закрыты или недоступны; результат оставлен в ветке."
                ),
                ephemeral=True,
            )

class TierReviewView(SafeView):
    def __init__(self, bot):
        super().__init__(timeout=None)
        self.bot = bot

    async def interaction_check(self, interaction):
        if not await can_review(self.bot, interaction):
            await interaction.response.send_message(
                "Рассматривают только участники с ролью tiercheck.", ephemeral=True
            )
            return False
        return True

    @discord.ui.button(
        label="Одобрить",
        style=discord.ButtonStyle.success,
        custom_id="colombo:tier:approve",
    )
    async def approve(self, interaction, _):
        await interaction.response.send_modal(TierDecision(self.bot, True))

    @discord.ui.button(
        label="Отказать",
        style=discord.ButtonStyle.danger,
        custom_id="colombo:tier:reject",
    )
    async def reject(self, interaction, _):
        await interaction.response.send_modal(TierDecision(self.bot, False))
