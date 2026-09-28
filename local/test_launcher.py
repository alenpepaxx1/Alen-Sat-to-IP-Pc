# Copyright © 2026 Alen Pepa.
import io
import json
import unittest
from unittest.mock import patch
import launcher
from runtime_identity import VERSION, INSTALLATION_ID

class LauncherTest(unittest.TestCase):
    def test_reuses_its_fallback_port(self):
        with patch.object(launcher, 'running_bridge', side_effect=lambda port: port == 8791) as probe:
            self.assertEqual(launcher.find_running_bridge(), 8791)
            self.assertEqual({call.args[0] for call in probe.call_args_list}, set(range(8787,8797)))

    def test_old_or_other_installations_are_not_reused(self):
        current = {'protocol':'alen-stb-bridge-v1','automatic':True,'version':VERSION,'installationId':INSTALLATION_ID}
        for changes, expected in [({},True),({'version':'0.5.0'},False),({'installationId':'another-copy'},False),({'protocol':'something-else'},False)]:
            with self.subTest(changes=changes), patch.object(launcher, 'build_opener') as opener:
                opener.return_value.open.return_value = io.BytesIO(json.dumps({**current, **changes}).encode())
                self.assertEqual(launcher.running_bridge(8788), expected)

    def test_main_opens_existing_service_without_starting_another(self):
        with patch.object(launcher, 'find_running_bridge', return_value=8790), patch.object(launcher.webbrowser, 'open') as browser:
            launcher.main([])
            browser.assert_called_once_with('http://127.0.0.1:8790/#connect')

    def test_lan_mode_does_not_reuse_loopback_only_bridge(self):
        value = {'protocol':'alen-stb-bridge-v1','automatic':True,'version':VERSION,'installationId':INSTALLATION_ID,'lanAvailable':False}
        with patch.object(launcher, 'build_opener') as opener:
            opener.return_value.open.return_value = io.BytesIO(json.dumps(value).encode())
            self.assertFalse(launcher.running_bridge(8787, True))

if __name__ == '__main__': unittest.main()
