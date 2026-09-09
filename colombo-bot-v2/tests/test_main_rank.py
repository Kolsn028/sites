import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
import discord
from bot.progression import award_main
from bot.roles import is_family, may_recruit, may_review_reports, may_promote

class MainRank(unittest.IsolatedAsyncioTestCase):
    async def test_award_adds_main_before_removing_novice_and_stops_on_failure(self):
        main=MagicMock(spec=discord.Role);main.id=8;main.managed=False;main.__ge__.return_value=False
        novice=MagicMock(spec=discord.Role);novice.id=5;novice.__ge__.return_value=False
        guild=SimpleNamespace(id=1,get_role={8:main,5:novice}.get,me=SimpleNamespace(top_role=object()))
        bot=SimpleNamespace(db=SimpleNamespace(get_config=AsyncMock(return_value={'main_role_id':8,'accepted_role_id':5})))
        order=[]
        async def add(*a,**k):order.append('add')
        async def remove(*a,**k):order.append('remove')
        member=SimpleNamespace(add_roles=AsyncMock(side_effect=add),remove_roles=AsyncMock(side_effect=remove),get_role=lambda rid:novice)
        await award_main(bot,guild,member)
        self.assertEqual(order,['add','remove'])
        member.add_roles.side_effect=discord.DiscordException('denied');member.remove_roles.reset_mock()
        with self.assertRaises(discord.DiscordException):await award_main(bot,guild,member)
        member.remove_roles.assert_not_awaited()
    def test_main_is_family_without_staff_authority(self):
        cfg=dict(main_role_id=8,accepted_role_id=5)
        member=SimpleNamespace(id=10,guild=SimpleNamespace(owner_id=999),get_role=lambda rid:8 if rid==8 else None)
        self.assertTrue(is_family(member,cfg))
        for policy in (may_recruit,may_review_reports,may_promote):self.assertFalse(policy(member,cfg))
