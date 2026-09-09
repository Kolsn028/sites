"""Private contract and promotion workflows. Evidence is checked by staff."""
import discord
from .interactions import SafeView, SafeModal, private_thread, serialized
from .roles import configured_roles, HIGH_KEYS, STAFF_KEYS, notify_assistants, notify_recruiters
from .ui import base_embed

RULES = ('**1 → 3 ранг**\n'
         '• 10 помощей по контрактам со скриншотами.\n'
         '• 10 скриншотов с разных каптов.\n'
         '• 10 дней в семье.\n'
         '• Пройденный обзвон у рекрутера и активность.\n\n'
         '**2 ранг пропускаем.** После 3 ранга — отдельные заявки и обзвоны.\n'
         'Прикрепи доказательства в приватной ветке. Руководство проверяет каждый пункт.\n'
         'После одобрения бот заменит -Novizio- на main (3 ранг). Права останутся теми же.')


async def award_main(bot, guild, member):
    cfg = await bot.db.get_config(guild.id)
    main = guild.get_role(cfg.get('main_role_id') or 0)
    novice = guild.get_role(cfg.get('accepted_role_id') or 0)
    if not main or not novice or main.managed or main >= guild.me.top_role or novice >= guild.me.top_role:
        raise ValueError('Проверь /setup и подними роль бота выше main и -Novizio-. Повышение пока не подтверждено.')
    # Add first so a failed removal never leaves the member without family access.
    await member.add_roles(main, reason='Colombo: одобрено повышение до 3 ранга')
    if member.get_role(novice.id):
        await member.remove_roles(novice, reason='Colombo: Novizio заменена на main')


def contract_panel_embed():
    return base_embed('🟠 Активация контрактов',
        'Нажми **Оформить контракт**, укажи название и выбери: активация или помощь.\n'
        'Прикрепи скриншот в своей приватной ветке. **Recruit- / Ass.Deputy / Deputy Leader** проверит отчёт.\n'
        'Для повышения учитывается помощь, а не просто активация.', 0xE58A35)


def promotion_panel_embed():
    return base_embed('😎 Система повышения', RULES, 0xD5AD65)


async def submit(bot, i, kind, details):
    if not isinstance(i.user, discord.Member) or not await bot.is_family_member(i.user):
        return await i.response.send_message('Доступно участникам семьи.', ephemeral=True)
    await i.response.defer(ephemeral=True, thinking=True)
    async with bot.operation_locks[('progress_open', i.guild_id, i.user.id)]:
        cfg = await bot.db.get_config(i.guild_id)
        parent = i.guild.get_channel(cfg.get(f'{kind}_panel_channel_id') or 0)
        if not isinstance(parent, discord.TextChannel):
            raise ValueError('Сначала настрой сервер через /setup.')
        existing = await bot.db._one('SELECT * FROM progress_requests WHERE guild_id=? AND member_id=? AND kind=? AND status=\'pending\'', (i.guild_id, i.user.id, kind))
        if existing:
            return await i.followup.send(f"У тебя уже есть открытая ветка: <#{existing['thread_id']}>.", ephemeral=True)
        thread = await private_thread(parent, i.user, configured_roles(i.guild, cfg, STAFF_KEYS),
                                      f'{"контракт" if kind == "contract" else "повышение"}-{i.user.display_name}')
        try:
            async with bot.db.lock:
                await bot.db.conn.execute('INSERT INTO progress_requests(guild_id,member_id,kind,thread_id,details,created_at) VALUES (?,?,?,?,?,?)',
                    (i.guild_id, i.user.id, kind, thread.id, details, bot.now_iso()))
                await bot.db.conn.commit()
            embed = base_embed('🟡 Проверка контракта' if kind == 'contract' else '🟡 Заявка на повышение',
                f'Участник: {i.user.mention}\n{details}\n\n**Прикрепи скриншоты в эту ветку.**\n'
                + ('Проверяют: Recruit- и выше. ' if kind == 'contract' else 'Повышение до 3 ранга проверяет Recruit- и выше. ') + 'Самостоятельное одобрение запрещено.')
            if kind == 'promotion':
                embed.add_field(name='Что проверяет руководство', value='10 помощей • 10 разных каптов • 10 дней в семье • обзвон • активность', inline=False)
            await thread.send(embed=embed, view=ProgressReviewView(bot), allowed_mentions=discord.AllowedMentions.none())
        except Exception:
            async with bot.db.lock:
                await bot.db.conn.execute("DELETE FROM progress_requests WHERE thread_id=?", (thread.id,))
                await bot.db.conn.commit()
            await thread.delete(reason='Colombo: не удалось открыть заявку')
            raise
        notifier = notify_recruiters if kind == 'promotion' else notify_assistants
        await notifier(thread, i.guild, cfg, base_embed('🔔 Нужна проверка', 'Новая заявка. Доказательства — в этой ветке.'))
        await i.followup.send(f'Готово: {thread.mention}. Загрузи сюда доказательства.', ephemeral=True)


