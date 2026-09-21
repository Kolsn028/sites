"""Tier applications: explicit roles, private review and resumable role changes."""

import json
import asyncio
import discord
from .performance import edit_if_changed
from .interactions import SafeModal, SafeView, private_thread
from .roles import STAFF_KEYS, configured_roles
from .ui import base_embed
from .access import TIER_GUILD_ID as GUILD_ID, TIERCHECK_ROLE_ID, may_review_tiers
from .services.ranks import TIER_ROLES, award_tier

KINDS = ("tier_1", "tier_2", "tier_3")


def tier_channel_topic(tier: int, bot_id: int, guild_id: int) -> str:
    # Тема связывает канал с конкретным ботом и сервером; имя можно менять.
    return f"colombo:tier:{tier}:{bot_id}:{guild_id}"


def tier_from_channel(channel, bot_id: int, guild_id: int) -> int | None:
    topic = getattr(channel, "topic", None)
    for tier in TIER_ROLES:
        if topic == tier_channel_topic(tier, bot_id, guild_id):
            return tier
    return None


async def can_review(bot, interaction: discord.Interaction) -> bool:
    return isinstance(interaction.user, discord.Member) and may_review_tiers(
        interaction.user, interaction.guild_id
    )


def panel(tier: int) -> discord.Embed:
    return base_embed(
        f"Повышение на тир {tier}",
        "Прикрепи ссылки на откаты и расскажи, зачем тебе нужен тир.\nДля каждой заявки создаётся отдельная приватная ветка; уведомления находятся внутри неё.\nРассматривают **tiercheck**. При одобрении другие тиры заменяются выбранным.",
        0xA82D40,
    )


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
            from .thread_archive import schedule_archive

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


async def install(bot, guild):
    if guild.id != GUILD_ID:
        return
    config = await bot.db.get_config(guild.id)
    category = guild.get_channel(config.get("family_category_id") or 0)
    if not isinstance(category, discord.CategoryChannel):
        raise ValueError("Не найдена настроенная категория COLOMBO • СОСТАВ.")
    if any(not guild.get_role(role_id) for role_id in TIER_ROLES.values()):
        raise ValueError("Не найдены указанные роли тиров.")
    reviewer_role = guild.get_role(TIERCHECK_ROLE_ID)
    if not reviewer_role:
        raise ValueError("Не найдена роль tiercheck.")
    family = [reviewer_role] + configured_roles(
        guild,
        config,
        STAFF_KEYS + ("colombo_role_id", "accepted_role_id", "main_role_id"),
    )
    ow = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False),
        guild.me: discord.PermissionOverwrite(
            view_channel=True,
            send_messages=True,
            embed_links=True,
            read_message_history=True,
            create_private_threads=True,
            send_messages_in_threads=True,
            manage_threads=True,
        ),
    }
    for r in family:
        ow[r] = discord.PermissionOverwrite(
            view_channel=True,
            send_messages=False,
            read_message_history=True,
            send_messages_in_threads=True,
        )
    channels = await guild.fetch_channels()
    for tier in TIER_ROLES:
        name = f"повышение-на-тир-{tier}"
        topic = tier_channel_topic(tier, bot.user.id, guild.id)
        matches = [
            c
            for c in channels
            if isinstance(c, discord.TextChannel)
            and (c.topic == topic or (c.category_id == category.id and c.name == name))
        ]
        if len(matches) > 1:
            raise ValueError(f"Найдены дубли канала {name}.")
        channel = (
            matches[0]
            if matches
            else await guild.create_text_channel(
                name, category=category, topic=topic, overwrites=ow
            )
        )
        if matches and (
            channel.category_id != category.id
            or channel.topic != topic
            or channel.overwrites != ow
        ):
            await channel.edit(category=category, topic=topic, overwrites=ow)
        message = None
        async for m in channel.history(limit=50):
            if m.author.id == bot.user.id and any(
                getattr(c, "custom_id", None) == "colombo:tier:apply"
                for row in m.components
                for c in row.children
            ):
                message = m
                break
        if message:
            await edit_if_changed(
                message,
                embed=panel(tier),
                view=TierPanelView(bot),
                allowed_mentions=discord.AllowedMentions.none(),
            )
        else:
            await channel.send(
                embed=panel(tier),
                view=TierPanelView(bot),
                allowed_mentions=discord.AllowedMentions.none(),
            )
        print(
            f"Tier channel ready | guild={guild.id} | tier={tier} | channel={channel.id}"
        )

    await sync_reviewers(bot, guild)


async def sync_reviewers(bot, guild, member=None):
    if guild.id != GUILD_ID:
        return
    if not hasattr(bot, "_tier_sync_tasks"):
        bot._tier_sync_tasks = {}
    key = (guild.id, member.id if member else None)
    existing = bot._tier_sync_tasks.get(key)
    if existing:
        return await asyncio.shield(existing)

    async def run():
        try:
            return await _sync_reviewers(bot, guild, member)
        finally:
            bot._tier_sync_tasks.pop(key, None)

    task = asyncio.create_task(run())
    bot._tier_sync_tasks[key] = task
    return await asyncio.shield(task)


async def _sync_reviewers(bot, guild, member=None):
    if guild.id != GUILD_ID:
        return
    role = guild.get_role(TIERCHECK_ROLE_ID)
    if not role:
        return
    if member is None and not guild.chunked:
        await guild.chunk(cache=True)
    reviewers = [member] if member else list(role.members)
    reviewers = [m for m in reviewers if not m.bot and m.get_role(TIERCHECK_ROLE_ID)]
    rows = await bot.db.tier_threads(guild.id)
    added = 0
    failed = 0
    for row in rows:
        async with bot.operation_locks[("tier_member", guild.id, row["member_id"])]:
            try:
                thread = await guild.fetch_channel(row["thread_id"])
                if not isinstance(thread, discord.Thread) or not thread.parent:
                    continue
                valid = {
                    tier_channel_topic(tier, bot.user.id, guild.id)
                    for tier in TIER_ROLES
                }
                if thread.parent.topic not in valid:
                    continue
                if member is None:
                    members = {m.id for m in await thread.fetch_members()}
                else:
                    try:
                        await thread.fetch_member(member.id)
                        members = {member.id}
                    except discord.NotFound:
                        members = set()
                missing = [
                    m
                    for m in reviewers
                    if m.id not in members
                    and (guild.get_member(m.id) or m).get_role(TIERCHECK_ROLE_ID)
                ]
                if not missing:
                    continue
                archived, locked = thread.archived, thread.locked
                try:
                    if archived:
                        await thread.edit(
                            archived=False,
                            reason="Colombo: восстановление доступа tiercheck",
                        )
                    for m in missing:
                        await thread.add_user(m)
                        added += 1
                finally:
                    if archived:
                        await thread.edit(
                            archived=True,
                            locked=locked,
                            reason="Colombo: сохранение архива заявки",
                        )
            except discord.NotFound:
                continue
            except discord.DiscordException as exc:
                failed += 1
                print(
                    f'Tiercheck access error | guild={guild.id} | thread={row["thread_id"]}: {exc}'
                )
    print(
        f"Tiercheck access restored | guild={guild.id} | applications={len(rows)} | added={added} | failed={failed}"
    )
    return added, failed
