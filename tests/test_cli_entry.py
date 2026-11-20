from __future__ import annotations

import unittest

from autoflux.cli import _normalize_argv


class TestCliEntry(unittest.TestCase):
    def test_empty_argv_defaults_to_run(self):
        # PyCharm 点绿三角就是这个场景：不带任何参数
        self.assertEqual(_normalize_argv([]), ["run"])

    def test_explicit_argv_untouched(self):
        self.assertEqual(_normalize_argv(["tasks"]), ["tasks"])
        self.assertEqual(_normalize_argv(["run", "--task", "bugfix"]), ["run", "--task", "bugfix"])
        self.assertEqual(_normalize_argv(["--help"]), ["--help"])


if __name__ == "__main__":
    unittest.main()
