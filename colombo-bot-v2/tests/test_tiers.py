import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock,MagicMock
import discord
from bot.tiers import award_tier,TIER_ROLES,GUILD_ID,TierModal,can_review

class Role:
    managed=False
    def __init__(self,rid,position):self.id=rid;self.position=position
    def is_default(self):return False
    def __ge__(self,other):return self.position>=other.position

class Tiers(unittest.IsolatedAsyncioTestCase):
    def setup_member(self):
        roles={n:Role(rid,n) for n,rid in TIER_ROLES.items()};unrelated=Role(99,1)
        member=SimpleNamespace(id=15,roles=[roles[2],unrelated]);member.get_role=lambda rid: next((r for r in member.roles if r.id==rid),None)
        async def add(r,**_):member.roles.append(r)
        async def remove(*rs,**_):member.roles[:]=[r for r in member.roles if r not in rs]
        member.add_roles=AsyncMock(side_effect=add);member.remove_roles=AsyncMock(side_effect=remove)
        guild=SimpleNamespace(id=GUILD_ID,get_role=lambda rid:next((r for r in roles.values() if r.id==rid),None),me=SimpleNamespace(top_role=Role(100,10),guild_permissions=SimpleNamespace(manage_roles=True)),fetch_member=AsyncMock(return_value=member))
        return guild,member,roles
    async def test_lower_tier_replaces_higher_and_keeps_other_roles(self):
        guild,member,_=self.setup_member()
        await award_tier(guild,member,1)
        self.assertEqual({r.id for r in member.roles},{TIER_ROLES[1],99})
        await award_tier(guild,member,1)
        member.add_roles.assert_awaited_once();member.remove_roles.assert_awaited_once()
    async def test_failed_add_never_removes_previous_role(self):
        guild,member,_=self.setup_member();member.add_roles.side_effect=RuntimeError('network')
        with self.assertRaises(RuntimeError):await award_tier(guild,member,3)
        member.remove_roles.assert_not_awaited()
        self.assertIsNotNone(member.get_role(TIER_ROLES[2]))
    async def test_bad_hierarchy_prevents_any_change(self):
        guild,member,roles=self.setup_member();roles[3].position=20
        with self.assertRaises(ValueError):await award_tier(guild,member,1)
        member.add_roles.assert_not_awaited();member.remove_roles.assert_not_awaited()
    async def test_retry_partial_change(self):
        guild,member,roles=self.setup_member();member.roles.append(roles[1])
        await award_tier(guild,member,1)
        member.add_roles.assert_not_awaited();self.assertEqual({r.id for r in member.roles},{99,TIER_ROLES[1]})
    async def test_access_and_updated_modal(self):
        user=MagicMock(spec=discord.Member);user.id=5;user.guild=SimpleNamespace(owner_id=100)
        cfg={'high_staff_role_id':3,'dep_leader_role_id':2,'leader_role_id':1,'recruiter_role_id':4}
        bot=SimpleNamespace(db=SimpleNamespace(get_config=AsyncMock(return_value=cfg)))
        i=SimpleNamespace(guild_id=GUILD_ID,user=user)
        for role,expected in [(4,False),(3,True),(2,True),(1,True)]:
            user.get_role.side_effect=lambda rid: rid==role
            self.assertEqual(bool(await can_review(bot,i)),expected)
        for tier in (1,2,3):
            form=TierModal(bot,tier)
            self.assertEqual(len(form.children),5)
            self.assertEqual(form.mcl.required,tier in (1,2))
