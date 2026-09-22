"""Tier application form and the persistent entry panel."""
import json
import discord
from ..interactions import SafeModal, SafeView, private_thread
from ..ui import base_embed
from .common import GUILD_ID, TIERCHECK_ROLE_ID, TIER_ROLES, tier_channel_topic, tier_from_channel, can_review
from .review import TierReviewView
from .reviewers import sync_reviewers


class TierModal(SafeModal):
    identity = discord.ui.TextInput(
        label="Ник / возраст / статик",
        placeholder="Nickname / 23 / 4949",
        max_length=150,
    )
    gg = discord.ui.TextInput(
        label="Откаты с ГГ",
        placeholder="Откаты с ГГ (спешики + сайга, от 8 людей в лобаке, онли 18 и 19 сервер)",
        style=discord.TextStyle.paragraph,
        max_length=900,
    )
    kapt = discord.ui.TextInput(
        label="Откаты с Каптов",
        placeholder="Ссылки на откаты с Каптов",
        style=discord.TextStyle.paragraph,
        max_length=900,
    )

    def __init__(self, bot, tier):
        super().__init__(title=f"Заявка на тир {tier}", timeout=300)
        self.bot = bot
        self.tier = tier
        mcl_required = tier in (1, 2)
        self.mcl = discord.ui.TextInput(
            label="Откаты с МЦЛ",
            placeholder=(
                "Ссылки на откаты с МЦЛ" if mcl_required else "Ссылки, если есть откаты"
            ),
            style=discord.TextStyle.paragraph,
            required=mcl_required,
            max_length=900,
        )
        self.add_item(self.mcl)
        self.purpose = discord.ui.TextInput(
            label="Для чего тебе нужен тир?",
            style=discord.TextStyle.paragraph,
            max_length=600,
        )
        self.add_item(self.purpose)

    async def on_submit(self, interaction):
        if (
            interaction.guild_id != GUILD_ID
            or not isinstance(interaction.user, discord.Member)
            or not await self.bot.is_family_member(interaction.user)
        ):
            return await interaction.response.send_message(
                "Заявки доступны участникам Colombo.", ephemeral=True
            )
        await interaction.response.defer(ephemeral=True)
        async with self.bot.operation_locks[
            ("tier_member", interaction.guild_id, interaction.user.id)
        ]:
            existing = await self.bot.db.find_open_tier(
                interaction.guild_id, interaction.user.id
            )
            if existing:
                return await interaction.followup.send(
                    f"У тебя уже есть заявка: <#{existing['thread_id']}>.",
                    ephemeral=True,
                )
            if (
                getattr(interaction.channel, "topic", None) or ""
            ) != tier_channel_topic(self.tier, self.bot.user.id, interaction.guild_id):
                raise ValueError("Открой актуальный канал тира.")
            if not interaction.guild.get_role(TIER_ROLES[self.tier]):
                raise ValueError("Роль тира удалена. Сообщи High.")
            reviewer_role = interaction.guild.get_role(TIERCHECK_ROLE_ID)
            if not reviewer_role:
                raise ValueError("Не найдена роль tiercheck.")
            thread = await private_thread(
                interaction.channel,
                interaction.user,
                [reviewer_role],
                f"тир-{self.tier}-{interaction.user.display_name}",
            )
            fields = [
                ("Ник / возраст / статик", str(self.identity)),
                ("Откаты с ГГ", str(self.gg)),
                ("Откаты с Каптов", str(self.kapt)),
                ("Откаты с МЦЛ", str(self.mcl) or "Не приложены"),
                ("Для чего нужен тир", str(self.purpose)),
            ]
            try:
                request_id = await self.bot.db.create_progress(
                    interaction.guild_id,
                    interaction.user.id,
                    f"tier_{self.tier}",
                    thread.id,
                    json.dumps(fields, ensure_ascii=False),
                    self.bot.now_iso(),
                )
            except Exception:
                await thread.delete(reason="Colombo: ошибка сохранения заявки")
                raise
            embed = base_embed(
                f"Заявка #{request_id} • тир {self.tier}",
                f"Участник: {interaction.user.mention}",
                0xD5A43A,
            )
            for name, value in fields:
                embed.add_field(name=name, value=value, inline=False)
            try:
                await thread.send(
                    content=f"<@&{TIERCHECK_ROLE_ID}> · Новая заявка на тир {self.tier}",
                    embed=embed,
                    view=TierReviewView(self.bot),
                    allowed_mentions=discord.AllowedMentions(
                        everyone=False,
                        users=False,
                        roles=[discord.Object(id=TIERCHECK_ROLE_ID)],
                        replied_user=False,
                    ),
                )
            except Exception:
                await self.bot.db.fail_progress(request_id)
                raise
            await interaction.followup.send(
                f"Заявка отправлена: {thread.mention}", ephemeral=True
            )

class TierPanelView(SafeView):
    def __init__(self, bot):
        super().__init__(timeout=None)
        self.bot = bot

    @discord.ui.button(
        label="Подать заявку",
        emoji="📝",
        style=discord.ButtonStyle.success,
        custom_id="colombo:tier:apply",
    )
    async def apply(self, interaction, _):
        tier = tier_from_channel(
            interaction.channel, self.bot.user.id, interaction.guild_id
        )
        if interaction.guild_id != GUILD_ID or tier is None:
            return await interaction.response.send_message(
                "Канал тира не настроен.", ephemeral=True
            )
        await interaction.response.send_modal(TierModal(self.bot, tier))

    @discord.ui.button(
        label="Восстановить доступ к заявкам",
        emoji="🔑",
        style=discord.ButtonStyle.secondary,
        custom_id="colombo:tier:restore_access",
    )
    async def restore_access(self, interaction, _):
        if not await can_review(self.bot, interaction):
            return await interaction.response.send_message(
                "Нужна роль tiercheck.", ephemeral=True
            )
        await interaction.response.defer(ephemeral=True, thinking=True)
        added, failed = await sync_reviewers(
            self.bot, interaction.guild, interaction.user
        )
        await interaction.followup.send(
            f"Доступ проверен. Добавлено веток: {added}. Ошибок: {failed}. Архивные заявки остаются закрытыми.",
            ephemeral=True,
        )
