import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock,MagicMock
import discord
from bot.tiers import award_tier,TIER_ROLES,GUILD_ID,TierModal,can_review,TIERCHECK_ROLE_ID,TierReviewView,TierDecision

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
        for role,expected in [(4,False),(3,False),(2,False),(1,False),(TIERCHECK_ROLE_ID,True)]:
            user.get_role.side_effect=lambda rid: rid==role
            self.assertEqual(bool(await can_review(bot,i)),expected)
        for tier in (1,2,3):
            form=TierModal(bot,tier)
            self.assertEqual(len(form.children),5)
            self.assertEqual(form.mcl.required,tier in (1,2))

    async def test_owner_admin_without_tiercheck_denied_and_modal_rechecks(self):
        user=MagicMock(spec=discord.Member);user.id=100;user.guild=SimpleNamespace(owner_id=100)
        user.guild_permissions=discord.Permissions(administrator=True)
        user.get_role.return_value=None
        i=SimpleNamespace(guild_id=GUILD_ID,user=user,response=SimpleNamespace(send_message=AsyncMock()))
        bot=SimpleNamespace()
        self.assertFalse(await can_review(bot,i))
        user.get_role.return_value=object()
        view=TierReviewView(bot)
        self.assertTrue(await view.interaction_check(i))
        # Role removed after opening the form: neither decision may proceed.
        user.get_role.return_value=None
        for accepted in (True,False):
            await TierDecision(bot,accepted).on_submit(i)
        self.assertEqual(i.response.send_message.await_count,2)
        user.get_role.return_value=object();i.guild_id=42
        self.assertFalse(await can_review(bot,i))

    async def test_access_repair_includes_archive_and_is_repeat_safe(self):
        from collections import defaultdict
        import asyncio
        from bot.tiers import sync_reviewers
        reviewer=SimpleNamespace(id=50,bot=False,get_role=lambda rid:rid==TIERCHECK_ROLE_ID)
        thread=MagicMock(spec=discord.Thread);thread.id=80;thread.archived=True;thread.locked=True
        thread.parent=SimpleNamespace(topic=f'colombo:tier:1:999:{GUILD_ID}')
        present=[]
        thread.fetch_members=AsyncMock(side_effect=lambda:present.copy())
        async def fetch_one(uid):
            if any(m.id==uid for m in present):return SimpleNamespace(id=uid)
            raise discord.NotFound(SimpleNamespace(status=404,reason='missing'),'missing')
        thread.fetch_member=AsyncMock(side_effect=fetch_one)
        async def add(m):present.append(SimpleNamespace(id=m.id))
        thread.add_user=AsyncMock(side_effect=add);thread.edit=AsyncMock()
        guild=SimpleNamespace(id=GUILD_ID,chunked=True,get_role=lambda _:SimpleNamespace(members=[reviewer]),get_member=lambda _:reviewer,fetch_channel=AsyncMock(return_value=thread))
        bot=SimpleNamespace(user=SimpleNamespace(id=999),operation_locks=defaultdict(asyncio.Lock),db=SimpleNamespace(tier_threads=AsyncMock(return_value=[{'member_id':10,'thread_id':80}])))
        self.assertEqual(await sync_reviewers(bot,guild,reviewer),(1,0))
        self.assertEqual(thread.edit.call_args_list[-1].kwargs['archived'],True)
        self.assertEqual(thread.edit.call_args_list[-1].kwargs['locked'],True)
        self.assertEqual(await sync_reviewers(bot,guild,reviewer),(0,0))
        thread.add_user.assert_awaited_once()
        # A similarly named channel outside this bot's tier panels is never touched.
        present.clear();thread.parent.topic='colombo:tier:1:other:server'
        self.assertEqual(await sync_reviewers(bot,guild,reviewer),(0,0))
        thread.add_user.assert_awaited_once()

    async def test_access_repair_restores_archive_even_when_invitation_fails(self):
        from collections import defaultdict
        import asyncio
        from bot.tiers import sync_reviewers
        reviewer=SimpleNamespace(id=50,bot=False,get_role=lambda rid:rid==TIERCHECK_ROLE_ID)
        thread=MagicMock(spec=discord.Thread);thread.archived=True;thread.locked=True
        thread.parent=SimpleNamespace(topic=f'colombo:tier:2:999:{GUILD_ID}')
        thread.fetch_members=AsyncMock(return_value=[]);thread.edit=AsyncMock()
        thread.fetch_member=AsyncMock(side_effect=discord.NotFound(SimpleNamespace(status=404,reason='missing'),'missing'))
        thread.add_user=AsyncMock(side_effect=discord.Forbidden(SimpleNamespace(status=403,reason='Forbidden'),'missing permissions'))
        guild=SimpleNamespace(id=GUILD_ID,chunked=True,get_role=lambda _:SimpleNamespace(members=[reviewer]),get_member=lambda _:reviewer,fetch_channel=AsyncMock(return_value=thread))
        bot=SimpleNamespace(user=SimpleNamespace(id=999),operation_locks=defaultdict(asyncio.Lock),db=SimpleNamespace(tier_threads=AsyncMock(return_value=[{'member_id':10,'thread_id':80}])))
        self.assertEqual(await sync_reviewers(bot,guild,reviewer),(0,1))
        self.assertTrue(thread.edit.call_args.kwargs['archived'])
        self.assertTrue(thread.edit.call_args.kwargs['locked'])

    async def test_new_application_notifies_only_inside_private_thread(self):
        import asyncio
        from collections import defaultdict
        from unittest.mock import patch
        user=MagicMock(spec=discord.Member);user.id=10;user.display_name='Applicant'
        guild=SimpleNamespace(id=GUILD_ID,get_role=lambda _:object())
        channel=SimpleNamespace(topic=f'colombo:tier:2:999:{GUILD_ID}',send=AsyncMock())
        thread=SimpleNamespace(id=88,mention='<#88>',send=AsyncMock())
        bot=SimpleNamespace(user=SimpleNamespace(id=999),is_family_member=AsyncMock(return_value=True),
            now_iso=lambda:'2026-09-21T00:00:00+00:00',operation_locks=defaultdict(asyncio.Lock),
            db=SimpleNamespace(find_open_tier=AsyncMock(return_value=None),create_progress=AsyncMock(return_value=1)))
        i=SimpleNamespace(guild_id=GUILD_ID,guild=guild,user=user,channel=channel,
            response=SimpleNamespace(defer=AsyncMock()),followup=SimpleNamespace(send=AsyncMock()))
        with patch('bot.tier_system.applications.private_thread',AsyncMock(return_value=thread)) as create:
            await TierModal(bot,2).on_submit(i)
        create.assert_awaited_once()
        channel.send.assert_not_awaited()
        thread.send.assert_awaited_once()
        self.assertIn(str(TIERCHECK_ROLE_ID),thread.send.call_args.kwargs['content'])
        self.assertEqual([r.id for r in thread.send.call_args.kwargs['allowed_mentions'].roles],[TIERCHECK_ROLE_ID])

    async def test_channel_binding_requires_exact_bot_guild_and_tier(self):
        from bot.tiers import tier_channel_topic, tier_from_channel
        channel=SimpleNamespace(topic=tier_channel_topic(2,999,GUILD_ID))
        self.assertEqual(tier_from_channel(channel,999,GUILD_ID),2)
        self.assertIsNone(tier_from_channel(channel,998,GUILD_ID))
        self.assertIsNone(tier_from_channel(channel,999,42))
        channel.topic=f'colombo:tier:4:999:{GUILD_ID}'
        self.assertIsNone(tier_from_channel(channel,999,GUILD_ID))
