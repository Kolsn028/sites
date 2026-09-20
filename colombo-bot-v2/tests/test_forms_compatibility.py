"""Existing Discord messages must keep working after moving their handlers."""
import importlib
import unittest

from bot import views


class PersistentFormsTests(unittest.IsolatedAsyncioTestCase):
    async def test_existing_message_component_ids_still_register(self):
        expected = {
            'ApplicationPanelView': ['colombo:application:open', 'colombo:application:mine'],
            'RecruiterActionView': ['colombo:recruiter:claim', 'colombo:recruiter:release', 'colombo:recruiter:action'],
            'VacationPanelView': ['colombo:vacation:open', 'colombo:vacation:return'],
            'VacationDecisionView': ['colombo:vacation:approve', 'colombo:vacation:reject'],
            'CasePanelView': ['colombo:case:open'],
            'ActivityClassifyView': ['colombo:activity:type'],
            'ActivityReviewView': ['colombo:activity:approve', 'colombo:activity:reject', 'colombo:activity:reclassify'],
        }
        registered = []
        for name, ids in expected.items():
            with self.subTest(view=name):
                view = getattr(views, name)(None)
                self.assertTrue(view.is_persistent())
                self.assertEqual([item.custom_id for item in view.children], ids)
                registered.extend(ids)
        self.assertEqual(len(registered), len(set(registered)))

    async def test_old_imports_refer_to_the_same_handlers(self):
        groups = {
            'applications': ['ApplicationModal', 'ApplicationPanelView', 'RecruiterActionSelect', 'RecruiterActionView'],
            'vacations': ['VacationModal', 'VacationPanelView', 'VacationDecisionView'],
            'cases': ['CasePanelView'],
            'activities': ['ActivityTypeSelect', 'ActivityClassifyView', 'RejectActivityModal', 'ActivityReviewView'],
        }
        for module_name, names in groups.items():
            module = importlib.import_module('bot.forms.' + module_name)
            for name in names:
                with self.subTest(handler=name):
                    self.assertIs(getattr(views, name), getattr(module, name))
