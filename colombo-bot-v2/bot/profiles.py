"""Read-through player cards: visits, reports and contracts keep their source IDs."""
import math
from datetime import datetime, timezone, timedelta
import discord
from .roles import STAFF_KEYS, has_role, is_leader
from .ui import base_embed
from .interactions import SafeView

SECTIONS={'all':'Обзор','mcl':'🟥 MCL','vzm':'🟩 VZM','vzz':'🟦 VZZ','capt':'⚔️ Капты',
          'contract':'🟠 Контракты','mp':'🎯 Старые МП','msh':'🛡️ МШ','training':'🏋️ Тренировки','other':'📌 Другое'}
STATUS={'approved':'✅ Подтверждено','pending_review':'🟡 Проверяется','pending_classification':'⚪ Не выбран тип',
        'pending':'🟡 Проверяется','rejected':'❌ Отклонено','failed':'⚠️ Не отправлено'}


async def can_view(bot,guild,viewer,member_id):
    if not isinstance(viewer,discord.Member):return False
    cfg=await bot.db.get_config(guild.id)
    return viewer.id==member_id or is_leader(viewer,cfg) or bool(has_role(viewer,cfg,STAFF_KEYS))


async def records(db,guild_id,member_id,days=0):
    result=[]
    events=await db._all('''SELECT e.*,s.attended,s.seat,s.confirmed_by,s.confirmed_at FROM event_signups s
        JOIN family_events e ON e.id=s.event_id WHERE e.guild_id=? AND s.member_id=?''',(guild_id,member_id))
    for e in events:
        result.append(dict(key=f"event:{e['id']}",category=e['kind'],kind='visit',
            status='approved' if e['attended'] else 'pending',title=e['title'],
            date=datetime.fromtimestamp(e['starts_at'],timezone.utc).isoformat(),
            url=f"https://discord.com/channels/{guild_id}/{e['channel_id']}/{e['message_id']}",
            detail=(('✅ Подтверждено ранее' if not e['confirmed_by'] else '✅ Присутствовал') if e['attended'] else ('🕒 Записан' if e['status']=='open' else '⚪ Присутствие не подтверждено'))+
                (' · резерв' if e['seat']=='reserve' else ' · основа'),points=0))
    reports=await db._all('SELECT * FROM activity_submissions WHERE guild_id=? AND member_id=?',(guild_id,member_id))
    for r in reports:
        result.append(dict(key=f"report:{r['id']}",category=r['category'],kind='report',status=r['status'],
            title=f"Отчёт #{r['id']}",date=r['created_at'],points=r['points'] if r['status']=='approved' else 0,
            url=f"https://discord.com/channels/{guild_id}/{r['case_channel_id']}/{r['source_message_id']}",
            detail=STATUS.get(r['status'],r['status'])+(f" · сбор #{r['event_id']}" if r.get('event_id') else '')))
    contracts=await db._all("SELECT * FROM progress_requests WHERE guild_id=? AND member_id=? AND kind='contract'",(guild_id,member_id))
    for r in contracts:
        result.append(dict(key=f"contract:{r['id']}",category='contract',kind='contract',status=r['status'],
            title=(r['details'].split('\n')[0])[:100],date=r['created_at'],points=0,
            url=f"https://discord.com/channels/{guild_id}/{r['thread_id']}",detail=STATUS.get(r['status'],r['status'])))
    cutoff=datetime.now(timezone.utc)-timedelta(days=days) if days else None
    def stamp(r):
        dt=datetime.fromisoformat(r['date']);return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    return sorted([r for r in result if not cutoff or stamp(r)>=cutoff],key=stamp,reverse=True)


async def render(bot,guild,member,section='all',days=30,page=0):
    rows=await records(bot.db,guild.id,member.id,days)
    visits=sum(r['kind']=='visit' and r['status']=='approved' for r in rows)
    reports=sum(r['kind']=='report' and r['status']=='approved' for r in rows)
    contracts=sum(r['kind']=='contract' and r['status']=='approved' for r in rows)
    period=f'{days} дней' if days else 'Всё время'
    cfg=await bot.db.get_config(guild.id)
    rank=next((r.name for r in reversed(member.roles) if not r.is_default()),'Участник')
    vac=await bot.db.pending_vacation_for_member(guild.id,member.id)
    state='🌴 На отдыхе' if vac and vac['status'] in ('applying','approved','return_pending','restoring') else '🟢 В составе'
    e=base_embed(f'ДОСЬЕ • {member.display_name}',
        f'**{discord.utils.escape_markdown(rank)}**\n{state}  ·  {period}\n'
        'Посещения учитываются только после подтверждения. Отчёты и контракты показаны отдельно.',0xA82D40)
    e.set_thumbnail(url=member.display_avatar.url)
    e.add_field(name='ПОСЕЩЕНИЯ',value=f'**{visits}**\nподтверждено',inline=True)
    e.add_field(name='ОТЧЁТЫ',value=f'**{reports}**\nпринято',inline=True)
    e.add_field(name='КОНТРАКТЫ',value=f'**{contracts}**\nподтверждено',inline=True)
    if section=='all':
        for key in ('mcl','vzm','vzz','capt','contract'):
            count=sum(r['status']=='approved' and r['category']==key and r['kind']==('contract' if key=='contract' else 'visit') for r in rows)
            e.add_field(name=SECTIONS[key],value=f'**{count}**',inline=True)
    selected=[r for r in rows if section=='all' or r['category']==section]
    pages=max(1,math.ceil(len(selected)/5));page=max(0,min(page,pages-1))
    history=[]
    for r in selected[page*5:page*5+5]:
        ts=int(datetime.fromisoformat(r['date']).replace(tzinfo=timezone.utc).timestamp()) if '+' not in r['date'] else int(datetime.fromisoformat(r['date']).timestamp())
        title=discord.utils.escape_markdown(r['title'])[:100]
        history.append(f"<t:{ts}:d> · [{title}]({r['url']})\n{r['detail']}")
    e.add_field(name=f'ИСТОРИЯ • {SECTIONS[section]}',value='\n\n'.join(history) or 'За этот период записей нет.',inline=False)
    e.set_footer(text=f'COLOMBO • {member.id} • страница {page+1}/{pages} • данные обновляются при открытии')
    return e,page,pages


