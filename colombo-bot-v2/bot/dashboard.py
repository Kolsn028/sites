"""Private management and self-service request status, with permission checks on every click."""
import discord
from .interactions import SafeView
from .roles import may_manage_recruiters,HIGH_KEYS,configured_roles
from .ui import base_embed

STATUS={'pending':'⏳ Ожидает проверки','interview':'📞 Обзвон','accepted':'✅ Принят','rejected':'❌ Отказ','approved':'✅ Одобрено','return_pending':'⏳ Возвращение на проверке','returned':'✅ Вернулся','pending_review':'⏳ Проверяется','pending_classification':'Выбери тип отчёта','applying':'⏳ Оформляется','restoring':'⏳ Возвращение оформляется','failed':'⚠️ Не отправлено'}
LABELS={'all':'Вся очередь','application':'Заявки в семью','vacation':'Отдых','contract':'Контракты','promotion':'Повышения','report':'Отчёты'}

async def high(bot,i):
    return isinstance(i.user,discord.Member) and may_manage_recruiters(i.user,await bot.db.get_config(i.guild_id))

async def request_rows(db,gid,member_id=None,pending=False,kind='all',page=0):
    # Owner filtering lives in every branch, never only in the UI.
    parts=[];args=[]
    specs=[('applications','application','applicant_id','thread_id','rejection_reason'),('vacations','vacation','member_id','thread_id','NULL'),('progress_requests',None,'member_id','thread_id','decision'),('activity_submissions','report','member_id','case_channel_id','note')]
    for table,label,owner,channel,reason in specs:
        category="kind" if label is None else "'"+label+"'"
        actor='COALESCE(assigned_to,handled_by)' if table=='applications' else 'handled_by'
        if table=='activity_submissions': actor='handled_by'
        where='guild_id=?';params=[gid]
        if member_id is not None: where+=f' AND {owner}=?';params.append(member_id)
        if pending: where+=" AND status IN ('pending','interview','return_pending','pending_review','pending_classification')"
        parts.append(f'SELECT id,{category} kind,{owner} member_id,status,{channel} channel_id,{actor} actor,{reason} reason,created_at FROM {table} WHERE {where}')
        args+=params
    union=' UNION ALL '.join(parts)
    filter_sql='' if kind=='all' else ' WHERE kind=?'
    if kind!='all':args.append(kind)
    total=await db._one('SELECT COUNT(*) n FROM ('+union+')'+filter_sql,args)
    pages=max(1,(total['n']+7)//8);page=max(0,min(page,pages-1))
    rows=await db._all('SELECT * FROM ('+union+')'+filter_sql+' ORDER BY created_at DESC,kind,id DESC LIMIT 8 OFFSET ?',[*args,page*8])
    return rows,total['n'],page,pages

class RequestsView(SafeView):
    def __init__(self,bot,viewer_id,own=False,kind='all',page=0):
        super().__init__(timeout=600);self.bot=bot;self.viewer_id=viewer_id;self.own=own;self.kind=kind;self.page=page
        self.add_item(RequestFilter(kind))
    async def interaction_check(self,i):
        if i.user.id!=self.viewer_id or (not self.own and not await high(self.bot,i)):
            await i.response.send_message('Эта панель недоступна.',ephemeral=True);return False
        return True
    async def update(self,i):
        await i.response.defer()
        embed,view=await request_card(self.bot,i,self.own,self.kind,self.page)
        await i.edit_original_response(embed=embed,view=view,allowed_mentions=discord.AllowedMentions.none())
    @discord.ui.button(label='Назад',row=1)
    async def previous(self,i,_):self.page-=1;await self.update(i)
    @discord.ui.button(label='Далее',row=1)
    async def next(self,i,_):self.page+=1;await self.update(i)
    @discord.ui.button(label='Обновить',emoji='🔄',row=1)
    async def refresh(self,i,_):await self.update(i)

class RequestFilter(discord.ui.Select):
    def __init__(self,kind):
        super().__init__(placeholder='Раздел',row=0,options=[discord.SelectOption(label=('Все обращения' if k=='all' else v),value=k,default=k==kind) for k,v in LABELS.items()])
    async def callback(self,i):self.view.kind=self.values[0];self.view.page=0;await self.view.update(i)

async def request_card(bot,i,own,kind='all',page=0):
    rows,total,page,pages=await request_rows(bot.db,i.guild_id,i.user.id if own else None,not own,kind,page)
    e=base_embed('📬 Мои заявки' if own else '📋 Очередь проверок',f'Всего: **{total}**. Выбери раздел ниже.\n'+('Здесь видны только твои обращения.' if own else 'Доступ к веткам определяется их текущими правами.'))
    for r in rows:
        title=f"{LABELS.get(r['kind'],r['kind'])} #{r['id']}"
        text=STATUS.get(r['status'],r['status'])
        if not own:text+=f" · <@{r['member_id']}>"
        text+='\nОтветственный: '+(f"<@{r['actor']}>" if r['actor'] else 'ещё не назначен')
        if own and r['status']=='rejected' and r['reason']:text+='\nПричина: '+discord.utils.escape_markdown(r['reason'])[:350]
        if r['channel_id']:text+=f"\n[Открыть обращение](https://discord.com/channels/{i.guild_id}/{r['channel_id']})"
        e.add_field(name=title,value=text,inline=False)
    if not rows:e.description+='\nОбращений нет.'
    e.set_footer(text=f'Страница {page+1}/{pages}')
    view=RequestsView(bot,i.user.id,own,kind,page);view.previous.disabled=page==0;view.next.disabled=page+1>=pages
    return e,view

async def open_requests(bot,i,own=False,kind='all'):
    if not own and not await high(bot,i):return await i.response.send_message('Очередь доступна High и выше.',ephemeral=True)
    await i.response.defer(ephemeral=True)
    e,v=await request_card(bot,i,own,kind)
    await i.followup.send(embed=e,view=v,ephemeral=True,allowed_mentions=discord.AllowedMentions.none())

class PlayerSearch(discord.ui.UserSelect):
    def __init__(self,bot):super().__init__(placeholder='Найди игрока по нику');self.bot=bot
    async def callback(self,i):
        from .profiles import open_profile
        await open_profile(self.bot,i,self.values[0].id)

class ManagementView(SafeView):
    def __init__(self,bot):super().__init__(timeout=None);self.bot=bot
    async def interaction_check(self,i):
        if not await high(self.bot,i):
            await i.response.send_message('Управление доступно только High, Deputy Leader и Leader.',ephemeral=True);return False
        return True
    @discord.ui.button(label='Очередь проверок',emoji='📋',custom_id='colombo:hub:queue')
    async def queue(self,i,_):await open_requests(self.bot,i)
    @discord.ui.button(label='Заявки',emoji='📥',custom_id='colombo:hub:applications')
    async def applications(self,i,_):await open_requests(self.bot,i,kind='application')
    @discord.ui.button(label='Отдых',emoji='🌴',custom_id='colombo:hub:vacations')
    async def vacations(self,i,_):await open_requests(self.bot,i,kind='vacation')
    @discord.ui.button(label='МП',emoji='📅',custom_id='colombo:hub:events',row=1)
    async def events(self,i,_):
        from .events import EVENTS
        cfg=await self.bot.db.get_config(i.guild_id);v=SafeView(timeout=180)
        for kind,(_,name,_) in EVENTS.items():
            if cfg.get(f'{kind}_panel_channel_id'):v.add_item(discord.ui.Button(label=name,url=f"https://discord.com/channels/{i.guild_id}/{cfg[kind+'_panel_channel_id']}"))
        await i.response.send_message('Открой нужный канал и нажми «Создать сбор».',view=v,ephemeral=True)
    @discord.ui.button(label='Найти игрока',emoji='🔎',custom_id='colombo:hub:players',row=1)
    async def players(self,i,_):
        v=SafeView(timeout=180);v.add_item(PlayerSearch(self.bot));await i.response.send_message('Выбери игрока — откроется его карточка.',view=v,ephemeral=True)
    @discord.ui.button(label='Статистика',emoji='🏆',custom_id='colombo:hub:stats',row=1)
    async def stats(self,i,_):
        v=SafeView(timeout=180);v.add_item(StatsPeriod(self.bot));await i.response.send_message('Выбери период рейтинга рекрутов.',view=v,ephemeral=True)

class StatsPeriod(discord.ui.Select):
    def __init__(self,bot):
        super().__init__(placeholder='Период',options=[discord.SelectOption(label=l,value=str(n)) for n,l in [(7,'Неделя'),(30,'Месяц'),(0,'Всё время')]]);self.bot=bot
    async def callback(self,i):
        if not await high(self.bot,i):return await i.response.send_message('Только High и выше.',ephemeral=True)
        from .enhancements import recruiter_board
        await i.response.defer(ephemeral=True)
        await i.followup.send(embed=await recruiter_board(self.bot.db,i.guild_id,int(self.values[0])),ephemeral=True,allowed_mentions=discord.AllowedMentions.none())

async def install_hub(bot,guild):
    cfg=await bot.db.get_config(guild.id);category=guild.get_channel(cfg.get('management_category_id') or 0)
    roles=configured_roles(guild,cfg,HIGH_KEYS)
    if not category or len(roles)!=3:return
    ow={guild.default_role:discord.PermissionOverwrite(view_channel=False),guild.me:discord.PermissionOverwrite(view_channel=True,send_messages=True,embed_links=True,read_message_history=True)}
    for r in roles:ow[r]=discord.PermissionOverwrite(view_channel=True,send_messages=False,read_message_history=True)
    topic=f'colombo:management:v1:{bot.user.id}:{guild.id}'
    channels=await guild.fetch_channels();matches=[c for c in channels if isinstance(c,discord.TextChannel) and c.topic==topic]
    if len(matches)>1:raise ValueError('Найдены две панели управления; требуется выбрать основной канал.')
    ch=matches[0] if matches else await guild.create_text_channel('управление-ботом',category=category,topic=topic,overwrites=ow)
    if ch.overwrites!=ow:await ch.edit(overwrites=ow)
    msg=None
    async for old in ch.history(limit=50):
        if old.author.id==bot.user.id and any(getattr(c,'custom_id',None)=='colombo:hub:queue' for row in old.components for c in row.children):msg=old;break
    e=base_embed('COLOMBO • Управление','Заявки, отдых, мероприятия и игроки — в одной панели.\nДоступ: **High · Deputy Leader · Leader**.',0xA82D40)
    if msg:await msg.edit(embed=e,view=ManagementView(bot),allowed_mentions=discord.AllowedMentions.none())
    else:await ch.send(embed=e,view=ManagementView(bot),allowed_mentions=discord.AllowedMentions.none())
    print(f'Management hub ready | guild={guild.id} | channel={ch.id}')
