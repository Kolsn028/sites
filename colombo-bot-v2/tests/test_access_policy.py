"""Keep role combinations and explicit exceptions stable across UI refactors."""
import unittest
from types import SimpleNamespace as NS
from bot import access

CFG = dict(leader_role_id=1, dep_leader_role_id=2, high_staff_role_id=3,
           recruiter_role_id=4, main_role_id=5, accepted_role_id=6,
           colombo_role_id=7, guest_role_id=8, role_schema_version=2)


def member(roles=(), uid=10, admin=False):
    return NS(id=uid, guild=NS(id=access.TIER_GUILD_ID, owner_id=99),
              get_role=lambda rid: rid if rid in roles else None,
              guild_permissions=NS(administrator=admin))


class AccessPolicy(unittest.TestCase):
    def test_matrix_including_admin_and_owner(self):
        for role in range(1, 9):
            m = member([role], admin=True)
            with self.subTest(role=role):
                for check in (access.may_recruit, access.may_review_reports, access.may_promote):
                    self.assertEqual(bool(check(m, CFG)), role <= 4)
                for check in (access.may_manage_events, access.may_view_profiles, access.may_review_vacation):
                    self.assertEqual(bool(check(m, CFG)), role <= 3)
                self.assertFalse(access.may_review_tiers(m, access.TIER_GUILD_ID))
        owner = member(uid=99)
        self.assertTrue(access.may_manage_events(owner, CFG))
        self.assertFalse(access.may_review_tiers(owner, access.TIER_GUILD_ID))
        checker = member([access.TIERCHECK_ROLE_ID])
        self.assertTrue(access.may_review_tiers(checker, access.TIER_GUILD_ID))
        self.assertFalse(access.may_review_tiers(checker, 123))

    def test_assignment_override_preserves_existing_rule(self):
        app = {'assigned_to': 11}
        for roles, uid, admin, expected in [([4],10,False,False),([4],11,False,True),
                ([3],10,False,False),([2],10,False,True),([4],10,True,True),([],10,True,False)]:
            with self.subTest(roles=roles, uid=uid, admin=admin):
                self.assertEqual(bool(access.may_decide_application(member(roles,uid,admin),CFG,app)),expected)

    def test_attendance_requires_organizer_or_leadership(self):
        event = {'creator_id': 11}
        self.assertFalse(access.may_confirm_attendance(member([3]), CFG, event))
        self.assertTrue(access.may_confirm_attendance(member([3], uid=11), CFG, event))
        self.assertFalse(access.may_confirm_attendance(member([4], uid=11), CFG, event))
        for roles, uid in [([1], 10), ([2], 10), ([], 99)]:
            self.assertTrue(access.may_confirm_attendance(member(roles, uid), CFG, event))

    def test_setup_name_lookup_only_before_configuration(self):
        resolver = lambda guild,key: NS(id=3) if key=='high_staff_role_id' else None
        self.assertTrue(access.may_setup(member([3]), {}, resolver))
        self.assertFalse(access.may_setup(member([3]), {'role_schema_version':2}, resolver))
        self.assertFalse(access.may_setup(member([4]), {}, resolver))
        self.assertFalse(access.may_setup(member(admin=True), {}, resolver))
