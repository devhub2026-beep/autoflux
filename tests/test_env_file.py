"""`.env` 这条补丁的契约测试：绿三角能跑，靠的就是它。"""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from autoflux.agents.llm import _load_env_file
from autoflux.config import LLMSettings


class EnvFileTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)
        self._old = os.getcwd()
        os.chdir(self.dir)
        self.addCleanup(os.chdir, self._old)
        os.environ.pop("AUTOFLUX_TEST_KEY", None)
        self.addCleanup(os.environ.pop, "AUTOFLUX_TEST_KEY", None)

    def test_reads_key_from_dotenv(self) -> None:
        (self.dir / ".env").write_text("AUTOFLUX_TEST_KEY=sk-abc\n", encoding="utf-8")
        _load_env_file()
        self.assertEqual(os.environ["AUTOFLUX_TEST_KEY"], "sk-abc")

    def test_does_not_override_existing(self) -> None:
        os.environ["AUTOFLUX_TEST_KEY"] = "from-shell"
        (self.dir / ".env").write_text("AUTOFLUX_TEST_KEY=from-file\n", encoding="utf-8")
        _load_env_file()
        self.assertEqual(os.environ["AUTOFLUX_TEST_KEY"], "from-shell")

    def test_ignores_comments_blanks_and_quotes(self) -> None:
        (self.dir / ".env").write_text(
            "# 注释\n\nAUTOFLUX_TEST_KEY='sk-quoted'\nNONSENSE LINE\n",
            encoding="utf-8",
        )
        _load_env_file()
        self.assertEqual(os.environ["AUTOFLUX_TEST_KEY"], "sk-quoted")

    def test_missing_file_is_not_an_error(self) -> None:
        _load_env_file()  # 没有 .env 也不能炸
        self.assertFalse(os.environ.get("AUTOFLUX_TEST_KEY"))

    def test_agent_picks_key_up_from_dotenv(self) -> None:
        (self.dir / ".env").write_text("AUTOFLUX_TEST_KEY=sk-ok\n", encoding="utf-8")
        settings = LLMSettings(api_key_env="AUTOFLUX_TEST_KEY")
        from autoflux.agents.llm import LLMAgent

        agent = LLMAgent(settings)
        self.assertEqual(agent._key, "sk-ok")


if __name__ == "__main__":
    unittest.main()
