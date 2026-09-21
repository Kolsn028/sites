"""SQL operations for events; callers use named methods."""


class EventsRepository:
    async def event_by_message(self, guild_id, message_id):
        return await self._one('SELECT * FROM family_events WHERE guild_id=? AND message_id=?', (guild_id, message_id,))

    async def event_participants(self, event_id):
        return await self._all('SELECT * FROM event_signups WHERE event_id=? ORDER BY joined_at,member_id', (event_id,))

    async def event_by_id(self, event_id):
        return await self._one('SELECT * FROM family_events WHERE id=?', (event_id,))

    async def event_template(self, guild_id, kind):
        return await self._one('SELECT * FROM family_events WHERE guild_id=? AND kind=? AND message_id IS NOT NULL ORDER BY id DESC LIMIT 1', (guild_id, kind,))

    async def guild_event(self, event_id, guild_id):
        return await self._one('SELECT * FROM family_events WHERE id=? AND guild_id=?', (event_id, guild_id,))

    async def event_participation(self, event_id, member_id):
        return await self._one('SELECT 1 FROM event_signups WHERE event_id=? AND member_id=?', (event_id, member_id,))

    async def create_event(self, guild_id, channel_id, creator_id, kind, title, starts_at, capacity, details, reserve_capacity):
        return await self._write(
            'INSERT INTO family_events(guild_id,channel_id,creator_id,kind,title,starts_at,capacity,details,reserve_capacity) VALUES (?,?,?,?,?,?,?,?,?)',
            (guild_id, channel_id, creator_id, kind, title, starts_at, capacity, details, reserve_capacity))

    async def delete_event(self, event_id):
        await self._write('DELETE FROM family_events WHERE id=?', (event_id,))

    async def set_event_message(self, event_id, message_id):
        await self._write('UPDATE family_events SET message_id=? WHERE id=?', (message_id, event_id))

    async def finish_event(self, event_id):
        await self._write("UPDATE family_events SET status='finished' WHERE id=?", (event_id,))

    async def link_report_event(self, guild_id, report_id, event_id, actor):
        from ..roster import audit
        async with self.lock:
            report = await self.get_activity(report_id)
            event = await self.guild_event(event_id, guild_id)
            if not report or report['guild_id'] != guild_id or not event:
                raise ValueError('Отчёт или сбор не найден на этом сервере.')
            if not await self.event_participation(event_id, report['member_id']):
                raise ValueError('Автор отчёта не записан в этот сбор.')
            try:
                await self.conn.execute('UPDATE activity_submissions SET event_id=?,category=? WHERE id=?',
                                        (event_id, event['kind'], report_id))
                await audit(self, guild_id, actor, 'report_event', report_id, {'event': event_id})
                await self.conn.commit()
            except BaseException:
                await self.conn.rollback()
                raise
            return report
