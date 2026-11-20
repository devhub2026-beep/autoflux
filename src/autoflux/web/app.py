"""FastAPI 后端：起一个 run，实时看 agent 每一步。

设计上只做三件事：
  1. 收「目标 + 起始目录 + 检查命令」，起一个线程跑 GraphEngine；
  2. 把 trace 事件按顺序吐给前端（增量拉取，offset）；
  3. 提供停止、技能库查询。

评测/反思/技能库的规矩在引擎里，这里不掺和业务判断。
"""
from __future__ import annotations

import json
import os
import sys
import threading
import time
import uuid
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, Field

from .. import config as config_mod
from ..agents.llm import LLMAgent, complete_fn
from ..checkpoint import SqliteSaver
from ..employment import Dataset, qa
from ..graph import GraphEngine
from ..reflector import LLMReflector
from ..skillbook import Skillbook
from ..stop import StopPolicy
from ..tasks.goal import GoalTask
from ..tools.fs import default_tools
from ..trace import Tracer

_INDEX = Path(__file__).with_name("index.html")


class WebTracer(Tracer):
    """写盘 + 进内存，前端靠内存这份做增量推送。"""

    def __init__(self, path: Path | None, sink: list[dict[str, Any]]) -> None:
        super().__init__(path)
        self._sink = sink
        self._lock = threading.Lock()

    def emit(self, kind: str, **fields: Any) -> None:
        super().emit(kind, **fields)
        record = {"t": round(time.time(), 4), "kind": kind, **fields}
        with self._lock:
            self._sink.append(record)


@dataclass
class RunState:
    id: str
    goal: str
    project: str
    check: str
    status: str = "running"
    error: str = ""
    summary: str = ""
    created: float = field(default_factory=time.time)
    events: list[dict[str, Any]] = field(default_factory=list)
    cancel: threading.Event = field(default_factory=threading.Event)
    result: str = ""


class RunRequest(BaseModel):
    goal: str = Field(min_length=1)
    project: str = ""
    check: str = ""
    max_steps: int = 40
    max_attempts: int = 5
    api_key: str = ""


class AskRequest(BaseModel):
    question: str = Field(min_length=1)
    data: str = ""
    attempts: int = 3
    api_key: str = ""
    # 多轮：前端把上一轮的问答原样带回来，追问才有上下文
    history: list[dict[str, str]] = Field(default_factory=list)


def _guess_check(project: Path) -> str:
    """带测试的项目就直接用 unittest 跑；猜不出来返回空串。"""
    try:
        names = {p.name for p in project.iterdir()}
    except OSError:
        return ""
    has_tests = "tests" in names or any(n.startswith("test_") and n.endswith(".py") for n in names)
    if has_tests:
        return f'"{sys.executable}" -m unittest discover -q'
    return ""


def _read_events(path: Path) -> list[dict[str, Any]]:
    """把 trace.jsonl 读成前端认识的事件列表；坏行直接跳过。"""
    if not path.is_file():
        return []
    events: list[dict[str, Any]] = []
    try:
        for raw_line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = raw_line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except ValueError:
                continue
            if isinstance(record, dict) and "kind" in record:
                events.append(record)
    except OSError:
        return []
    return events


def _final_from_state(path: Path) -> tuple[str, str]:
    """从 state.json 倒推一条历史 run 的结局，给列表用。"""
    fallback = ("stopped", "历史记录（没有 state.json）")
    if not path.is_file():
        return fallback
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return fallback
    attempts = raw.get("attempts") or []
    best = 0.0
    for item in attempts:
        total = int(item.get("total") or 1)
        best = max(best, int(item.get("passed") or 0) / max(1, total))
    steps = int(raw.get("step") or 0)
    status = "done" if best >= 1.0 else "stopped"
    summary = f"历史记录 · 尝试 {len(attempts)} 次 · {steps} 步 · 最好 {best:.2f}"
    reason = str(raw.get("stop_reason") or "").strip()
    if reason:
        summary += f"（{reason}）"
    return status, summary


