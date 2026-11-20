"""跑批这一层：任务规格读得对、汇总数字算得对。"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from autoflux import bench
from autoflux.bench import load_task_specs, run_once, summarize
from autoflux.config import load as load_config


class BenchTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        (self.root / "tasks").mkdir()

    def _task(self, name: str, check: str = "{python} -m unittest -q") -> None:
        d = self.root / "tasks" / name
        (d / "project").mkdir(parents=True)
        (d / "task.json").write_text(
            json.dumps({"goal": f"修好 {name}", "check": check}), encoding="utf-8"
        )

    def test_loads_specs_and_expands_python(self) -> None:
        self._task("alpha")
        self._task("beta")
        specs = load_task_specs(self.root, None)
        self.assertEqual([s["name"] for s in specs], ["alpha", "beta"])
        self.assertIn(sys.executable, specs[0]["check"])
        self.assertNotIn("{python}", specs[0]["check"])
        self.assertTrue(Path(specs[0]["source"]).is_dir())

    def test_loads_only_named_tasks(self) -> None:
        self._task("alpha")
        self._task("beta")
        specs = load_task_specs(self.root, ["beta"])
        self.assertEqual([s["name"] for s in specs], ["beta"])

    def test_unknown_task_raises(self) -> None:
        self._task("alpha")
        with self.assertRaises(RuntimeError):
            load_task_specs(self.root, ["nope"])

    def test_missing_bench_dir_raises(self) -> None:
        with self.assertRaises(RuntimeError):
            load_task_specs(self.root / "nope", None)

    def test_summarize_counts(self) -> None:
        rows = [
            {"task": "a", "success": True, "steps": 5, "seconds": 10.0,
             "reflections": 0, "stop_reason": "达标"},
            {"task": "a", "success": False, "steps": 20, "seconds": 30.0,
             "reflections": 1, "stop_reason": "步数用尽（30）"},
            {"task": "b", "success": True, "steps": 7, "seconds": 20.0,
             "reflections": 2, "stop_reason": "达标"},
        ]
        total = summarize(rows)
        self.assertEqual(total["overall"]["n"], 3)
        self.assertEqual(total["overall"]["success"], 2)
        self.assertAlmostEqual(total["overall"]["success_rate"], 2 / 3, places=3)
        self.assertEqual(total["by_task"]["a"]["n"], 2)
        self.assertEqual(total["by_task"]["a"]["success"], 1)
        self.assertEqual(total["failure_reasons"], {"步数用尽": 1})

    def test_summarize_empty(self) -> None:
        total = summarize([])
        self.assertEqual(total["overall"]["n"], 0)
        self.assertEqual(total["overall"].get("success", 0), 0)

    # -- 真正跑一遍 CLI（模型换成假的，一次不花钱） --------------------
    def _row(self, success: bool) -> dict:
        return {
            "task": "alpha",
            "success": success,
            "best": 1.0 if success else 0.0,
            "steps": 5,
            "seconds": 1.2,
            "reflections": 0,
            "attempts": 1,
            "stop_reason": "达标" if success else "步数用尽（4）",
            "curve": [1.0] if success else [0.0],
            "plan_done": 0,
            "plan_total": 0,
        }

    def test_main_writes_result_json_and_returns_zero(self) -> None:
        self._task("alpha")
        out = self.root / "out.json"
        with patch("autoflux.bench.run_once", return_value=self._row(True)):
            code = bench.main(
                [
                    "--tasks", "alpha",
                    "--bench", str(self.root),
                    "--out", str(out),
                    "--repeats", "1",
                    "--config", str(self.root / "none.toml"),
                    "--workdir", str(self.root / "ws"),
                ]
            )
        self.assertEqual(code, 0)
        data = json.loads(out.read_text(encoding="utf-8"))
        self.assertEqual(data["summary"]["overall"]["success"], 1)
        self.assertEqual(data["rows"][0]["task"], "alpha")

    def test_main_returns_one_when_all_failed(self) -> None:
        self._task("alpha")
        out = self.root / "out.json"
        with patch("autoflux.bench.run_once", return_value=self._row(False)):
            code = bench.main(
                [
                    "--tasks", "alpha",
                    "--bench", str(self.root),
                    "--out", str(out),
                    "--config", str(self.root / "none.toml"),
                    "--workdir", str(self.root / "ws"),
                ]
            )
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(out.read_text(encoding="utf-8"))["summary"]["failure_reasons"], {"步数用尽": 1})

    def test_run_once_records_crash_instead_of_raising(self) -> None:
        self._task("alpha")
        spec = load_task_specs(self.root, ["alpha"])[0]
        cfg = load_config(None)

        class BoomEngine:
            def __init__(self, *args, **kwargs) -> None:
                pass

            def run(self, *args, **kwargs):
                raise RuntimeError("boom")

        with patch("autoflux.bench.LLMAgent", lambda *a, **k: object()), \
                patch("autoflux.bench.complete_fn", lambda *a, **k: (lambda p: "x")), \
                patch("autoflux.bench.GraphEngine", BoomEngine):
            row = run_once(
                spec,
                cfg,
                workdir=self.root / "ws",
                trace_path=self.root / "trace.jsonl",
                store=str(self.root / "skills.db"),
                max_steps=3,
            )
        self.assertFalse(row["success"])
        self.assertIn("崩了", row["stop_reason"])
        self.assertEqual(row["attempts"], 0)


if __name__ == "__main__":
    unittest.main()
