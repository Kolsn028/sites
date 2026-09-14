import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
import discord
from bot.leave import begin_leave, restore_leave


class RoleOnlyLeave(unittest.IsolatedAsyncioTestCase):
    async def test_new_leave_only_toggles_leave_role_and_preserves_saved_id(self):
        leave = MagicMock(spec=discord.Role)
        leave.id = 7
        leave.managed = False
        leave.is_default.return_value = False
        leave.__ge__.return_value = False
        member = SimpleNamespace(add_roles=AsyncMock(), remove_roles=AsyncMock())
        guild = SimpleNamespace(id=1, me=SimpleNamespace(top_role=object()),
            fetch_member=AsyncMock(return_value=member), get_role=lambda rid: leave if rid == 7 else None)
        vac = dict(id=1, member_id=10, role_snapshot=None, status='pending')
        async def update(vid, **fields):
            vac.update(fields)
        cfg = {'vacation_role_id': 7}
        bot = SimpleNamespace(now_iso=lambda: '2026-09-14T00:00:00+00:00',
            db=SimpleNamespace(get_config=AsyncMock(return_value=cfg),
                update_vacation=AsyncMock(side_effect=update),
                get_vacation=AsyncMock(side_effect=lambda vid: dict(vac))))
        await begin_leave(bot, guild, dict(vac))
        self.assertEqual(member.add_roles.call_args.args, (leave,))
        member.remove_roles.assert_not_awaited()
        self.assertEqual(vac['status'], 'approved')
        cfg['vacation_role_id'] = 88
        member.add_roles.reset_mock()
        await restore_leave(bot, guild, dict(vac))
        member.add_roles.assert_not_awaited()
        self.assertEqual(member.remove_roles.call_args.args, (leave,))
        self.assertEqual(vac['status'], 'returned')
