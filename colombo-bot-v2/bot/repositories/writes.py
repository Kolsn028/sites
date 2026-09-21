"""Single-statement writes with rollback; transactions spanning statements stay explicit."""


class WriteRepository:
    async def _write(self, sql, params):
        async with self.lock:
            try:
                cursor = await self.conn.execute(sql, params)
                await self.conn.commit()
                return cursor.lastrowid
            except BaseException:
                await self.conn.rollback()
                raise
