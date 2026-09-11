import unittest
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, MagicMock
import discord
from bot.membership import accept_member, repair_members, sync_application_members
from bot.roles import is_family

class Membership(unittest.IsolatedAsyncioTestCase):
    def environment(self):
        keys=('guest_role_id','colombo_role_id','accepted_role_id','main_role_id','vacation_role_id')
        roles={}
        for n,key in enumerate(keys,1):
            role=MagicMock(spec=discord.Role);role.id=n;role.managed=False;role.is_default.return_value=False;role.__ge__.return_value=False
            roles[key]=role
        guild=NS(id=99,me=NS(top_role=object()),get_role={r.id:r for r in roles.values()}.get)
        return guild,roles,{k:r.id for k,r in roles.items()}
    def member(self,guild,ids):
        held=set(ids)
        member=NS(id=55,guild=guild,bot=False,get_role=lambda rid: guild.get_role(rid) if rid in held else None)
        async def add(*roles,**kw):held.update(r.id for r in roles)
        async def remove(*roles,**kw):held.difference_update(r.id for r in roles)
        member.add_roles=AsyncMock(side_effect=add);member.remove_roles=AsyncMock(side_effect=remove)
        return member,held
    async def test_accept_and_retry(self):
        g,r,cfg=self.environment();m,held=self.member(g,{1})
        await accept_member(m,cfg,'test');self.assertEqual(held,{2,3})
        await accept_member(m,cfg,'retry');self.assertEqual(held,{2,3})
    async def test_failure_does_not_remove_guest(self):
        g,r,cfg=self.environment();m,held=self.member(g,{1});m.add_roles.side_effect=discord.DiscordException('denied')
        with self.assertRaises(discord.DiscordException):await accept_member(m,cfg,'test')
        m.remove_roles.assert_not_awaited();self.assertEqual(held,{1})
    async def test_repair_only_family_not_guests_or_leave(self):
        g,r,cfg=self.environment()
        entries=[self.member(g,ids) for ids in ({1,3},{1},{1,3,5},{1,4})]
        g.members=[x[0] for x in entries]
        bot=NS(db=NS(pending_vacation_for_member=AsyncMock(return_value=None)))
        self.assertEqual(await repair_members(bot,g,r),2)
        self.assertEqual([x[1] for x in entries],[{2,3},{1},{1,3,5},{2,4}])
        self.assertEqual(await repair_members(bot,g,r),0)
    async def test_claim_removes_other_reviewers(self):
        g,r,cfg=self.environment()
        thread=NS(guild=g,fetch_members=AsyncMock(return_value=[NS(id=i) for i in (10,20,30,999)]),remove_user=AsyncMock(),add_user=AsyncMock())
        bot=NS(user=NS(id=999),db=NS(get_config=AsyncMock(return_value=cfg)))
        await sync_application_members(bot,thread,{'applicant_id':10,'assigned_to':20})
        self.assertEqual([c.args[0].id for c in thread.remove_user.call_args_list],[30])
    def test_guest_has_no_family_access(self):
        g,r,cfg=self.environment();g.owner_id=1000
        guest,_=self.member(g,{1});family,_=self.member(g,{2})
        self.assertFalse(is_family(guest,cfg));self.assertTrue(is_family(family,cfg))
