"""LangGraph 版引擎：一个环，没有阶段序列。

循环由 LangGraph 的图驱动，于是白拿两样东西：
  1. checkpointer：每一步的状态快照，可以中断、可以续跑、可以回放；
  2. 图本身：能画出「agent 这一步为什么走到了这里」。

决策权仍在 agent 手里：decide 节点的出边由它**当场**选的动作决定，
没有任何「先规划再执行再反思」的固定链。连「计划」也不是必经阶段——
它是 agent 可选的一个动作（kind="plan"），想写就写、想改就改。

三条硬规矩不变：
  - 分数只来自 task.evaluate()，模型改不了；
  - 没有评测信号不许反思；
  - 反思必须换到东西（诊断/规则），否则模型不会选它。

另外引擎会自己算一条 note 塞进观察里：重复同一个动作、长时间没有新的评测、
一直没有计划——这些是「卡住了」的客观迹象，agent 有权无视，但它看得到。
"""
from __future__ import annotations

import json
import time
import traceback
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any, TypedDict

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from .protocols import Agent, Reflector, Task, Tool
from .skillbook import Skillbook
from .stop import StopPolicy
from .trace import Tracer
from .types import Action, AttemptRecord, Observation, RunResult, Score
from .usage import Meter, Usage

MAX_TOOL_OUTPUT = 4000
MAX_HISTORY_ENTRY = 2000
MAX_RECENT_CHARS = 6000

# 「卡住了」的判定阈值。全是客观计数，不猜语义。
REPEAT_NUDGE = 3  # 同一个动作重复几次开始提醒
STALL_NUDGE = 8  # 多少步没有新评测就提醒
PLAN_NUDGE = 6  # 多少步还没写过计划就提醒
PLAN_TICK_NUDGE = 4  # 计划有多项没划勾，走到第几步开始提醒


class FluxState(TypedDict, total=False):
    """一次 run 的全部状态。它就是 checkpointer 存的东西。"""

    history: list[str]
    step: int
    attempt: int
    reflections: int
    ratios: list[float]
    attempts: list[dict[str, Any]]
    last_score: dict[str, Any] | None
    pending: dict[str, Any] | None
    stop_reason: str
    finished: bool
    plan: list[list[Any]]
    action_seq: list[str]
    last_progress_step: int
    started_at: float


def _score_from(state: FluxState) -> Score | None:
    raw = state.get("last_score")
    if not raw:
        return None
    return Score(int(raw["passed"]), int(raw["total"]), tuple(raw.get("details") or ()))


