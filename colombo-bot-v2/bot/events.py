"""Family event signups with staff-only creation and verified attendance."""
from datetime import datetime, timezone, timedelta
import discord
from .roles import has_role, HIGH_KEYS, is_leader
from .interactions import SafeView, SafeModal
from .ui import base_embed

EVENTS = {'mcl': ('🟥', 'плюсы-mcl', 0xED4245), 'vzm': ('🟩', 'плюсы-vzm', 0x3BAA72),
          'vzz': ('🟦', 'плюсы-vzz', 0x3498DB), 'capt': ('➕', 'плюсы-на-капт', 0xF39C12)}


def may_manage_events(member, cfg):
    return is_leader(member, cfg) or bool(has_role(member, cfg, HIGH_KEYS))


def parse_time(value):
    try:
        dt = datetime.strptime(value.strip(), '%d.%m.%Y %H:%M').replace(tzinfo=timezone(timedelta(hours=3)))
    except ValueError:
        raise ValueError('Дата: ДД.ММ.ГГГГ ЧЧ:ММ, время московское (UTC+3).')
    if dt <= datetime.now(timezone.utc):
        raise ValueError('Укажи будущую дату и время.')
    return int(dt.timestamp())


async def allowed(bot, i):
    return isinstance(i.user, discord.Member) and may_manage_events(i.user, await bot.db.get_config(i.guild_id))


async def event_row(bot, guild_id, message_id):
    return await bot.db._one('SELECT * FROM family_events WHERE guild_id=? AND message_id=?', (guild_id, message_id))


async def card(db, row):
    people = await db._all('SELECT * FROM event_signups WHERE event_id=? ORDER BY joined_at,member_id', (row['id'],))
    e = base_embed(('🟢 ЗАПИСЬ ОТКРЫТА' if row['status']=='open' else '🛑 ЗАВЕРШЁН') + f" • {row['title']}",
        f"Создал: <@{row['creator_id']}>\nДата: <t:{row['starts_at']}:F> (<t:{row['starts_at']}:R>)\n"
        f"Доступ: участники семьи\n{row['details'] or ''}", EVENTS[row['kind']][2])
    lines = [f"{'👑 ' if p['member_id']==row['creator_id'] else ''}<@{p['member_id']}>{' ✅' if p['attended'] else ''}" for p in people]
    for offset in range(0,max(len(lines),1),20):
        e.add_field(name=f"Участники ({len(people)}/{row['capacity']})" if offset==0 else 'Продолжение списка',
                    value='\n'.join(lines[offset:offset+20]) or 'Пока никто не записался. Нажми «Записаться».',inline=False)
    e.set_footer(text=f"COLOMBO • Сбор #{row['id']} • ✅ присутствие подтверждено организатором")
    return e


async def signup(db, event_id, member_id, leave=False):
    async with db.lock:
        row = await db._one('SELECT * FROM family_events WHERE id=?', (event_id,))
        if not row or row['status'] != 'open': return 'Сбор завершён.'
        if leave:
            await db.conn.execute('DELETE FROM event_signups WHERE event_id=? AND member_id=?', (event_id,member_id))
            await db.conn.commit(); return 'Ты вышел из списка.'
        if await db._one('SELECT 1 FROM event_signups WHERE event_id=? AND member_id=?',(event_id,member_id)):
            return 'Ты уже записан.'
        count = await db._one('SELECT COUNT(*) AS n FROM event_signups WHERE event_id=?',(event_id,))
        if count['n'] >= row['capacity']: return 'Все места заняты.'
        await db.conn.execute('INSERT INTO event_signups(event_id,member_id,joined_at) VALUES (?,?,?)',
                              (event_id,member_id,datetime.now(timezone.utc).isoformat()))
        await db.conn.commit(); return 'Ты записан!'


