"""Tier applications: explicit roles, private review and resumable role changes."""
import json
import discord
from .interactions import SafeModal,SafeView,private_thread
from .roles import STAFF_KEYS,configured_roles
from .ui import base_embed
GUILD_ID=1503854540116721747
TIERCHECK_ROLE_ID=1549336543527960636
TIER_ROLES={1:1549336886886015046,2:1549337062497452183,3:1549337206139785266}
KINDS=('tier_1','tier_2','tier_3')

async def can_review(bot,i):
    return i.guild_id==GUILD_ID and isinstance(i.user,discord.Member) and bool(i.user.get_role(TIERCHECK_ROLE_ID))

def panel(tier):
    return base_embed(f'Повышение на тир {tier}','Прикрепи ссылки на откаты и расскажи, зачем тебе нужен тир.\nРассматривают **tiercheck**. При одобрении другие тиры заменяются выбранным.',0xA82D40)

async def award_tier(guild,member,tier):
    if guild.id!=GUILD_ID or tier not in TIER_ROLES:raise ValueError('Неизвестный сервер или тир.')
    roles={n:guild.get_role(rid) for n,rid in TIER_ROLES.items()}
    if not guild.me.guild_permissions.manage_roles:raise ValueError('Боту нужно право «Управлять ролями».')
    for r in roles.values():
        if not r or r.managed or r.is_default() or r>=guild.me.top_role:raise ValueError('Подними роль бота выше всех трёх тиров.')
    if not member.get_role(roles[tier].id):await member.add_roles(roles[tier],reason=f'Colombo: одобрен тир {tier}')
    old=[r for n,r in roles.items() if n!=tier and member.get_role(r.id)]
    if old:await member.remove_roles(*old,reason=f'Colombo: замена на тир {tier}')
    fresh=await guild.fetch_member(member.id)
    if {r.id for r in fresh.roles}&set(TIER_ROLES.values())!={TIER_ROLES[tier]}:raise ValueError('Discord не подтвердил замену. Повтори одобрение.')

class TierModal(SafeModal):
    identity=discord.ui.TextInput(label='Ник / возраст / статик',placeholder='Nickname / 23 / 4949',max_length=150)
    gg=discord.ui.TextInput(label='Откаты с ГГ',placeholder='Откаты с ГГ (спешики + сайга, от 8 людей в лобаке, онли 18 и 19 сервер)',style=discord.TextStyle.paragraph,max_length=900)
    kapt=discord.ui.TextInput(label='Откаты с Каптов',placeholder='Ссылки на откаты с Каптов',style=discord.TextStyle.paragraph,max_length=900)
    def __init__(self,bot,tier):
        super().__init__(title=f'Заявка на тир {tier}',timeout=300);self.bot=bot;self.tier=tier
        mcl_required=tier in (1,2)
        self.mcl=discord.ui.TextInput(label='Откаты с МЦЛ',placeholder='Ссылки на откаты с МЦЛ' if mcl_required else 'Ссылки, если есть откаты',style=discord.TextStyle.paragraph,required=mcl_required,max_length=900)
        self.add_item(self.mcl)
        self.purpose=discord.ui.TextInput(label='Для чего тебе нужен тир?',style=discord.TextStyle.paragraph,max_length=600)
        self.add_item(self.purpose)
    async def on_submit(self,i):
        if i.guild_id!=GUILD_ID or not isinstance(i.user,discord.Member) or not await self.bot.is_family_member(i.user):return await i.response.send_message('Заявки доступны участникам Colombo.',ephemeral=True)
        await i.response.defer(ephemeral=True)
        async with self.bot.operation_locks[('tier_member',i.guild_id,i.user.id)]:
            existing=await self.bot.db._one("SELECT thread_id FROM progress_requests WHERE guild_id=? AND member_id=? AND kind IN ('tier_1','tier_2','tier_3') AND status IN ('pending','applying')",(i.guild_id,i.user.id))
            if existing:return await i.followup.send(f"У тебя уже есть заявка: <#{existing['thread_id']}>.",ephemeral=True)
            if (getattr(i.channel,'topic',None) or '')!=f'colombo:tier:{self.tier}:{self.bot.user.id}:{i.guild_id}':raise ValueError('Открой актуальный канал тира.')
            if not i.guild.get_role(TIER_ROLES[self.tier]):raise ValueError('Роль тира удалена. Сообщи High.')
            reviewer_role=i.guild.get_role(TIERCHECK_ROLE_ID)
            if not reviewer_role:raise ValueError('Не найдена роль tiercheck.')
            thread=await private_thread(i.channel,i.user,[reviewer_role],f'тир-{self.tier}-{i.user.display_name}')
            fields=[('Ник / возраст / статик',str(self.identity)),('Откаты с ГГ',str(self.gg)),('Откаты с Каптов',str(self.kapt)),('Откаты с МЦЛ',str(self.mcl) or 'Не приложены'),('Для чего нужен тир',str(self.purpose))]
            try:
                async with self.bot.db.lock:
                    cur=await self.bot.db.conn.execute('INSERT INTO progress_requests(guild_id,member_id,kind,thread_id,details,created_at) VALUES (?,?,?,?,?,?)',(i.guild_id,i.user.id,f'tier_{self.tier}',thread.id,json.dumps(fields,ensure_ascii=False),self.bot.now_iso()));rid=cur.lastrowid;await self.bot.db.conn.commit()
            except Exception:
                await thread.delete(reason='Colombo: ошибка сохранения заявки');raise
            e=base_embed(f'Заявка #{rid} • тир {self.tier}',f'Участник: {i.user.mention}',0xD5A43A)
            for name,value in fields:e.add_field(name=name,value=value,inline=False)
            try:await thread.send(embed=e,view=TierReviewView(self.bot),allowed_mentions=discord.AllowedMentions.none())
            except Exception:
                async with self.bot.db.lock:
                    await self.bot.db.conn.execute("UPDATE progress_requests SET status='failed' WHERE id=?",(rid,));await self.bot.db.conn.commit()
                raise
            await i.followup.send(f'Заявка отправлена: {thread.mention}',ephemeral=True)
            # Notify in the parent channel; application details stay in the private thread.
            await i.channel.send(f'<@&{TIERCHECK_ROLE_ID}> · Новая заявка на **тир {self.tier}**: {thread.mention}',allowed_mentions=discord.AllowedMentions(everyone=False,users=False,roles=[discord.Object(id=TIERCHECK_ROLE_ID)],replied_user=False))

