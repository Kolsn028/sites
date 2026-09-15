"""Repeatable case recovery, dated decisions and two-hour recruiter reminders."""
from datetime import datetime, timezone, timedelta
import discord
from .interactions import SafeModal
from .roles import application_recruiters, HIGH_KEYS, has_role, is_leader
from .ui import base_embed


def stamp(value):
    dt = datetime.fromisoformat(value)
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


async def decide_application(db, app_id, guild_id, actor, status, now, reason=None):
    if status not in ('accepted','rejected') or (status=='rejected' and not (reason or '').strip()):
        raise ValueError('Для отказа нужна причина.')
    async with db.lock:
        await db.conn.execute('BEGIN IMMEDIATE')
        try:
            cur=await db.conn.execute("UPDATE applications SET status=?,handled_by=?,updated_at=?,decided_at=?,rejection_reason=?,interview_room_id=NULL,interview_until=NULL WHERE id=? AND guild_id=? AND status IN ('pending','interview')",(status,actor,now,now,reason,app_id,guild_id))
            if not cur.rowcount:
                await db.conn.rollback(); return False
            await db.conn.execute('''INSERT INTO recruiter_stats(guild_id,recruiter_id,accepted_count,rejected_count) VALUES (?,?,?,?)
                ON CONFLICT(guild_id,recruiter_id) DO UPDATE SET accepted_count=accepted_count+excluded.accepted_count,rejected_count=rejected_count+excluded.rejected_count''', (guild_id,actor,int(status=='accepted'),int(status=='rejected')))
            await db.conn.commit()
        except Exception:
            await db.conn.rollback(); raise
    return True


class RejectionModal(SafeModal,title='Причина отказа'):
    reason=discord.ui.TextInput(label='Почему заявка отклонена?',style=discord.TextStyle.paragraph,min_length=3,max_length=700)
    def __init__(self,bot,app_id):
        super().__init__(timeout=300);self.bot=bot;self.app_id=app_id
    async def on_submit(self,i):
        reason=str(self.reason).strip()
        if len(reason)<3: return await i.response.send_message('Напиши причину отказа.',ephemeral=True)
        if not isinstance(i.user,discord.Member) or not await self.bot.is_recruiter(i.user):
            return await i.response.send_message('Нет доступа к рассмотрению заявок.',ephemeral=True)
        await i.response.defer(ephemeral=True)
        async with self.bot.operation_locks[('recruiter_decision',i.guild_id,i.channel_id)]:
            app=await self.bot.db.get_application_by_thread(i.guild_id,i.channel_id)
            if not app or app['id']!=self.app_id or not app.get('assigned_to'):
                return await i.followup.send('Заявка изменилась. Открой её заново.',ephemeral=True)
            if app['assigned_to']!=i.user.id and not await self.bot.can_manage(i.user):
                return await i.followup.send('Отказ оформляет ответственный рекрутер.',ephemeral=True)
            if not await decide_application(self.bot.db,app['id'],i.guild_id,i.user.id,'rejected',self.bot.now_iso(),reason):
                return await i.followup.send('Заявка уже закрыта.',ephemeral=True)
            await i.followup.send('Отказ и причина сохранены в истории игрока.',ephemeral=True)
            await i.channel.send(embed=base_embed('❌ По заявке отказ',f"Кандидат: <@{app['applicant_id']}>\nРекрутер: {i.user.mention}\nПричина: {discord.utils.escape_markdown(reason)}",0xD64045),allowed_mentions=discord.AllowedMentions.none())
            from .profiles import refresh_member
            await refresh_member(self.bot,i.guild,app['applicant_id'],create=False)
            await self.bot.send_or_update_leaderboard(i.guild)
            if isinstance(i.channel,discord.Thread): await i.channel.edit(archived=True,locked=True)


async def recruiter_board(db,guild_id,days):
    if not days:
        rows=await db.leaderboard(guild_id,10)
    else:
        cutoff=(datetime.now(timezone.utc)-timedelta(days=days)).isoformat()
        rows=await db._all("""SELECT handled_by recruiter_id,SUM(status='accepted') accepted_count,SUM(status='rejected') rejected_count
            FROM applications WHERE guild_id=? AND handled_by IS NOT NULL AND decided_at IS NOT NULL
            AND julianday(decided_at)>=julianday(?) AND status IN ('accepted','rejected') GROUP BY handled_by
            ORDER BY accepted_count DESC,rejected_count ASC,handled_by LIMIT 10""",(guild_id,cutoff))
    lines=[f"{n+1}. <@{r['recruiter_id']}> — **{r['accepted_count']}** принято · **{r['rejected_count']}** отказов" for n,r in enumerate(rows)]
    e=base_embed('🏆 Рекруты • '+({7:'за неделю',30:'за месяц'}.get(days,'всё время')),'\n'.join(lines) or 'За этот период решений пока нет.',0xE5B64B)
    if days: e.set_footer(text='Последние 7 / 30 дней • старые суммы без дат входят только в общий рейтинг')
    return e


async def find_case(bot,member):
    cfg=await bot.db.get_case_by_member(member.guild.id,member.id)
    if cfg:
        channel=member.guild.get_channel(cfg['channel_id'])
        if isinstance(channel,discord.TextChannel): return channel
    # Fetch fresh channels: a just-created channel might not have reached the Gateway cache yet.
    channels=await member.guild.fetch_channels()
    found=sorted((c for c in channels if isinstance(c,discord.TextChannel) and c.topic==f'Личное дело • owner={member.id}'),key=lambda c:c.id)
    if found:
        ch=found[0]
        await bot.db.create_case(member.guild.id,member.id,ch.id,bot.now_iso())
        async with bot.db.lock:
            await bot.db.conn.execute('UPDATE personal_cases SET profile_message_id=NULL WHERE guild_id=? AND member_id=?',(member.guild.id,member.id));await bot.db.conn.commit()
        return ch


