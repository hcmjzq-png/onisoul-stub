"""Fail-closed profile selection and exact-owned-process identity checks."""
import unittest
from unittest.mock import patch
from tools.game_environments import Environments, same_process, validate_health


class GameEnvironmentsTest(unittest.TestCase):
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
