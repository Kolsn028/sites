from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch
from datetime import datetime, timezone
from test_requested_high import RequestedHigh, GUILD_ID, MEMBER_ID
from bot.requested_role_removal import apply


class Role:
    def __init__(self, rid, position, managed=False):
        self.id, self.position, self.managed = rid, position, managed
    def is_default(self): return self.id == GUILD_ID
    def __lt__(self, other): return self.position < other.position


class Removal(RequestedHigh):
    async def test_removal_preserves_uneditable_and_never_repeats(self):
        everyone, low, managed, high, botrole = [Role(GUILD_ID,0), Role(301,1), Role(302,2,True), Role(303,9), Role(304,5)]
        held = [everyone, low, managed, high]
        async def remove(role, **kwargs):
            self.bot.backups.save.assert_awaited_once()
            held.remove(role)
        member = NS(roles=held, remove_roles=AsyncMock(side_effect=remove))
        me = NS(roles=[everyone,botrole], guild_permissions=NS(manage_roles=True))
        async def fetch(mid): return me if mid == self.bot.user.id else member
        guild = NS(id=GUILD_ID, fetch_roles=AsyncMock(return_value=[everyone,low,managed,high,botrole]), fetch_member=AsyncMock(side_effect=fetch))
        with patch.dict('os.environ', {'REQUESTED_REMOVE_GUILD_ID':str(GUILD_ID), 'REQUESTED_REMOVE_MEMBER_ID':str(MEMBER_ID)}), patch('bot.requested_role_removal.datetime') as clock:
            clock.now.return_value = datetime(2026,9,21,12,tzinfo=timezone.utc)
            await apply(self.bot, guild)
            self.assertEqual(held, [everyone,managed,high])
            held.append(low)
            await apply(self.bot, guild)
            member.remove_roles.assert_awaited_once()
            self.assertIn(low, held)