class TierPanelView(SafeView):
    def __init__(self,bot):super().__init__(timeout=None);self.bot=bot
    @discord.ui.button(label='Подать заявку',emoji='📝',style=discord.ButtonStyle.success,custom_id='colombo:tier:apply')
    async def apply(self,i,_):
        parts=(getattr(i.channel,'topic',None) or '').split(':')
        if i.guild_id!=GUILD_ID or len(parts)!=5 or parts[:2]!=['colombo','tier'] or parts[2] not in ('1','2','3') or parts[3:]!=[str(self.bot.user.id),str(i.guild_id)]:return await i.response.send_message('Канал тира не настроен.',ephemeral=True)
        await i.response.send_modal(TierModal(self.bot,int(parts[2])))

class TierDecision(SafeModal):
    reason=discord.ui.TextInput(label='Комментарий / причина отказа',style=discord.TextStyle.paragraph,max_length=700,min_length=3)
    def __init__(self,bot,accepted):super().__init__(title='Одобрить тир' if accepted else 'Причина отказа',timeout=300);self.bot=bot;self.accepted=accepted
    async def on_submit(self,i):
        if not await can_review(self.bot,i):return await i.response.send_message('Рассматривают только участники с ролью tiercheck.',ephemeral=True)
        reason=str(self.reason).strip()
        if len(reason)<3:return await i.response.send_message('Напиши комментарий не короче трёх символов.',ephemeral=True)
        await i.response.defer(ephemeral=True)
        row=await self.bot.db._one('SELECT * FROM progress_requests WHERE guild_id=? AND thread_id=?',(i.guild_id,i.channel_id))
        if not row or row['kind'] not in KINDS:return await i.followup.send('Заявка не найдена.',ephemeral=True)
        async with self.bot.operation_locks[('tier_member',i.guild_id,row['member_id'])]:
            row=await self.bot.db._one('SELECT * FROM progress_requests WHERE id=?',(row['id'],))
            if row['status'] not in ('pending','applying'):return await i.followup.send('Заявка уже закрыта.',ephemeral=True)
            if row['member_id']==i.user.id:return await i.followup.send('Свою заявку рассматривать нельзя.',ephemeral=True)
            if row['status']=='applying' and not self.accepted:return await i.followup.send('Замена роли уже началась. Заверши одобрение.',ephemeral=True)
            tier=int(row['kind'][-1])
            if self.accepted:
                member=await i.guild.fetch_member(row['member_id'])
                if not await self.bot.is_family_member(member):return await i.followup.send('Игрок больше не состоит в Colombo.',ephemeral=True)
                async with self.bot.db.lock:
                    await self.bot.db.conn.execute("UPDATE progress_requests SET status='applying',handled_by=?,decision=? WHERE id=?",(i.user.id,reason,row['id']));await self.bot.db.conn.commit()
                try:await award_tier(i.guild,member,tier)
                except (discord.DiscordException,ValueError) as exc:return await i.followup.send(f'Замена тира не завершена: {exc} Исправь права и повтори одобрение.',ephemeral=True)
            status='approved' if self.accepted else 'rejected'
            e=base_embed(f'✅ Тир {tier} одобрен' if self.accepted else f'❌ Отказ в тире {tier}',f"Участник: <@{row['member_id']}>\nРассмотрел: {i.user.mention}\n"+('Комментарий: ' if self.accepted else 'Причина отказа: ')+discord.utils.escape_markdown(reason),0x3BAA72 if self.accepted else 0xD64045)
            await i.channel.send(embed=e,allowed_mentions=discord.AllowedMentions.none())
            async with self.bot.db.lock:
                await self.bot.db.conn.execute('UPDATE progress_requests SET status=?,handled_by=?,decision=? WHERE id=?',(status,i.user.id,reason,row['id']));await self.bot.db.conn.commit()
            dm=True
            try:
                member=await i.guild.fetch_member(row['member_id']);await member.send(embed=e,allowed_mentions=discord.AllowedMentions.none())
            except discord.DiscordException:dm=False
            await i.followup.send('Решение сохранено. '+('Игроку отправлено личное сообщение.' if dm else 'Личные сообщения закрыты или недоступны; результат оставлен в ветке.'),ephemeral=True)
            await i.channel.edit(archived=True,locked=True)