class FilterSelect(discord.ui.Select):
    def __init__(self,kind,value):
        self.kind=kind
        options=[discord.SelectOption(label=v,value=k,default=k==value) for k,v in SECTIONS.items()] if kind=='section' else [
            discord.SelectOption(label=label,value=str(n),default=str(n)==str(value)) for n,label in [(7,'За неделю'),(30,'За месяц'),(0,'За всё время')]]
        super().__init__(placeholder='Раздел' if kind=='section' else 'Период',options=options,row=0 if kind=='section' else 1)
    async def callback(self,i):
        if self.kind=='section':self.view.section=self.values[0]
        else:self.view.days=int(self.values[0])
        self.view.page=0
        await self.view.update(i)


class PlayerView(SafeView):
    def __init__(self,bot,member_id,viewer_id,section='all',days=30,page=0):
        super().__init__(timeout=600);self.bot=bot;self.member_id=member_id;self.viewer_id=viewer_id
        self.section=section;self.days=days;self.page=page
        self.add_item(FilterSelect('section',section));self.add_item(FilterSelect('period',days))
    async def interaction_check(self,i):
        if i.user.id!=self.viewer_id or not await can_view(self.bot,i.guild,i.user,self.member_id):
            await i.response.send_message('Нет доступа к этой карточке.',ephemeral=True);return False
        return True
    async def update(self,i):
        member=i.guild.get_member(self.member_id)
        if not member:return await i.response.send_message('Участник покинул сервер.',ephemeral=True)
        await i.response.defer()
        e,page,pages=await render(self.bot,i.guild,member,self.section,self.days,self.page)
        view=PlayerView(self.bot,self.member_id,self.viewer_id,self.section,self.days,page)
        view.previous.disabled=page==0;view.next.disabled=page+1>=pages
        await i.edit_original_response(embed=e,view=view,allowed_mentions=discord.AllowedMentions.none())
    @discord.ui.button(label='Назад',style=discord.ButtonStyle.secondary,row=2)
    async def previous(self,i,_):self.page-=1;await self.update(i)
    @discord.ui.button(label='Далее',style=discord.ButtonStyle.secondary,row=2)
    async def next(self,i,_):self.page+=1;await self.update(i)
    @discord.ui.button(label='Обновить',emoji='🔄',style=discord.ButtonStyle.primary,row=2)
    async def reload(self,i,_):await self.update(i)


async def open_profile(bot,i,member_id):
    if not await can_view(bot,i.guild,i.user,member_id):
        return await i.response.send_message('Чужие дела доступны только Recruit- и старшим ролям.',ephemeral=True)
    member=i.guild.get_member(member_id)
    if not member:return await i.response.send_message('Участник покинул сервер.',ephemeral=True)
    await i.response.defer(ephemeral=True)
    e,page,pages=await render(bot,i.guild,member)
    view=PlayerView(bot,member_id,i.user.id);view.previous.disabled=True;view.next.disabled=pages<=1
    await i.followup.send(embed=e,view=view,ephemeral=True,allowed_mentions=discord.AllowedMentions.none())


class ProfileLauncher(SafeView):
    def __init__(self,bot):super().__init__(timeout=None);self.bot=bot
    @discord.ui.button(label='Открыть статистику',emoji='📊',style=discord.ButtonStyle.primary,custom_id='colombo:profile:open')
    async def open(self,i,_):
        case=await self.bot.db.get_case_by_channel(i.guild_id,i.channel_id)
        if not case:return await i.response.send_message('Личное дело не найдено.',ephemeral=True)
        await open_profile(self.bot,i,case['member_id'])


async def refresh_member(bot,guild,member_id,create=True):
    member=guild.get_member(member_id)
    if not member:return
    case=await bot.db.get_case_by_member(guild.id,member_id)
    if not case and create:
        if not await bot.is_family_member(member):return
        await bot.ensure_personal_case(member)
        return
    if not case:return
    ch=guild.get_channel(case['channel_id'])
    if not isinstance(ch,discord.TextChannel):return
    async with bot.operation_locks[('profile_card',guild.id,member_id)]:
        try:
            e,_,_=await render(bot,guild,member)
            # Permanent card has the latest five entries; filters open privately per viewer.
            msg=None
            if case.get('profile_message_id'):
                try:msg=await ch.fetch_message(case['profile_message_id'])
                except discord.NotFound:pass
            if not msg:
                async for old in ch.history(limit=100):
                    if old.author.id==bot.user.id and any(getattr(c,'custom_id',None)=='colombo:profile:open' for row in old.components for c in row.children):
                        msg=old;break
            if msg:await msg.edit(embed=e,view=ProfileLauncher(bot),allowed_mentions=discord.AllowedMentions.none())
            else:msg=await ch.send(embed=e,view=ProfileLauncher(bot),allowed_mentions=discord.AllowedMentions.none())
            async with bot.db.lock:
                await bot.db.conn.execute('UPDATE personal_cases SET profile_message_id=? WHERE id=?',(msg.id,case['id']));await bot.db.conn.commit()
        except discord.DiscordException as exc:
            print(f'Profile refresh failed member={member_id}: {type(exc).__name__}')
