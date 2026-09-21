"""SQL operations for applications; callers use named methods."""


class ApplicationsRepository:
    async def find_open_application(self, guild_id, member_id):
        return await self._one("SELECT id,thread_id FROM applications WHERE guild_id=? AND applicant_id=? AND status IN ('pending','interview') AND thread_id IS NOT NULL ORDER BY id DESC LIMIT 1", (guild_id, member_id,))

    async def record_application_decision(self, app_id, guild_id, actor, status, now, reason=None):
        if status not in ('accepted','rejected') or (status=='rejected' and not (reason or '').strip()):
            raise ValueError('Для отказа нужна причина.')
        async with self.lock:
            await self.conn.execute('BEGIN IMMEDIATE')
            try:
                cur=await self.conn.execute("UPDATE applications SET status=?,handled_by=?,updated_at=?,decided_at=?,rejection_reason=?,interview_room_id=NULL,interview_until=NULL WHERE id=? AND guild_id=? AND status IN ('pending','interview')",(status,actor,now,now,reason,app_id,guild_id))
                if not cur.rowcount:
                    await self.conn.rollback(); return False
                await self.conn.execute('''INSERT INTO recruiter_stats(guild_id,recruiter_id,accepted_count,rejected_count) VALUES (?,?,?,?)
                    ON CONFLICT(guild_id,recruiter_id) DO UPDATE SET accepted_count=accepted_count+excluded.accepted_count,rejected_count=rejected_count+excluded.rejected_count''', (guild_id,actor,int(status=='accepted'),int(status=='rejected')))
                await self.conn.commit()
            except BaseException:
                await self.conn.rollback(); raise
        return True
