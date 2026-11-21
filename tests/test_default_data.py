"""默认数据表要能「装到哪都能用」。

以前 `autoflux ask` 默认读仓库里的 `examples/...`：装成包、换个目录跑就找不到。
现在包里自带一份，并且解析不依赖当前目录。
"""
from __future__ import annotations

import os
import unittest
from argparse import Namespace
from pathlib import Path
from unittest import mock

from autoflux import cli
from autoflux.employment import Dataset, default_data_path

from . import ScratchCase

_REPO_COPY = Path(__file__).resolve().parents[1] / "examples/employment/data/wages_2025.csv"


class TestDefaultData(ScratchCase):
    def test_path_is_inside_the_package_and_exists(self):
        path = default_data_path()
        self.assertTrue(path.is_file())
        self.assertEqual(path.name, "wages_2025.csv")
        # 必须落在包目录里，而不是恰好命中了仓库里的 examples/
        self.assertIn("employment", path.parts)
        self.assertIn("data", path.parts)

    def test_same_content_as_repo_example(self):
        packaged = Dataset(default_data_path())
        repo = Dataset(_REPO_COPY)
        self.assertEqual(len(packaged.rows), 19)
        self.assertEqual(
            [r.name for r in packaged.rows], [r.name for r in repo.rows]
        )
        self.assertEqual(packaged.total.wage if packaged.total else 0, 129441)

    def test_resolves_outside_the_repo_directory(self):
        """把当前目录挪开：路径仍然有效（不是靠 cwd 碰运气）。"""
        old = os.getcwd()
        try:
            os.chdir(self.root)
            path = default_data_path()
            self.assertTrue(path.is_file())
            self.assertEqual(len(Dataset(path).rows), 19)
        finally:
            os.chdir(old)

    def test_ask_parser_no_longer_hardcodes_examples_path(self):
        args = cli._build_parser().parse_args(["ask", "--question", "最高的是哪个行业"])
        self.assertIsNone(args.data)

    def test_ask_without_data_uses_packaged_table(self):
        """不给 --data 也必须能跑起来——否则就是「装好了却不能问」。"""
        args = Namespace(
            chat=False,
            question="最高的行业是哪个",
            data=None,
            attempts=1,
            config="config.toml",
        )
        fake_result = {"answer": "信息传输、软件和信息技术服务业", "verified": True,
                       "problems": [], "attempts": 1}
        with (
            mock.patch.object(cli, "LLMAgent", return_value=object()),
            mock.patch.object(cli.qa, "ask", return_value=fake_result),
        ):
            self.assertEqual(cli._cmd_ask(args), 0)


if __name__ == "__main__":
    unittest.main()
