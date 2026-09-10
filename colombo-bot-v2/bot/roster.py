"""All roster mutations use the database lock; counters never exceed seat limits."""
import json
from datetime import datetime, timezone
from .roles import is_leader, has_role, HIGH_KEYS


def may_confirm(member, cfg, event):
    return is_leader(member,cfg) or bool(has_role(member,cfg,('dep_leader_role_id',))) or (
        member.id==event['creator_id'] and bool(has_role(member,cfg,HIGH_KEYS)))


async def audit(db,guild_id,actor,action,target,details):
    await db.conn.execute('INSERT INTO audit_actions(guild_id,actor_id,action,target_id,details,created_at) VALUES (?,?,?,?,?,?)',
        (guild_id,actor,action,target,json.dumps(details,ensure_ascii=False),datetime.now(timezone.utc).isoformat()))


async def join(db,event_id,member_id,leave=False,seat='main'):
    if seat not in ('main','reserve'):raise ValueError('Неизвестный состав.')
    async with db.lock:
        event=await db._one('SELECT * FROM family_events WHERE id=?',(event_id,))
        if not event or event['status']!='open':return 'Сбор завершён.'
        current=await db._one('SELECT * FROM event_signups WHERE event_id=? AND member_id=?',(event_id,member_id))
        if leave:
            if current and current['attended']:return 'Присутствие уже подтверждено. Изменение — через организатора.'
            await db.conn.execute('DELETE FROM event_signups WHERE event_id=? AND member_id=?',(event_id,member_id))
            await db.conn.commit();return 'Ты вышел из списка.'
        if current:return 'Ты уже записан.'
        cap=event['capacity'] if seat=='main' else event['reserve_capacity']
        count=await db._one('SELECT COUNT(*) n FROM event_signups WHERE event_id=? AND seat=?',(event_id,seat))
        if count['n']>=cap:return 'Все места заняты.'
        await db.conn.execute('INSERT INTO event_signups(event_id,member_id,joined_at,seat) VALUES (?,?,?,?)',
            (event_id,member_id,datetime.now(timezone.utc).isoformat(),seat))
        await db.conn.commit();return 'Ты записан!' if seat=='main' else 'Ты записан в резерв!'


async def move(db,event_id,member_id,seat,actor):
    if seat not in ('main','reserve'):raise ValueError('Неизвестный состав.')
    async with db.lock:
        event=await db._one('SELECT * FROM family_events WHERE id=?',(event_id,))
        if not event or event['status']!='open':raise ValueError('Сбор уже завершён.')
        row=await db._one('SELECT * FROM event_signups WHERE event_id=? AND member_id=?',(event_id,member_id))
        if not row:raise ValueError('Участник не записан.')
        if row['seat']==seat:return
        cap=event['capacity'] if seat=='main' else event['reserve_capacity']
        count=await db._one('SELECT COUNT(*) n FROM event_signups WHERE event_id=? AND seat=?',(event_id,seat))
        if count['n']>=cap:raise ValueError('В выбранном составе нет свободных мест. Сначала измени лимит или освободи место.')
        await db.conn.execute('UPDATE event_signups SET seat=? WHERE event_id=? AND member_id=?',(seat,event_id,member_id))
        await audit(db,event['guild_id'],actor,'seat',member_id,{'event':event_id,'from':row['seat'],'to':seat})
        await db.conn.commit()


async def limits(db,event_id,main,reserve,actor):
    if not 1<=main<=100 or not 0<=reserve<=99 or main+reserve>100:
        raise ValueError('Основа: 1–100, резерв: 0–99, всего не больше 100 мест.')
    async with db.lock:
        event=await db._one('SELECT * FROM family_events WHERE id=?',(event_id,))
        if not event or event['status']!='open':raise ValueError('Сбор завершён.')
        rows=await db._all('SELECT seat,COUNT(*) n FROM event_signups WHERE event_id=? GROUP BY seat',(event_id,))
        if any(r['n'] > (main if r['seat']=='main' else reserve) for r in rows):
            raise ValueError('Новый лимит меньше числа записанных. Сначала перемести участников.')
        await db.conn.execute('UPDATE family_events SET capacity=?,reserve_capacity=? WHERE id=?',(main,reserve,event_id))
        await audit(db,event['guild_id'],actor,'limits',event_id,{'main':main,'reserve':reserve});await db.conn.commit()


async def confirm(db,event_id,member_id,actor):
    async with db.lock:
        event=await db._one('SELECT * FROM family_events WHERE id=?',(event_id,))
        if not event or event['starts_at']>datetime.now(timezone.utc).timestamp():
            raise ValueError('Подтверждать присутствие можно после начала МП.')
        row=await db._one('SELECT * FROM event_signups WHERE event_id=? AND member_id=?',(event_id,member_id))
        if not row:raise ValueError('Этот участник не записан.')
        value=1-row['attended'];now=datetime.now(timezone.utc).isoformat()
        await db.conn.execute('UPDATE event_signups SET attended=?,confirmed_by=?,confirmed_at=? WHERE event_id=? AND member_id=?',
            (value,actor,now,event_id,member_id))
        await audit(db,event['guild_id'],actor,'attendance',member_id,{'event':event_id,'confirmed':value});await db.conn.commit()