class RunManager:
    def __init__(self, settings: config_mod.Settings, root: Path | None = None) -> None:
        self.settings = settings
        self.root = Path(root or Path.cwd() / "runs")
        self.runs: dict[str, RunState] = {}
        self._lock = threading.Lock()
        self._load_history()

    # -- 历史 ---------------------------------------------------------
    def _load_history(self) -> None:
        """把 runs/ 里之前跑过的 run 读回内存——服务重启不等于记录消失。"""
        if not self.root.is_dir():
            return
        for run_dir in sorted(self.root.iterdir()):
            if not run_dir.is_dir():
                continue
            meta_path = run_dir / "run.json"
            if not meta_path.is_file():
                continue
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            run_id = str(meta.get("run_id") or run_dir.name)
            if run_id in self.runs:
                continue
            status, summary = _final_from_state(run_dir / "state.json")
            try:
                created = run_dir.stat().st_mtime
            except OSError:
                created = time.time()
            self.runs[run_id] = RunState(
                id=run_id,
                goal=str(meta.get("goal") or ""),
                project=str(meta.get("project") or ""),
                check=str(meta.get("check") or ""),
                status=status,
                summary=summary,
                created=created,
                events=_read_events(run_dir / "trace.jsonl"),
            )

    # -- 对外 ---------------------------------------------------------
    def start(self, req: RunRequest) -> RunState:
        run_id = time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]
        state = RunState(
            id=run_id, goal=req.goal, project=req.project, check=req.check
        )
        with self._lock:
            self.runs[run_id] = state
        thread = threading.Thread(
            target=self._execute, args=(state, req), name=f"run-{run_id}", daemon=True
        )
        thread.start()
        return state

    def get(self, run_id: str) -> RunState:
        state = self.runs.get(run_id)
        if state is None:
            raise HTTPException(status_code=404, detail="没有这个 run")
        return state

    def stop(self, run_id: str) -> RunState:
        state = self.get(run_id)
        state.cancel.set()
        return state

    # -- 执行 ---------------------------------------------------------
    def _execute(self, state: RunState, req: RunRequest) -> None:
        run_dir = self.root / state.id
        workdir = run_dir / "work"
        try:
            run_dir.mkdir(parents=True, exist_ok=True)
            # 先把元信息落盘：进程中途死掉，重启后这条 run 还能从列表里点开
            (run_dir / "run.json").write_text(
                json.dumps(
                    {
                        "run_id": state.id,
                        "task": "goal",
                        "goal": req.goal,
                        "check": req.check,
                        "project": req.project,
                        "workdir": str(workdir),
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            if req.api_key:
                os.environ[self.settings.llm.api_key_env] = req.api_key

            task = GoalTask(
                goal=req.goal, check=req.check, source=Path(req.project)
            )
            tools = default_tools(workdir)
            agent = LLMAgent(
                self.settings.llm, mission=getattr(task, "brief", lambda: "")()
            )
            reflector = LLMReflector(complete_fn(self.settings.llm))
            tracer = WebTracer(run_dir / "trace.jsonl", state.events)

            limits = replace(
                self.settings.limits,
                max_steps=req.max_steps,
                max_attempts=req.max_attempts,
            )

            with Skillbook(self.settings.store) as book:
                saver = SqliteSaver(run_dir / "checkpoints.sqlite")
                engine = GraphEngine(
                    task=task,
                    agent=agent,
                    tools=tools,
                    reflector=reflector,
                    skillbook=book,
                    stop_policy=StopPolicy(limits),
                    tracer=tracer,
                    workdir=workdir,
                    thread_id=state.id,
                    checkpointer=saver,
                    snapshot_path=run_dir / "state.json",
                )
                try:
                    result = engine.run(should_stop=state.cancel.is_set)
                finally:
                    saver.close()

            state.summary = result.summary()
            state.result = result.curve()
            state.status = "done"
        except Exception as exc:
            state.error = f"{type(exc).__name__}: {exc}"
            state.status = "error"
        finally:
            state.events.append({"kind": "end", "status": state.status})


def create_app(
    settings: config_mod.Settings | None = None,
    root: Path | None = None,
) -> FastAPI:
    settings = settings or config_mod.load(Path("config.toml"))
    manager = RunManager(settings, root=root)
    app = FastAPI(title="autoflux", version="0.6.0")
    app.state.manager = manager

    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        return _INDEX.read_text(encoding="utf-8")

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        return {"ok": True, "runs": len(manager.runs)}

    @app.post("/api/runs")
    def start_run(req: RunRequest) -> JSONResponse:
        if not req.goal.strip():
            raise HTTPException(status_code=400, detail="目标不能是空的")

        # 起始目录可以留空：自动开一个空目录，不用你去找
        project = Path(req.project.strip()) if req.project.strip() else None
        if project is None:
            project = manager.root / "sandbox"
            project.mkdir(parents=True, exist_ok=True)
        if not project.is_dir():
            raise HTTPException(status_code=400, detail=f"起始目录不存在：{project}")

        # 判定命令也可以留空：认得 pytest/unittest 的项目就自动生成
        check = req.check.strip() or _guess_check(project)
        if not check:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"判定命令留空时，我只认得带测试的项目；{project} 里没找到测试。"
                    "写一条能判对错的命令，例如 findstr /X /C:42 a.txt"
                ),
            )

        req.project = str(project)
        req.check = check
        state = manager.start(req)
        return JSONResponse({"id": state.id, "project": req.project, "check": req.check})

    @app.get("/api/runs")
    def list_runs() -> dict[str, Any]:
        with manager._lock:
            rows = [
                {
                    "id": s.id,
                    "goal": s.goal,
                    "status": s.status,
                    "created": s.created,
                    "summary": s.summary,
                }
                for s in sorted(manager.runs.values(), key=lambda s: s.created, reverse=True)
            ]
        return {"runs": rows}

    @app.get("/api/runs/{run_id}")
    def run_detail(run_id: str, after: int = 0) -> dict[str, Any]:
        state = manager.get(run_id)
        events = state.events[after:]
        return {
            "id": state.id,
            "status": state.status,
            "error": state.error,
            "summary": state.summary,
            "goal": state.goal,
            "project": state.project,
            "check": state.check,
            "next": after + len(events),
            "events": events,
        }

    @app.post("/api/runs/{run_id}/stop")
    def stop_run(run_id: str) -> dict[str, Any]:
        state = manager.stop(run_id)
        return {"id": state.id, "stopping": True}

    @app.get("/api/skills")
    def skills() -> dict[str, Any]:
        try:
            with Skillbook(settings.store) as book:
                rows = book.all()
        except Exception as exc:
            return {"skills": [], "error": str(exc)}
        return {
            "skills": [
                {"id": ident, "text": text, "uses": uses, "wins": wins}
                for ident, text, uses, wins in rows
            ]
        }

    @app.post("/api/ask")
    def ask(req: AskRequest) -> dict[str, Any]:
        """数据问答：答案里的数字由 verify() 把关，编了就打回重写。

        和 /api/runs 不是一回事——这条路径不跑动作循环，只跑「写 → 核 → 重写」。
        """
        data = Path(req.data.strip()) if req.data.strip() else Path(
            "examples/employment/data/wages_2025.csv"
        )
        if not data.is_file():
            raise HTTPException(status_code=400, detail=f"找不到数据表：{data}")
        if req.api_key:
            os.environ[settings.llm.api_key_env] = req.api_key

        ds = Dataset(data)
        try:
            agent = LLMAgent(settings.llm)
        except RuntimeError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        history = [
            {"role": str(t.get("role", "user")), "content": str(t.get("content", ""))}
            for t in req.history
            if str(t.get("role", "")) in ("user", "assistant")
        ]
        result = qa.ask(
            agent, ds, req.question, history=history, attempts=max(1, req.attempts)
        )
        turns = [
            *history,
            {"role": "user", "content": req.question},
            {"role": "assistant", "content": result["answer"]},
        ]
        return {
            "answer": result["answer"],
            "verified": result["verified"],
            "problems": result["problems"],
            "attempts": result["attempts"],
            "history": turns,
        }

    return app


def serve(host: str = "127.0.0.1", port: int = 8765) -> None:
    import uvicorn

    app = create_app()
    print(f"autoflux  →  http://{host}:{port}")
    uvicorn.run(app, host=host, port=port, log_level="warning")