class GraphEngine:
    """把「感知 → 决策 → 行动 → 反馈」直接画成图。"""

    def __init__(
        self,
        *,
        task: Task,
        agent: Agent,
        tools: Sequence[Tool],
        reflector: Reflector,
        skillbook: Skillbook,
        stop_policy: StopPolicy,
        tracer: Tracer,
        workdir: Path,
        thread_id: str = "main",
        checkpointer: Any | None = None,
        snapshot_path: Path | None = None,
        meter: Meter | None = None,
    ) -> None:
        self.task = task
        self.agent = agent
        self.tools = list(tools)
        self.reflector = reflector
        self.skillbook = skillbook
        self.stop = stop_policy
        self.tracer = tracer
        self.workdir = Path(workdir)
        self.thread_id = thread_id
        self.checkpointer = checkpointer or MemorySaver()
        self.snapshot_path = snapshot_path
        # agent 和 reflector 用同一个 meter 记账；引擎只负责把账摆到结果里
        self.meter = meter
        self._seen: dict[str, tuple[int, str]] = {}
        self._should_stop: Callable[[], bool] | None = None

    # -- 图 -----------------------------------------------------------
    def build(self):
        g = StateGraph(FluxState)
        g.add_node("guard", self._guard)
        g.add_node("decide", self._decide)
        g.add_node("act", self._act)
        g.add_node("plan", self._plan)
        g.add_node("reflect", self._reflect)
        g.add_node("judge", self._judge)

        g.add_edge(START, "guard")
        g.add_conditional_edges(
            "guard", self._after_guard, {"decide": "decide", "end": END}
        )
        g.add_conditional_edges(
            "decide",
            self._route,
            {
                "act": "act",
                "plan": "plan",
                "reflect": "reflect",
                "judge": "judge",
                "end": END,
            },
        )
        g.add_edge("act", "guard")
        g.add_edge("plan", "guard")
        g.add_edge("reflect", "guard")
        g.add_edge("judge", "guard")
        return g.compile(checkpointer=self.checkpointer)

    # -- 节点 ---------------------------------------------------------
    def _guard(self, state: FluxState) -> FluxState:
        self._snapshot(state)
        attempts = list(state.get("ratios") or [])
        steps = int(state.get("step") or 0)
        elapsed = time.time() - float(state.get("started_at") or time.time())

        if self._should_stop is not None and self._should_stop():
            return {"stop_reason": "被外部停止", "finished": True}

        reason = self.stop.check(
            attempts=attempts, steps_used=steps, elapsed=elapsed
        )
        if reason is not None:
            return {"stop_reason": reason, "finished": True}
        return {}

    def _decide(self, state: FluxState) -> FluxState:
        skills = self.skillbook.skills()
        obs = Observation(
            step=int(state.get("step") or 0),
            attempt=int(state.get("attempt") or 1),
            recent=self._recent(list(state.get("history") or [])),
            workspace=self._listing(),
            skills=tuple(skills),
            last_signal=_score_from(state),
            plan=self._plan_view(state),
            note=self._note(state),
        )
        action = self.agent.decide(obs, self.tools, obs.skills)
        self.tracer.emit(
            "action",
            step=obs.step,
            attempt=obs.attempt,
            action=action.describe(),
        )
        out: FluxState = {"pending": _action_to_dict(action)}
        if action.kind == "stop":
            # agent 自己喊停：理由要留在结果里，不能悄悄变成「自然结束」
            out["stop_reason"] = action.text.strip() or "agent 决定停下"
        return out

    def _act(self, state: FluxState) -> FluxState:
        action = _action_from(state.get("pending"))
        result = self._run_tool(action)
        history = list(state.get("history") or [])
        step = int(state.get("step") or 0)
        self._record(history, step, action, result)
        self.tracer.emit("tool", name=action.name, result=result[:1000])
        return {
            "history": history,
            "step": step + 1,
            "pending": None,
            "action_seq": self._push_seq(state, action.describe()),
        }

    def _plan(self, state: FluxState) -> FluxState:
        """agent 给自己定计划，或把某一项划掉。不是引擎强加的阶段。"""
        action = _action_from(state.get("pending"))
        raw = action.args.get("steps") if isinstance(action.args, dict) else action.args
        steps = _normalize_steps(raw)
        history = list(state.get("history") or [])
        step = int(state.get("step") or 0)
        rendered = "；".join(
            f"{'[x]' if done else '[ ]'} {text}" for text, done in steps
        ) or "（空）"
        history.append(f"[计划] {rendered}")
        self.tracer.emit("plan", steps=[{"text": t, "done": d} for t, d in steps])
        return {
            "history": history,
            "plan": [[t, d] for t, d in steps],
            "step": step + 1,
            "pending": None,
            "action_seq": self._push_seq(state, action.describe()),
        }

    def _reflect(self, state: FluxState) -> FluxState:
        history = list(state.get("history") or [])
        step = int(state.get("step") or 0)
        score = _score_from(state)

        if score is None:
            history.append("[反思] 跳过：还没有任何评测信号，无依据可反思")
            self.tracer.emit("reflect_skipped", reason="no_signal")
            return {
                "history": history,
                "step": step + 1,
                "pending": None,
                "action_seq": self._push_seq(state, "reflect"),
            }

        diagnosis = self._diagnose()
        text = self.reflector.reflect(
            score,
            self._recent(history),
            tuple(self.skillbook.skills()),
            diagnosis=diagnosis,
        )
        added = self.skillbook.add(text)
        pruned = self.skillbook.prune()
        history.append(
            f"[反思] {text}" + ("" if added else "（与已有规则重复，未入库）")
        )
        if pruned:
            history.append(f"[清理] 淘汰了 {pruned} 条从不奏效 / 超出上限的旧规则")
        if diagnosis:
            history.append(f"[诊断] {diagnosis[:600]}")
        self.tracer.emit(
            "reflect",
            text=text,
            stored=added is not None,
            pruned=pruned,
            diagnosis=diagnosis[:2000],
        )
        return {
            "history": history,
            "step": step + 1,
            "reflections": int(state.get("reflections") or 0) + 1,
            "pending": None,
            "action_seq": self._push_seq(state, "reflect"),
        }

    def _judge(self, state: FluxState) -> FluxState:
        score = self.task.evaluate(self.workdir)
        ratios = list(state.get("ratios") or [])
        prev_best = max(ratios, default=-1.0)
        ratios.append(score.ratio)

        attempts = list(state.get("attempts") or [])
        attempts.append(
            {
                "attempt": int(state.get("attempt") or 1),
                "passed": score.passed,
                "total": score.total,
                "steps": int(state.get("step") or 0),
                "reflections": int(state.get("reflections") or 0),
            }
        )

        history = list(state.get("history") or [])
        history.append(f"[评测] {score}")
        self.tracer.emit(
            "eval",
            attempt=int(state.get("attempt") or 1),
            passed=score.passed,
            total=score.total,
            ratio=score.ratio,
        )
        if score.ratio > prev_best:
            self.skillbook.bump_win(self.skillbook.last_ids())

        step = int(state.get("step") or 0)
        return {
            "history": history,
            "ratios": ratios,
            "attempts": attempts,
            "last_score": {
                "passed": score.passed,
                "total": score.total,
                "details": list(score.details),
            },
            "step": step + 1,
            "attempt": int(state.get("attempt") or 1) + 1,
            "pending": None,
            # 每次提交都算一次「有进展」的观察点：至少知道了现在的分数。
            "last_progress_step": step,
            "action_seq": self._push_seq(state, "submit"),
        }

    # -- 边 -----------------------------------------------------------
    def _after_guard(self, state: FluxState) -> str:
        return "end" if state.get("finished") else "decide"

    def _route(self, state: FluxState) -> str:
        kind = (state.get("pending") or {}).get("kind")
        return {
            "tool": "act",
            "plan": "plan",
            "reflect": "reflect",
            "submit": "judge",
            "stop": "end",
        }.get(str(kind), "end")

    # -- 运行 ---------------------------------------------------------
    def run(
        self,
        should_stop: Callable[[], bool] | None = None,
        resume_state: dict[str, Any] | None = None,
    ) -> RunResult:
        self._should_stop = should_stop

        max_steps = self.stop.limits.max_steps
        graph = self.build()
        config = {
            "configurable": {"thread_id": self.thread_id},
            "recursion_limit": max(25, max_steps * 4 + 10),
        }

        # 续跑时**不能**重新 prepare：工作区里是上一轮改到一半的文件，
        # 再复制一遍起始目录等于把进度抹掉。只有全新一轮才铺工作区。
        has_checkpoint = self._has_checkpoint(config)
        resuming = resume_state is not None or has_checkpoint
        if resuming:
            self.workdir.mkdir(parents=True, exist_ok=True)
        else:
            self._prepare()

        init: FluxState = self._initial_state(resume_state)
        # 有 checkpointer 且这条线程上次留有 checkpoint 时，传 None 才是「接着上次跑」；
        # 传一个全新 state 会把它当成一次新的输入覆盖掉进度。
        if resume_state is None and has_checkpoint:
            # 上次是因为步数/时间用尽才停的，得先把「停」这个标记清掉，
            # 否则 invoke(None) 一进来就被 guard 直接送回 END。
            graph.update_state(
                config,
                {"finished": False, "stop_reason": "", "started_at": time.time()},
            )
            state = graph.invoke(None, config)
        else:
            state = graph.invoke(init, config)
        return self._result(state)

    def _has_checkpoint(self, config: dict[str, Any]) -> bool:
        saver = getattr(self, "checkpointer", None)
        if saver is None:
            return False
        try:
            return saver.get_tuple(config) is not None
        except Exception:
            return False

    def resume(self, should_stop: Callable[[], bool] | None = None) -> RunResult:
        """从 checkpointer 里接着跑（同进程内有效）。"""
        self._should_stop = should_stop
        graph = self.build()
        config = {
            "configurable": {"thread_id": self.thread_id},
            "recursion_limit": max(25, self.stop.limits.max_steps * 4 + 10),
        }
        state = graph.invoke(None, config)
        return self._result(state)

    # -- 内部 ---------------------------------------------------------
    @staticmethod
    def _initial_state(resume_state: dict[str, Any] | None) -> FluxState:
        base: FluxState = {
            "history": [],
            "step": 0,
            "attempt": 1,
            "reflections": 0,
            "ratios": [],
            "attempts": [],
            "last_score": None,
            "pending": None,
            "stop_reason": "循环自然结束",
            "finished": False,
            "plan": [],
            "action_seq": [],
            "last_progress_step": 0,
            "started_at": time.time(),
        }
        if resume_state:
            for key in (
                "history",
                "step",
                "attempt",
                "reflections",
                "ratios",
                "attempts",
                "last_score",
                "plan",
                "action_seq",
                "last_progress_step",
            ):
                if key in resume_state:
                    base[key] = resume_state[key]
            base["finished"] = False
            base["pending"] = None
            base["started_at"] = time.time()
        return base

    def _result(self, state: FluxState) -> RunResult:
        attempts = [
            AttemptRecord(
                a["attempt"],
                Score(a["passed"], a["total"]),
                a["steps"],
                a["reflections"],
            )
            for a in state.get("attempts") or []
        ]
        best = max(attempts, key=lambda a: a.score.ratio) if attempts else None
        return RunResult(
            task=self.task.name,
            attempts=attempts,
            stop_reason=str(state.get("stop_reason") or "循环自然结束"),
            steps_used=min(int(state.get("step") or 0), self.stop.limits.max_steps),
            reflections=int(state.get("reflections") or 0),
            best=best.score if best else None,
            plan=self._plan_view(state),
            usage=self.meter.snapshot() if self.meter else Usage(),
        )

    def _snapshot(self, state: FluxState) -> None:
        if self.snapshot_path is None:
            return
        try:
            self.snapshot_path.parent.mkdir(parents=True, exist_ok=True)
            payload = dict(state)
            payload["saved_at"] = time.time()
            self.snapshot_path.write_text(
                json.dumps(payload, ensure_ascii=False, default=str),
                encoding="utf-8",
            )
        except OSError:
            pass

    def _prepare(self) -> None:
        self.workdir.mkdir(parents=True, exist_ok=True)
        self.task.prepare(self.workdir)

    def _listing(self) -> tuple[str, ...]:
        out: list[str] = []
        for path in sorted(self.workdir.rglob("*")):
            if path.is_dir() or "__pycache__" in path.parts:
                continue
            out.append(path.relative_to(self.workdir).as_posix())
            if len(out) >= 40:
                break
        return tuple(out)

    def _diagnose(self) -> str:
        diagnose = getattr(self.task, "diagnose", None)
        if not callable(diagnose):
            return ""
        try:
            return str(diagnose(self.workdir) or "")
        except Exception:
            return ""

    @staticmethod
    def _plan_view(state: FluxState) -> tuple[tuple[str, bool], ...]:
        return tuple((str(t), bool(d)) for t, d in (state.get("plan") or []))

    @staticmethod
    def _push_seq(state: FluxState, item: str) -> list[str]:
        seq = list(state.get("action_seq") or [])
        seq.append(item)
        return seq[-12:]

    def _note(self, state: FluxState) -> str:
        """把「卡住了」的客观迹象摆到 agent 眼前。它有权无视。"""
        notes: list[str] = []
        step = int(state.get("step") or 0)
        seq = list(state.get("action_seq") or [])
        if len(seq) >= REPEAT_NUDGE and len(set(seq[-REPEAT_NUDGE:])) == 1:
            notes.append(
                f"你已经连续 {REPEAT_NUDGE} 步做同一件事（{seq[-1]}），output 大概也一样。"
                "换一种做法，或者用 stop 说明卡在哪。"
            )
        since = step - int(state.get("last_progress_step") or 0)
        if step >= STALL_NUDGE and since >= STALL_NUDGE:
            notes.append(
                f"已经 {since} 步没有新的评测结果了。别再盲改——先 run_tests 看看现状，"
                "或者直接 submit 拿一次分数。"
            )
        if step >= PLAN_NUDGE and not (state.get("plan") or []):
            notes.append(
                f"你已经走了 {step} 步，但还没写过计划。如果这件事不止一步，"
                '先用 {"action":"plan","steps":[...]} 把它拆开。'
            )
        plan = state.get("plan") or []
        done = sum(1 for _, d in plan if d)
        if plan and done < len(plan) and step >= PLAN_TICK_NUDGE:
            notes.append(
                f"计划里 {len(plan)} 项只划掉了 {done} 项。哪一项已经做完了，"
                '就用 {"action":"plan","steps":[{"text":"...","done":true}, ...]} 把整份计划重写一遍'
                "（没做完的保持 done:false）——提交前先对一遍，别把计划当摆设。"
            )
        return "\n".join(notes)

    def _record(
        self, history: list[str], step: int, action: Action, result: str
    ) -> None:
        key = action.describe()
        prev = self._seen.get(key)
        if prev is not None and prev[1] == result:
            history.append(f"[{key}] -> （与第 {prev[0]} 步的输出完全相同，未重复展示）")
            return
        self._seen[key] = (step, result)
        history.append(f"[{key}] -> {result[:MAX_HISTORY_ENTRY]}")

    def _recent(self, history: list[str]) -> tuple[str, ...]:
        out: list[str] = []
        used = 0
        for entry in reversed(history):
            if out and used + len(entry) > MAX_RECENT_CHARS:
                break
            out.append(entry)
            used += len(entry)
            if len(out) >= 30:
                break
        out.reverse()
        return tuple(out)

    def _run_tool(self, action: Action) -> str:
        for tool in self.tools:
            if tool.name == action.name:
                try:
                    return tool.run(**action.args)[:MAX_TOOL_OUTPUT]
                except TypeError as exc:
                    return f"ERROR 参数不对：{exc}"
                except Exception:
                    return "ERROR " + traceback.format_exc(limit=3)
        return f"ERROR 没有名为 {action.name!r} 的工具"


def _normalize_steps(raw: Any) -> list[tuple[str, bool]]:
    """接受 ["a","b"] 或 [{"text":"a","done":true}] 两种写法。"""
    out: list[tuple[str, bool]] = []
    if not isinstance(raw, list):
        return out
    for item in raw:
        if isinstance(item, str):
            text = item.strip()
            if text:
                out.append((text, False))
        elif isinstance(item, dict):
            text = str(item.get("text") or item.get("step") or "").strip()
            if text:
                out.append((text, bool(item.get("done"))))
    return out


def _action_to_dict(action: Action) -> dict[str, Any]:
    return {"kind": action.kind, "name": action.name, "args": action.args, "text": action.text}


def _action_from(raw: dict[str, Any] | None) -> Action:
    raw = raw or {}
    return Action(
        kind=raw.get("kind", "stop"),
        name=raw.get("name", ""),
        args=raw.get("args") or {},
        text=raw.get("text", ""),
    )