class ContractModal(SafeModal, title='Контракт • Colombo'):
    name = discord.ui.TextInput(label='Название контракта', max_length=120)
    mode = discord.ui.TextInput(label='Активация или помощь?', placeholder='активация / помощь', max_length=20)
    event = discord.ui.TextInput(label='Дата / время / номер события', max_length=100)
    def __init__(self, bot):
        super().__init__(); self.bot = bot
    async def on_submit(self, i):
        mode = str(self.mode).strip().lower()
        if mode not in ('активация', 'помощь'):
            return await i.response.send_message('В поле типа напиши «активация» или «помощь».', ephemeral=True)
        await submit(self.bot, i, 'contract', f'**{mode.capitalize()}** • {self.name}\nСобытие: {self.event}')


class PromotionModal(SafeModal, title='Повышение • 1 → 3'):
    contracts = discord.ui.TextInput(label='10 помощей: ссылки на отчёты', style=discord.TextStyle.paragraph, max_length=1000)
    capts = discord.ui.TextInput(label='10 разных каптов: даты / ссылки', style=discord.TextStyle.paragraph, max_length=1000)
    since = discord.ui.TextInput(label='Дата вступления в семью', max_length=60)
    interview = discord.ui.TextInput(label='Кто провёл обзвон и когда?', max_length=150)
    activity = discord.ui.TextInput(label='Твоя активность в семье', style=discord.TextStyle.paragraph, max_length=300)
    def __init__(self, bot):
        super().__init__(); self.bot = bot
    async def on_submit(self, i):
        await submit(self.bot, i, 'promotion', f'**Контракты:** {self.contracts}\n**Капты:** {self.capts}\n'
                     f'**В семье с:** {self.since}\n**Обзвон:** {self.interview}\n**Активность:** {self.activity}')


class ContractPanelView(SafeView):
    def __init__(self, bot):
        super().__init__(timeout=None); self.bot = bot
    @discord.ui.button(label='Оформить контракт', emoji='🟠', style=discord.ButtonStyle.primary, custom_id='colombo:contract:open')
    async def open(self, i, _):
        await i.response.send_modal(ContractModal(self.bot))


class PromotionPanelView(SafeView):
    def __init__(self, bot):
        super().__init__(timeout=None); self.bot = bot
    @discord.ui.button(label='Подать на 3 ранг', emoji='📈', style=discord.ButtonStyle.success, custom_id='colombo:promotion:open')
    async def open(self, i, _):
        await i.response.send_modal(PromotionModal(self.bot))


