"""包级导出回归：业务/传输层通过 `from app import sessions/state` 调用，
符号必须在包 __init__ 上 re-export，避免 AttributeError。仅导入，不连数据库。"""
import unittest


class PackageExportTest(unittest.TestCase):
    def test_sessions_exports(self):
        from app import sessions

        for name in ("issue", "resolve", "revoke", "list_sessions"):
            self.assertTrue(callable(getattr(sessions, name)), name)

    def test_state_exports(self):
        from app import state

        for name in ("load", "save"):
            self.assertTrue(callable(getattr(state, name)), name)


if __name__ == "__main__":
    unittest.main()
