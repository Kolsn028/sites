import unittest
from unittest.mock import patch,AsyncMock
from types import SimpleNamespace as NS
from bot.uninstall import select_configured,Uninstaller

class RemovalScope(unittest.IsolatedAsyncioTestCase):
    def test_configured_objects_only_no_managed_or_everyone_roles(self):
        roles=[NS(id=1,managed=False,is_default=lambda:False),NS(id=2,managed=True,is_default=lambda:False),NS(id=3,managed=False,is_default=lambda:True),NS(id=4,managed=False,is_default=lambda:False)]
        cfg={'leader_role_id':1,'other_role_id':2,'base_role_id':3,'case_panel_channel_id':10,'family_category_id':11,'interview_voice_2_id':12,'message_id':13}
        channels,selected=select_configured(cfg,[NS(id=i) for i in range(10,15)],roles)
        self.assertEqual(channels,{10,11,12});self.assertEqual(selected,{1})
    async def test_manifest_for_other_guild_never_fetches_or_mutates(self):
        client=NS(user=NS(id=9));guild=NS(id=100,fetch_channels=AsyncMock(),leave=AsyncMock())
        with patch.dict('os.environ',{'COLOMBO_UNINSTALL_MANIFEST':'{"guild_id":200,"bot_id":9}'}):
            with self.assertRaises(ValueError):await Uninstaller.remove(client,guild)
        guild.fetch_channels.assert_not_awaited();guild.leave.assert_not_awaited()
