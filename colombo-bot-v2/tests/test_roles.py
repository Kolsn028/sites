import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock
from bot.roles import may_recruit, may_review_reports, is_family, notify_recruiters, named_role, STAFF_KEYS, configured_roles, may_promote, may_review_vacation, may_manage_recruiters
from bot.ui import application_banner_file, application_panel_embed

CFG = dict(leader_role_id=1, dep_leader_role_id=2, high_staff_role_id=3,
           recruiter_role_id=4, accepted_role_id=5, colombo_role_id=6)

def member(rank_ids, admin=False, uid=10, guild=None):
    return SimpleNamespace(id=uid, guild=guild or SimpleNamespace(owner_id=999),
        get_role=lambda rid: rid if rid in rank_ids else None,
        guild_permissions=SimpleNamespace(administrator=admin), bot=False, mention=f'<@{uid}>')

class RolePolicy(unittest.IsolatedAsyncioTestCase):
    def test_hierarchy_access_matrix(self):
        for rank in range(1,7):
            m=member([rank],admin=True)
            self.assertEqual(bool(may_recruit(m,CFG)),rank in (1,2,3,4))
            self.assertEqual(bool(may_review_reports(m,CFG)),rank in (1,2,3,4))
            self.assertEqual(bool(may_promote(m,CFG)),rank in (1,2,3,4))
            self.assertEqual(bool(may_review_vacation(m,CFG)),rank in (1,2,3))
            self.assertEqual(bool(may_manage_recruiters(m,CFG)),rank in (1,2,3))
            self.assertEqual(bool(is_family(m,CFG)),rank!=6)
        self.assertTrue(may_recruit(member([],admin=True,uid=999),CFG))
        self.assertTrue(may_recruit(member([2,4]),CFG))

    async def test_recruit_notifications_exclude_leader_and_deputy_with_recruit_role(self):
        people=[member([4],uid=10),member([1,4],uid=11),member([2,4],uid=12)]
        role=SimpleNamespace(members=people)
        guild=SimpleNamespace(get_role=lambda rid: role if rid==4 else None)
        channel=SimpleNamespace(send=AsyncMock())
        await notify_recruiters(channel,guild,CFG,None)
        args=channel.send.call_args.kwargs
        self.assertEqual(args['content'],'<@10>')
        self.assertEqual([m.id for m in args['allowed_mentions'].users],[10])
        self.assertFalse(args['allowed_mentions'].roles)
        self.assertFalse(args['allowed_mentions'].everyone)

    def test_staff_visibility_includes_all_four_ranks(self):
        guild=SimpleNamespace(get_role=lambda rid: rid or None)
        self.assertEqual(configured_roles(guild,CFG,STAFF_KEYS),[1,2,3,4])

    def test_ambiguous_names_require_explicit_choice(self):
        def role(rid): return SimpleNamespace(id=rid,name='Leader',managed=False,is_default=lambda:False)
        guild=SimpleNamespace(roles=[role(1),role(2)])
        with self.assertRaises(ValueError): named_role(guild,'leader_role_id')

    async def test_join_grants_colombo_only(self):
        from bot.core import ColomboBot
        role=SimpleNamespace(id=6)
        bot=SimpleNamespace(db=SimpleNamespace(get_config=AsyncMock(return_value=CFG)))
        guild=SimpleNamespace(id=100,get_role=lambda rid:role if rid==6 else None)
        user=SimpleNamespace(bot=False,guild=guild,add_roles=AsyncMock())
        await ColomboBot.on_member_join(bot,user)
        self.assertEqual(user.add_roles.call_args.args,(role,))

    def test_application_banner_is_bundled_and_text_is_short(self):
        file=application_banner_file()
        self.assertEqual(file.fp.read(8),b'\x89PNG\r\n\x1a\n')
        file.close()
        e=application_panel_embed()
        self.assertEqual(e.image.url,'attachment://colombo-banner.png')
        self.assertLess(len(e.description),220)
        self.assertEqual(len(e.fields),0)

    async def test_assistant_pings_exclude_both_leaders_with_overlapping_roles(self):
        from bot.roles import notify_assistants
        people=[member([3],uid=10),member([1,3],uid=11),member([2,3],uid=12)]
        guild=SimpleNamespace(get_role=lambda rid:SimpleNamespace(members=people) if rid==3 else None)
        channel=SimpleNamespace(send=AsyncMock())
        await notify_assistants(channel,guild,CFG,None)
        self.assertEqual(channel.send.call_args.kwargs['content'],'<@10>')
        self.assertEqual([m.id for m in channel.send.call_args.kwargs['allowed_mentions'].users],[10])