class DecisionModal(SafeModal, title='Решение по заявке'):
    reason = discord.ui.TextInput(label='Что проверено / причина отказа', style=discord.TextStyle.paragraph, max_length=700)
    checklist = discord.ui.TextInput(label='Для повышения: 10/10/10/обзвон/активность', placeholder='После проверки напиши: подтверждаю', required=False, max_length=40)
    def __init__(self, bot, thread_id, accepted):
        super().__init__(); self.bot=bot; self.thread_id=thread_id; self.accepted=accepted
    async def on_submit(self, i):
        if not isinstance(i.user, discord.Member):
            return await i.response.send_message('Доступно только на сервере.', ephemeral=True)
        await i.response.defer(ephemeral=True, thinking=True)
        async with self.bot.operation_locks[('progress_decision', i.guild_id, self.thread_id)]:
            row = await self.bot.db._one('SELECT * FROM progress_requests WHERE guild_id=? AND thread_id=?', (i.guild_id, self.thread_id))
            if not row or row['status'] != 'pending':
                return await i.followup.send('Заявка уже закрыта или не найдена.', ephemeral=True)
            allowed = await self.bot.can_promote(i.user) if row['kind'] == 'promotion' else await self.bot.is_high_staff(i.user)
            if not allowed:
                return await i.followup.send('Проверка доступна Recruit- и всем старшим ролям.', ephemeral=True)
            if row['member_id'] == i.user.id:
                return await i.followup.send('Свою заявку проверять нельзя.', ephemeral=True)
            member = i.guild.get_member(row['member_id'])
            if self.accepted and (not member or not await self.bot.is_family_member(member)):
                return await i.followup.send('Автор больше не состоит в семье.', ephemeral=True)
            if self.accepted and row['kind'] == 'promotion' and str(self.checklist).strip().lower() != 'подтверждаю':
                return await i.followup.send('Проверь все пять условий и напиши «подтверждаю».', ephemeral=True)
            if self.accepted and row['kind'] == 'contract':
                evidence = False
                async for msg in i.channel.history(limit=None):
                    if msg.author.id == row['member_id'] and any((a.content_type or '').startswith('image/') for a in msg.attachments):
                        evidence = True; break
                if not evidence:
                    return await i.followup.send('Автор ещё не прикрепил скриншот контракта в эту ветку.', ephemeral=True)
            if self.accepted and row['kind'] == 'promotion':
                await award_main(self.bot, i.guild, member)
            status = 'approved' if self.accepted else 'rejected'
            # Publish first; if Discord is unavailable keep the request actionable.
            await i.channel.send(embed=base_embed('✅ Подтверждено' if self.accepted else '❌ Отклонено',
                f"Участник: <@{row['member_id']}>\nПроверил: {i.user.mention}\n{self.reason}"
                + ('\n**3 ранг: main.** Роль -Novizio- заменена; права сохранены.' if self.accepted and row['kind']=='promotion' else ''),
                0x3BAA72 if self.accepted else 0xD64045), allowed_mentions=discord.AllowedMentions.none())
            async with self.bot.db.lock:
                await self.bot.db.conn.execute('UPDATE progress_requests SET status=?,handled_by=?,decision=? WHERE thread_id=?',
                    (status,i.user.id,str(self.reason),self.thread_id))
                await self.bot.db.conn.commit()
            await i.followup.send('Решение сохранено.', ephemeral=True)
            await i.channel.edit(archived=True, locked=True)


class ProgressReviewView(SafeView):
    def __init__(self, bot):
        super().__init__(timeout=None); self.bot=bot
    async def decide(self, i, accepted):
        row = await self.bot.db._one('SELECT kind FROM progress_requests WHERE guild_id=? AND thread_id=?', (i.guild_id, i.channel_id))
        if not row or not isinstance(i.user, discord.Member):
            return await i.response.send_message('Заявка не найдена.', ephemeral=True)
        allowed = await self.bot.can_promote(i.user) if row['kind'] == 'promotion' else await self.bot.is_high_staff(i.user)
        if not allowed:
            return await i.response.send_message('Нет роли, ответственной за это направление.', ephemeral=True)
        await i.response.send_modal(DecisionModal(self.bot, i.channel_id, accepted))
    @discord.ui.button(label='Подтвердить', style=discord.ButtonStyle.success, custom_id='colombo:progress:approve')
    async def approve(self, i, _): await self.decide(i, True)
    @discord.ui.button(label='Отклонить', style=discord.ButtonStyle.danger, custom_id='colombo:progress:reject')
    async def reject(self, i, _): await self.decide(i, False)