async def create_case_channel(bot,member,base,overwrites,name):
    async with bot.operation_locks[('case_category',member.guild.id)]:
        channels=await member.guild.fetch_channels()
        prefix=f'Личные дела • {base.id} • '
        categories=[c for c in channels if isinstance(c,discord.CategoryChannel) and (c.id==base.id or c.name.startswith(prefix))]
        categories.sort(key=lambda c:(c.id!=base.id,c.id))
        target=next((c for c in categories if sum(x.category_id==c.id for x in channels if hasattr(x,'category_id'))<50),None)
        if target is None:
            target=await member.guild.create_category(prefix+str(len(categories)+1),overwrites=base.overwrites,reason='Colombo: следующая категория личных дел')
        return await member.guild.create_text_channel(name,category=target,overwrites=overwrites,topic=f'Личное дело • owner={member.id}',reason='Colombo: личное дело')


async def mark_staff_response(bot,msg):
    if not msg.guild or msg.author.bot or not isinstance(msg.author,discord.Member): return
    if not isinstance(msg.channel,discord.Thread): return
    app=await bot.db.get_application_by_thread(msg.guild.id,msg.channel.id)
    if not app or app['status'] not in ('pending','interview') or msg.author.id==app['applicant_id']: return
    if await bot.is_recruiter(msg.author):
        async with bot.db.lock:
            await bot.db.conn.execute("UPDATE applications SET updated_at=? WHERE id=? AND status IN ('pending','interview')",(msg.created_at.isoformat(),app['id']));await bot.db.conn.commit()


async def remind_applications(bot,guild):
    now=datetime.now(timezone.utc)
    cfg=await bot.db.get_config(guild.id)
    rows=await bot.db._all("SELECT * FROM applications WHERE guild_id=? AND status IN ('pending','interview') AND thread_id IS NOT NULL",(guild.id,))
    for initial in rows:
        async with bot.operation_locks[('recruiter_decision',guild.id,initial['thread_id'])]:
            app=await bot.db.get_application_by_thread(guild.id,initial['thread_id'])
            if not app or app['status'] not in ('pending','interview'): continue
            last=max(stamp(app['updated_at']),stamp(app.get('last_reminded_at') or app['created_at']))
            if now-last<timedelta(hours=2): continue
            try:
                thread=guild.get_thread(app['thread_id']) or await bot.fetch_channel(app['thread_id'])
                if thread.guild.id!=guild.id: continue
                if app.get('assigned_to'):
                    member=guild.get_member(app['assigned_to'])
                    # Never ping senior roles, even when they personally claimed an application.
                    people=[member] if member and not member.bot and not is_leader(member,cfg) and not has_role(member,cfg,HIGH_KEYS) else []
                else:
                    people=application_recruiters(guild,cfg)
                if not people: continue
                if thread.archived: await thread.edit(archived=False)
                for offset in range(0,len(people),40):
                    group=people[offset:offset+40]
                    await thread.send(' '.join(m.mention for m in group)+f"\n⏰ Заявка #{app['id']} ждёт ответа более 2 часов.",allowed_mentions=discord.AllowedMentions(everyone=False,roles=False,users=group,replied_user=False))
                await bot.db.update_application(app['id'],last_reminded_at=now.isoformat())
            except discord.DiscordException as exc:
                print(f'Reminder failed | guild={guild.id} | application={app["id"]}: {exc}')


async def refresh_interface(bot,guild):
    """Update existing bot panels/cards without running setup or modifying role grants."""
    from .events import EVENTS,event_panel,EventPanelView,EventView,card
    from .profiles import refresh_member
    from .ui import vacation_panel_embed
    cfg=await bot.db.get_config(guild.id)
    from .progression import contract_panel_embed,promotion_panel_embed
    for kind in (*EVENTS,'vacation','contract','promotion'):
        cid=cfg.get(f'{kind}_panel_channel_id');mid=cfg.get(f'{kind}_panel_message_id')
        if not cid or not mid: continue
        try:
            ch=guild.get_channel(cid) or await bot.fetch_channel(cid)
            msg=await ch.fetch_message(mid)
            if msg.author.id!=bot.user.id: continue
            kwargs={'embed':event_panel(kind),'view':EventPanelView(bot)} if kind in EVENTS else {'embed':vacation_panel_embed()}
            if kind=='contract': kwargs={'embed':contract_panel_embed()}
            if kind=='promotion': kwargs={'embed':promotion_panel_embed()}
            await msg.edit(**kwargs,allowed_mentions=discord.AllowedMentions.none())
        except discord.NotFound: continue
    for row in await bot.db._all('SELECT * FROM family_events WHERE guild_id=? AND message_id IS NOT NULL',(guild.id,)):
        try:
            ch=guild.get_channel(row['channel_id']) or await bot.fetch_channel(row['channel_id'])
            msg=await ch.fetch_message(row['message_id'])
            if msg.author.id!=bot.user.id: continue
            view=EventView(bot)
            if row['status']!='open':
                for item in view.children: item.disabled=item.custom_id!='colombo:event:manage'
            await msg.edit(embed=await card(bot.db,row),view=view,allowed_mentions=discord.AllowedMentions.none())
        except discord.NotFound: continue
    for case in await bot.db._all('SELECT member_id FROM personal_cases WHERE guild_id=?',(guild.id,)):
        await refresh_member(bot,guild,case['member_id'],create=False)
    print(f'Interface refreshed | guild={guild.id}')