class CreateEventModal(SafeModal, title='Создать сбор • Colombo'):
    title_input = discord.ui.TextInput(label='Название сбора', max_length=100)
    date_input = discord.ui.TextInput(label='Дата и время по Москве (UTC+3)', placeholder='10.09.2026 20:00',max_length=16)
    limit_input = discord.ui.TextInput(label='Количество мест (1–100)', default='35', max_length=3)
    details_input = discord.ui.TextInput(label='Место встречи / требования', style=discord.TextStyle.paragraph,required=False,max_length=700)
    def __init__(self, bot, kind):
        super().__init__(); self.bot=bot; self.kind=kind
    async def on_submit(self, i):
        if not await allowed(self.bot,i):
            return await i.response.send_message('Создают только Ass.Deputy, Deputy Leader и Leader.',ephemeral=True)
        ts=parse_time(str(self.date_input))
        try: capacity=int(str(self.limit_input))
        except ValueError: raise ValueError('Количество мест — целое число от 1 до 100.')
        if not 1 <= capacity <= 100: raise ValueError('Количество мест — от 1 до 100.')
        cfg=await self.bot.db.get_config(i.guild_id)
        ch=i.guild.get_channel(cfg.get(f'{self.kind}_panel_channel_id') or 0)
        if not isinstance(ch,discord.TextChannel): raise ValueError('Канал сбора не настроен: /setup.')
        await i.response.defer(ephemeral=True)
        async with self.bot.db.lock:
            cur=await self.bot.db.conn.execute('INSERT INTO family_events(guild_id,channel_id,creator_id,kind,title,starts_at,capacity,details) VALUES (?,?,?,?,?,?,?,?)',
                (i.guild_id,ch.id,i.user.id,self.kind,str(self.title_input),ts,capacity,str(self.details_input)))
            eid=cur.lastrowid;await self.bot.db.conn.commit()
        row=await self.bot.db._one('SELECT * FROM family_events WHERE id=?',(eid,))
        try:
            msg=await ch.send(embed=await card(self.bot.db,row),view=EventView(self.bot),allowed_mentions=discord.AllowedMentions.none())
        except Exception:
            async with self.bot.db.lock:
                await self.bot.db.conn.execute('DELETE FROM family_events WHERE id=?',(eid,));await self.bot.db.conn.commit()
            raise
        async with self.bot.db.lock:
            await self.bot.db.conn.execute('UPDATE family_events SET message_id=? WHERE id=?',(msg.id,eid));await self.bot.db.conn.commit()
        await i.followup.send(f'Сбор создан: {msg.jump_url}',ephemeral=True)


class EventPanelView(SafeView):
    def __init__(self,bot): super().__init__(timeout=None);self.bot=bot
    @discord.ui.button(label='Создать сбор',emoji='📅',style=discord.ButtonStyle.primary,custom_id='colombo:event:open')
    async def create(self,i,_):
        if not await allowed(self.bot,i):
            return await i.response.send_message('Создавать сборы могут Ass.Deputy и выше. Для записи нажми кнопку под нужным сбором.',ephemeral=True)
        cfg=await self.bot.db.get_config(i.guild_id)
        kind=next((k for k in EVENTS if cfg.get(f'{k}_panel_channel_id')==i.channel_id),None)
        if not kind: raise ValueError('Канал не настроен: /setup.')
        await i.response.send_modal(CreateEventModal(self.bot,kind))


class AttendanceSelect(discord.ui.UserSelect):
    def __init__(self,bot,message_id):
        super().__init__(placeholder='Выбери участника: поставить / снять ✅',min_values=1,max_values=1)
        self.bot=bot;self.message_id=message_id
    async def callback(self,i):
        if not await allowed(self.bot,i): return await i.response.send_message('Только Ass.Deputy и выше.',ephemeral=True)
        await i.response.defer(ephemeral=True)
        async with self.bot.operation_locks[('event',i.guild_id,self.message_id)]:
            row=await event_row(self.bot,i.guild_id,self.message_id)
            if not row: return await i.followup.send('Сбор не найден.',ephemeral=True)
            async with self.bot.db.lock:
                cur=await self.bot.db.conn.execute('UPDATE event_signups SET attended=1-attended WHERE event_id=? AND member_id=?',(row['id'],self.values[0].id))
                await self.bot.db.conn.commit()
            if not cur.rowcount: return await i.followup.send('Этот участник не записан.',ephemeral=True)
            msg=await i.channel.fetch_message(self.message_id)
            await msg.edit(embed=await card(self.bot.db,row),allowed_mentions=discord.AllowedMentions.none())
            await i.followup.send('Отметка присутствия обновлена.',ephemeral=True)


