"""网页层的测试：只碰不花钱的部分。"""
from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from autoflux.config import Settings
from autoflux.web.app import create_app

from . import ScratchCase

ROOT = Path(__file__).resolve().parents[1]
WAGES = ROOT / "examples" / "employment" / "data" / "wages_2025.csv"


class TestWebApi(ScratchCase):
    def setUp(self) -> None:
        super().setUp()
        self.cfg = replace(Settings(), store=str(self.root / "state.db"))
        self.client = TestClient(create_app(self.cfg, root=self.root))
        self.runs_root = self.root

    def test_index_served(self):
        r = self.client.get("/")
        self.assertEqual(r.status_code, 200)
        self.assertIn("autoflux", r.text.lower())
        self.assertIn("<script", r.text)
        # 历史列表和「问数据」入口都得在页面上
        self.assertIn('id="history"', r.text)
        self.assertIn('id="ask_btn"', r.text)

    def test_health(self):
        r = self.client.get("/api/health")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["ok"])

    def test_runs_starts_empty(self):
        r = self.client.get("/api/runs")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["runs"], [])

    def test_reject_missing_project(self):
        r = self.client.post(
            "/api/runs",
            json={"goal": "让它通过", "project": str(self.root / "没有这个目录"), "check": "true"},
        )
        self.assertEqual(r.status_code, 400)
        self.assertIn("起始目录", r.json()["detail"])

    def test_reject_blank_goal(self):
        r = self.client.post(
            "/api/runs",
            json={"goal": "   ", "project": str(self.root), "check": "true"},
        )
        self.assertEqual(r.status_code, 400)

    def test_blank_project_gets_sandbox(self):
        r = self.client.post(
            "/api/runs",
            json={"goal": "建一个 note.txt", "check": "true", "api_key": "k"},
        )
        self.assertEqual(r.status_code, 200, r.text)
        self.assertTrue(r.json()["project"].endswith("sandbox"))
        self.assertTrue(Path(r.json()["project"]).is_dir())

    def test_blank_check_guesses_unittest(self):
        project = self.root / "withtests"
        project.mkdir()
        (project / "test_x.py").write_text("", encoding="utf-8")
        r = self.client.post(
            "/api/runs",
            json={"goal": "让它通过", "project": str(project), "api_key": "k"},
        )
        self.assertEqual(r.status_code, 200, r.text)
        self.assertIn("unittest", r.json()["check"])

    def test_blank_check_without_tests_is_rejected(self):
        project = self.root / "notests"
        project.mkdir()
        r = self.client.post(
            "/api/runs",
            json={"goal": "让它通过", "project": str(project), "api_key": "k"},
        )
        self.assertEqual(r.status_code, 400)
        self.assertIn("判定命令", r.json()["detail"])

    def test_skills_empty(self):
        r = self.client.get("/api/skills")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["skills"], [])

    def test_ask_rejects_missing_table(self):
        r = self.client.post(
            "/api/ask",
            json={"question": "全国平均多少？", "data": str(self.root / "没有这个表.csv")},
        )
        self.assertEqual(r.status_code, 400)
        self.assertIn("找不到数据表", r.json()["detail"])

    def test_ask_returns_history_and_drops_unknown_roles(self):
        fake = {"answer": "全国合计 129441 元。", "verified": True, "problems": [], "attempts": 1}
        with patch("autoflux.web.app.LLMAgent", lambda *a, **k: object()), \
                patch("autoflux.web.app.qa.ask", return_value=fake) as spy:
            r = self.client.post(
                "/api/ask",
                json={
                    "question": "全国平均多少？",
                    "data": str(WAGES),
                    "history": [
                        {"role": "user", "content": "上一问"},
                        {"role": "assistant", "content": "上一答"},
                        {"role": "system", "content": "不该进来的角色"},
                    ],
                },
            )
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertEqual(len(body["history"]), 4)
        self.assertEqual(body["history"][-1], {"role": "assistant", "content": fake["answer"]})
        passed = spy.call_args.kwargs["history"]
        self.assertEqual([t["role"] for t in passed], ["user", "assistant"])

    # -- 历史：重启之后还能看见以前的 run ------------------------------
    def _write_run(self, run_id: str, passed: int = 1, total: int = 1) -> Path:
        d = self.runs_root / run_id
        d.mkdir()
        (d / "run.json").write_text(
            json.dumps(
                {
                    "run_id": run_id,
                    "task": "goal",
                    "goal": "建一个 hello.txt",
                    "check": "true",
                    "project": str(self.root),
                    "workdir": str(d / "work"),
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        (d / "state.json").write_text(
            json.dumps(
                {
                    "step": 4,
                    "attempts": [{"attempt": 1, "passed": passed, "total": total, "steps": 3, "reflections": 0}],
                    "stop_reason": "达标" if passed >= total else "步数用尽",
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        (d / "trace.jsonl").write_text(
            json.dumps({"kind": "action", "step": 0, "action": "submit"}, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        return d

    def test_history_survives_restart(self):
        self._write_run("20260101-000000-aaaaaa")
        fresh = TestClient(create_app(self.cfg, root=self.root))   # 模拟重启
        runs = fresh.get("/api/runs").json()["runs"]
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0]["status"], "done")
        self.assertIn("hello.txt", runs[0]["goal"])

        detail = fresh.get("/api/runs/20260101-000000-aaaaaa").json()
        self.assertEqual(detail["status"], "done")
        self.assertEqual(len(detail["events"]), 1)
        self.assertIn("历史记录", detail["summary"])

    def test_history_marks_unfinished_run(self):
        self._write_run("20260101-000000-bbbbbb", passed=0, total=1)
        fresh = TestClient(create_app(self.cfg, root=self.root))
        row = fresh.get("/api/runs").json()["runs"][0]
        self.assertEqual(row["status"], "stopped")

    def test_folders_without_run_json_are_ignored(self):
        (self.root / "bench").mkdir()
        (self.root / "bench" / "calc-1").mkdir()
        fresh = TestClient(create_app(self.cfg, root=self.root))
        self.assertEqual(fresh.get("/api/runs").json()["runs"], [])
