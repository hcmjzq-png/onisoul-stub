"""Fail-closed profile selection and exact-owned-process identity checks."""
import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch
from tools.game_environments import Environments, same_process, validate_health


class GameEnvironmentsTest(unittest.TestCase):
    def test_local_cache_refresh_preserves_other_assets_and_cloud_cache(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            cache = root / 'Client/cache/data7'
            cache.mkdir(parents=True)
            cloud = root / 'Cloud/cache'
            cloud.mkdir(parents=True)
            url = b'http://client-onisoul.86joy.com/client/pc/jp/assets/pbm/' + b'a' * 32 + b'.unity3d?r=0'
            (cache / 'background.d').write_bytes(b'Qt-header' + url + b'\0body')
            (cache / 'portrait.d').write_bytes(url.replace(b'/pbm/', b'/chara/'))
            (cloud / 'background.d').write_bytes(url)
            manager = object.__new__(Environments)
            manager.root = root
            manager.settings = {'local_client': str(root / 'Client')}
            self.assertEqual(manager.clear_local_background_cache(), 1)
            self.assertFalse((cache / 'background.d').exists())
            self.assertTrue((cache / 'portrait.d').exists())
            self.assertTrue((cloud / 'background.d').exists())
            manager.settings['local_client'] = str(root / 'Cloud')
            with self.assertRaises(RuntimeError):
                manager.clear_local_background_cache()

    def test_port_or_up_status_cannot_substitute_for_server_identity(self):
        for payload in ({'service': 'onisoul-stub', 'status': 'up'},
            {'service': 'onisoul-stub', 'status': 'up', 'environment': 'cloud', 'instance_id': 'other'},
            {'service': 'onisoul-stub', 'status': 'up', 'environment': 'local-test', 'instance_id': 'expected'}):
            with self.subTest(payload=payload), self.assertRaises(RuntimeError):
                validate_health(payload, 'cloud', 'expected')
        validate_health({'service': 'onisoul-stub', 'status': 'up', 'environment': 'cloud', 'instance_id': 'expected'}, 'cloud', 'expected')

    def test_reused_pid_different_executable_or_creation_is_not_owned(self):
        record = dict(pid=123, executable='C:/Python/python.exe', creation_100ns=23456)
        self.assertTrue(same_process(record, dict(record)))
        self.assertFalse(same_process(record, None))
        self.assertFalse(same_process(record, {**record, 'creation_100ns': 23457}))
        self.assertFalse(same_process(record, {**record, 'executable': 'C:/Other/python.exe'}))

    def test_open_client_prevents_switch_before_any_backend_or_gateway_change(self):
        manager = object.__new__(Environments)
        with patch('tools.game_environments.game_processes', return_value=[{'pid': 1}]), \
                patch.object(manager, 'live', return_value={'role': 'cloud'}), \
                patch.object(manager, 'backend') as backend, \
                patch.object(manager, 'stop') as stop, \
                self.assertRaisesRegex(RuntimeError, '关闭游戏'):
            manager.select('local-test')
        backend.assert_not_called()
        stop.assert_not_called()
