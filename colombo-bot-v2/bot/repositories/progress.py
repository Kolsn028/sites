"""SQL operations for progress; callers use named methods."""


class ProgressRepository:
    async def tier_threads(self, guild_id):
        return await self._all("SELECT member_id,thread_id FROM progress_requests WHERE guild_id=? AND kind IN ('tier_1','tier_2','tier_3')", (guild_id,))

    async def progress_by_thread(self, guild_id, thread_id):
        return await self._one('SELECT * FROM progress_requests WHERE guild_id=? AND thread_id=?', (guild_id, thread_id,))

    async def find_open_tier(self, guild_id, member_id):
        return await self._one("SELECT thread_id FROM progress_requests WHERE guild_id=? AND member_id=? AND kind IN ('tier_1','tier_2','tier_3') AND status IN ('pending','applying')", (guild_id, member_id,))

    async def progress_by_id(self, request_id):
        return await self._one('SELECT * FROM progress_requests WHERE id=?', (request_id,))

    async def find_open_progress(self, guild_id, member_id, kind):
        return await self._one("SELECT * FROM progress_requests WHERE guild_id=? AND member_id=? AND kind=? AND status='pending'", (guild_id, member_id, kind,))

    async def progress_kind_by_thread(self, guild_id, thread_id):
        return await self._one('SELECT kind FROM progress_requests WHERE guild_id=? AND thread_id=?', (guild_id, thread_id,))

    async def vacation_return_request(self, guild_id, thread_id, message_id):
        return await self._one('SELECT * FROM vacations WHERE guild_id=? AND return_thread_id=? AND return_message_id=?', (guild_id, thread_id, message_id,))

    async def create_progress(self, guild_id, member_id, kind, thread_id, details, created_at):
        return await self._write(
            'INSERT INTO progress_requests(guild_id,member_id,kind,thread_id,details,created_at) VALUES (?,?,?,?,?,?)',
            (guild_id, member_id, kind, thread_id, details, created_at))

    async def fail_progress(self, request_id):
        await self._write("UPDATE progress_requests SET status='failed' WHERE id=?", (request_id,))

    async def delete_progress_thread(self, thread_id):
        await self._write('DELETE FROM progress_requests WHERE thread_id=?', (thread_id,))

    async def set_progress_decision(self, request_id, status, actor, reason):
        await self._write('UPDATE progress_requests SET status=?,handled_by=?,decision=? WHERE id=?',
                          (status, actor, reason, request_id))

    async def decide_progress_thread(self, thread_id, status, actor, reason):
        await self._write('UPDATE progress_requests SET status=?,handled_by=?,decision=? WHERE thread_id=?',
                          (status, actor, reason, thread_id))
