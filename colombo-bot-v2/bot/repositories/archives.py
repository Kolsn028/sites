"""Archive jobs use audit_actions, which existing snapshots already preserve."""

import json
from datetime import datetime, timezone


class ArchiveRepository:
    async def queue_thread_archive(
        self, guild_id: int, thread_id: int, due: float
    ) -> None:
        async with self.lock:
            if await self._one(
                "SELECT id FROM audit_actions WHERE guild_id=? AND target_id=? AND action='thread_archive:pending'",
                (guild_id, thread_id),
            ):
                return
            try:
                await self.conn.execute(
                    "INSERT INTO audit_actions(guild_id,actor_id,action,target_id,details,created_at) VALUES (?,?,?,?,?,?)",
                    (
                        guild_id,
                        0,
                        "thread_archive:pending",
                        thread_id,
                        json.dumps({"due": due}),
                        datetime.now(timezone.utc).isoformat(),
                    ),
                )
                await self.conn.commit()
            except BaseException:
                await self.conn.rollback()
                raise

    async def pending_thread_archives(self, guild_id, now):
        return await self._all(
            """SELECT p.target_id FROM audit_actions p
            WHERE p.guild_id=? AND p.action='thread_archive:pending'
            AND CAST(json_extract(p.details,'$.due') AS REAL)<=?
            AND NOT EXISTS (SELECT 1 FROM audit_actions d WHERE d.guild_id=p.guild_id
                AND d.target_id=p.target_id AND d.action='thread_archive:done')
            ORDER BY p.id LIMIT 25""",
            (guild_id, now),
        )

    async def finish_thread_archive(self, guild_id: int, thread_id: int) -> None:
        await self._write(
            "INSERT INTO audit_actions(guild_id,actor_id,action,target_id,details,created_at) VALUES (?,?,?,?,?,?)",
            (
                guild_id,
                0,
                "thread_archive:done",
                thread_id,
                "{}",
                datetime.now(timezone.utc).isoformat(),
            ),
        )