class EventView(SafeView):
    def __init__(self,bot): super().__init__(timeout=None);self.bot=bot
    async def change(self,i,leave=False):
        if not isinstance(i.user,discord.Member) or (not leave and not await self.bot.is_family_member(i.user)):
            return await i.response.send_message('Запись доступна участникам семьи.',ephemeral=True)
        await i.response.defer(ephemeral=True)
        async with self.bot.operation_locks[('event',i.guild_id,i.message.id)]:
            row=await event_row(self.bot,i.guild_id,i.message.id)
            if not row: return await i.followup.send('Сбор не найден.',ephemeral=True)
            result=await signup(self.bot.db,row['id'],i.user.id,leave)
            await i.message.edit(embed=await card(self.bot.db,row),allowed_mentions=discord.AllowedMentions.none())
            await i.followup.send(result,ephemeral=True)
    @discord.ui.button(label='Записаться',emoji='➕',style=discord.ButtonStyle.success,custom_id='colombo:event:join')
    async def join(self,i,_): await self.change(i)
    @discord.ui.button(label='Выйти',emoji='➖',style=discord.ButtonStyle.secondary,custom_id='colombo:event:leave')
    async def leave(self,i,_): await self.change(i,True)
    @discord.ui.button(label='Присутствие',emoji='✅',style=discord.ButtonStyle.secondary,custom_id='colombo:event:attendance')
    async def attendance(self,i,_):
        if not await allowed(self.bot,i): return await i.response.send_message('Отмечают Ass.Deputy и выше.',ephemeral=True)
        view=SafeView(timeout=180);view.add_item(AttendanceSelect(self.bot,i.message.id))
        await i.response.send_message('Выбери записанного участника. Повторный выбор снимает отметку.',view=view,ephemeral=True)
    @discord.ui.button(label='Завершить',emoji='🛑',style=discord.ButtonStyle.danger,custom_id='colombo:event:finish')
    async def finish(self,i,_):
        if not await allowed(self.bot,i): return await i.response.send_message('Завершают Ass.Deputy и выше.',ephemeral=True)
        await i.response.defer(ephemeral=True)
        async with self.bot.operation_locks[('event',i.guild_id,i.message.id)]:
            row=await event_row(self.bot,i.guild_id,i.message.id)
            if not row: return await i.followup.send('Сбор не найден.',ephemeral=True)
            async with self.bot.db.lock:
                await self.bot.db.conn.execute("UPDATE family_events SET status='finished' WHERE id=?",(row['id'],));await self.bot.db.conn.commit()
            row['status']='finished'
            view=EventView(self.bot)
            for item in view.children: item.disabled=item.custom_id!='colombo:event:attendance'
            await i.message.edit(embed=await card(self.bot.db,row),view=view,allowed_mentions=discord.AllowedMentions.none())
            await i.followup.send('Сбор завершён. Список сохранён; можно отметить присутствие.',ephemeral=True)


def event_panel(kind):
    emoji,name,color=EVENTS[kind]
    return base_embed(f'{emoji} {name.upper()}',
        '**Ass.Deputy и выше:** нажми «Создать сбор», укажи время и число мест.\n'
        '**Участники семьи:** нажмите «Записаться» под нужным сбором. Кнопка «Выйти» освобождает место.\n'
        '✅ Присутствие отмечает организатор. Запись сама по себе не засчитывает активность.',color)