class TierReviewView(SafeView):
    def __init__(self,bot):super().__init__(timeout=None);self.bot=bot
    async def interaction_check(self,i):
        if not await can_review(self.bot,i):await i.response.send_message('Рассматривают только участники с ролью tiercheck.',ephemeral=True);return False
        return True
    @discord.ui.button(label='Одобрить',style=discord.ButtonStyle.success,custom_id='colombo:tier:approve')
    async def approve(self,i,_):await i.response.send_modal(TierDecision(self.bot,True))
    @discord.ui.button(label='Отказать',style=discord.ButtonStyle.danger,custom_id='colombo:tier:reject')
    async def reject(self,i,_):await i.response.send_modal(TierDecision(self.bot,False))

async def install(bot,guild):
    if guild.id!=GUILD_ID:return
    cfg=await bot.db.get_config(guild.id);category=guild.get_channel(cfg.get('family_category_id') or 0)
    if not isinstance(category,discord.CategoryChannel):raise ValueError('Не найдена настроенная категория COLOMBO • СОСТАВ.')
    if any(not guild.get_role(rid) for rid in TIER_ROLES.values()):raise ValueError('Не найдены указанные роли тиров.')
    reviewer_role=guild.get_role(TIERCHECK_ROLE_ID)
    if not reviewer_role:raise ValueError('Не найдена роль tiercheck.')
    family=[reviewer_role]+configured_roles(guild,cfg,STAFF_KEYS+('colombo_role_id','accepted_role_id','main_role_id'))
    ow={guild.default_role:discord.PermissionOverwrite(view_channel=False),guild.me:discord.PermissionOverwrite(view_channel=True,send_messages=True,embed_links=True,read_message_history=True,create_private_threads=True,send_messages_in_threads=True,manage_threads=True)}
    for r in family:ow[r]=discord.PermissionOverwrite(view_channel=True,send_messages=False,read_message_history=True,send_messages_in_threads=True)
    channels=await guild.fetch_channels()
    for tier in TIER_ROLES:
        name=f'повышение-на-тир-{tier}';topic=f'colombo:tier:{tier}:{bot.user.id}:{guild.id}'
        matches=[c for c in channels if isinstance(c,discord.TextChannel) and (c.topic==topic or (c.category_id==category.id and c.name==name))]
        if len(matches)>1:raise ValueError(f'Найдены дубли канала {name}.')
        ch=matches[0] if matches else await guild.create_text_channel(name,category=category,topic=topic,overwrites=ow)
        if matches:await ch.edit(category=category,topic=topic,overwrites=ow)
        message=None
        async for m in ch.history(limit=50):
            if m.author.id==bot.user.id and any(getattr(c,'custom_id',None)=='colombo:tier:apply' for row in m.components for c in row.children):message=m;break
        if message:await message.edit(embed=panel(tier),view=TierPanelView(bot),allowed_mentions=discord.AllowedMentions.none())
        else:await ch.send(embed=panel(tier),view=TierPanelView(bot),allowed_mentions=discord.AllowedMentions.none())
        print(f'Tier channel ready | guild={guild.id} | tier={tier} | channel={ch.id}')

    # Existing pending applications must also be accessible to the new reviewers.
    if not guild.chunked:await guild.chunk(cache=True)
    pending=await bot.db._all("SELECT thread_id FROM progress_requests WHERE guild_id=? AND kind IN ('tier_1','tier_2','tier_3') AND status IN ('pending','applying')",(guild.id,))
    for row in pending:
        try:
            thread=await guild.fetch_channel(row['thread_id'])
            if not isinstance(thread,discord.Thread) or not thread.parent or not (thread.parent.topic or '').startswith(f'colombo:tier:'):continue
            members={m.id for m in await thread.fetch_members()}
            for member in reviewer_role.members:
                if not member.bot and member.id not in members:await thread.add_user(member)
        except discord.NotFound:continue
    print(f'Tiercheck access ready | guild={guild.id} | pending={len(pending)}')
