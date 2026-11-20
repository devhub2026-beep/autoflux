"""命令行入口。

三种用法：
    autoflux                      # 默认跑一次（等价 run）
    autoflux serve                # 起网页，看它自己跑
    autoflux run --goal "..." --project . --check "pytest -q"
    autoflux run --resume runs/20261114-203555-d90b04   # 从上次的状态接着跑
"""
from __future__ import annotations

import argparse
import contextlib
import json
import sys
import time
from dataclasses import replace
from pathlib import Path

from . import config, tasks
from .agents.llm import LLMAgent, complete_fn
from .checkpoint import SqliteSaver
from .employment import Dataset, qa
from .graph import GraphEngine
from .protocols import Task
from .reflector import LLMReflector
from .skillbook import Skillbook
from .stop import StopPolicy
from .tasks.goal import GoalTask
from .tools.fs import default_tools
from .trace import Tracer
from .types import RunResult

RESUME_KEYS = (
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
)


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="autoflux",
        description="自主循环 + 自主反思的 agent：评测闸门在外部，模型改不了分。",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    run = sub.add_parser("run", help="跑一次自主循环")
    run.add_argument("--task", help="内置任务名（默认取配置）")
    run.add_argument("--goal", help="目标模式：一句话目标，交给 agent 自己拆")
    run.add_argument("--project", default=".", help="目标模式的起始目录")
    run.add_argument("--check", help="目标模式的判定命令，退出码 0 算过")
    run.add_argument("--resume", help="从某个 run 目录里的 state.json 接着跑")
    run.add_argument("--config", default="config.toml", help="配置文件路径")
    run.add_argument("--workdir", default="runs/workspace", help="agent 的工作区")
    run.add_argument("--store", help="skillbook 数据库路径")
    run.add_argument("--max-attempts", type=int)
    run.add_argument("--max-steps", type=int)
    run.add_argument("--max-seconds", type=float)

    sub.add_parser("tasks", help="列出内置任务")

    sk = sub.add_parser("skills", help="查看技能库")
    sk.add_argument("--store", default=".autoflux/state.db")

    ask = sub.add_parser(
        "ask", help="问就业数据：先答一版，数字核对不过就自动重写"
    )
    ask.add_argument("--question", help="要问的问题（不带 --chat 时必填）")
    ask.add_argument("--chat", action="store_true", help="多轮问答：一行一问，空行结束")
    ask.add_argument(
        "--data",
        default="examples/employment/data/wages_2025.csv",
        help="统计表 CSV（默认用仓库里的就业示例数据）",
    )
    ask.add_argument("--attempts", type=int, default=3, help="每问最多让模型重写几次")
    ask.add_argument("--config", default="config.toml", help="配置文件路径")

    sub.add_parser("bench", help="批量跑批：同一批任务跑 N 次，出成功率/步数/耗时")

    srv = sub.add_parser("serve", help="起本地网页，输入目标看它自己跑")
    srv.add_argument("--host", default="127.0.0.1")
    srv.add_argument("--port", type=int, default=8765)

    return p


def _resolve(args: argparse.Namespace) -> config.Settings:
    path = Path(args.config) if args.config else None
    cfg = config.load(path)
    limits = cfg.limits
    if getattr(args, "max_attempts", None) is not None:
        limits = replace(limits, max_attempts=args.max_attempts)
    if getattr(args, "max_steps", None) is not None:
        limits = replace(limits, max_steps=args.max_steps)
    if getattr(args, "max_seconds", None) is not None:
        limits = replace(limits, max_seconds=args.max_seconds)
    return replace(
        cfg,
        task=args.task or cfg.task,
        store=args.store or cfg.store,
        limits=limits,
    )


def _load_resume(run_dir: Path) -> dict:
    path = run_dir / "state.json"
    if not path.exists():
        raise RuntimeError(f"{path} 不存在，没法续跑")
    raw = json.loads(path.read_text(encoding="utf-8"))
    return {k: raw[k] for k in RESUME_KEYS if k in raw}


def _cmd_run(args: argparse.Namespace) -> int:
    cfg = _resolve(args)

    if args.resume:
        return _cmd_resume(args, cfg)

    if args.goal:
        if not args.check:
            print("[错误] --goal 必须配 --check（判定命令），否则没人能给分", file=sys.stderr)
            return 2
        task: Task = GoalTask(goal=args.goal, check=args.check, source=Path(args.project))
    else:
        try:
            task = tasks.get(cfg.task)
        except KeyError as exc:
            print(f"[错误] {exc}", file=sys.stderr)
            return 2

    workdir = Path(args.workdir).resolve()
    tools = default_tools(workdir)

    agent = LLMAgent(cfg.llm, mission=getattr(task, "brief", lambda: "")())
    reflector = LLMReflector(complete_fn(cfg.llm))

    stamp = time.strftime("%Y%m%d-%H%M%S")
    run_dir = Path("runs") / stamp
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "run.json").write_text(
        json.dumps(
            {
                "run_id": stamp,
                "task": getattr(task, "name", cfg.task),
                "goal": getattr(task, "goal", ""),
                "check": getattr(task, "check", ""),
                "project": str(getattr(task, "source", args.project) or args.project),
                "workdir": str(workdir),
                "started_at": stamp,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    tracer = Tracer(run_dir / "trace.jsonl")
    saver = SqliteSaver(run_dir / "checkpoints.sqlite")

    with Skillbook(cfg.store) as book:
        engine = GraphEngine(
            task=task,
            agent=agent,
            tools=tools,
            reflector=reflector,
            skillbook=book,
            stop_policy=StopPolicy(cfg.limits),
            tracer=tracer,
            workdir=workdir,
            thread_id=stamp,
            checkpointer=saver,
            snapshot_path=run_dir / "state.json",
        )
        try:
            result = engine.run()
        finally:
            saver.close()

    _print_result(result, tracer.path, workdir)
    return 0


def _cmd_resume(args: argparse.Namespace, cfg: config.Settings) -> int:
    """从 state.json 接着跑：历史、分数曲线、计划都还在，只有 pending 清空。"""
    run_dir = Path(args.resume).resolve()
    state = _load_resume(run_dir)

    meta_path = run_dir / "run.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
    goal = args.goal or meta.get("goal") or ""
    check = args.check or meta.get("check") or ""
    project = args.project if args.project != "." else meta.get("project") or "."

    if not goal or not check:
        print(
            "[错误] 续跑需要目标和判定命令：要么 run.json 里存过，要么 --goal/--check 再给一次",
            file=sys.stderr,
        )
        return 2

    task = GoalTask(goal=goal, check=check, source=Path(project))
    workdir = Path(meta["workdir"]) if meta.get("workdir") else Path(args.workdir).resolve()
    if not workdir.exists():
        print(f"[错误] 上次的工作区 {workdir} 已经没了，没法接着改", file=sys.stderr)
        return 2

    tools = default_tools(workdir)
    agent = LLMAgent(cfg.llm, mission=task.brief())
    reflector = LLMReflector(complete_fn(cfg.llm))

    stamp = meta.get("run_id") or time.strftime("%Y%m%d-%H%M%S")
    tracer = Tracer(run_dir / "trace.jsonl")
    db = run_dir / "checkpoints.sqlite"
    saver = SqliteSaver(db) if db.exists() else None
    # 有 checkpointer 就用它接着跑（真续跑）；没有才退回 state.json 快照
    resume_state = None if saver else state

    with Skillbook(cfg.store) as book:
        engine = GraphEngine(
            task=task,
            agent=agent,
            tools=tools,
            reflector=reflector,
            skillbook=book,
            stop_policy=StopPolicy(cfg.limits),
            tracer=tracer,
            workdir=workdir,
            thread_id=stamp,
            checkpointer=saver,
            snapshot_path=run_dir / "state.json",
        )
        try:
            result = engine.run(resume_state=resume_state)
        finally:
            if saver:
                saver.close()

    _print_result(result, tracer.path, workdir)
    return 0


def _print_result(result: RunResult, trace_path: Path | None, workdir: Path) -> None:
    print(f"\n=== {result.task} ===")
    print(result.summary())
    if result.attempts:
        print("\n--- 每次尝试 ---")
        for a in result.attempts:
            print(
                f"  #{a.attempt}  {a.score.passed}/{a.score.total}"
                f"  步数 {a.steps_used}  反思 {a.reflections}"
            )
            for line in a.score.details[:4]:
                print(f"       {line}")
    print(f"\n追踪文件    {trace_path or '（未开）'}")
    print(f"工作区      {workdir}")


def _cmd_tasks() -> int:
    for name in tasks.names():
        print(name)
    return 0


def _cmd_skills(store: str) -> int:
    with Skillbook(store) as book:
        rows = book.all()
        if not rows:
            print("还没有学到任何规则")
            return 0
        for ident, text, uses, wins in rows:
            print(f"[{ident}] 用{uses} 赢{wins}  {text}")
    return 0


def _show(result: dict, ds: Dataset) -> None:
    print(f"\n=== 答案（第 {result['attempts']} 次）===\n")
    print(result["answer"])
    print()
    if result["verified"]:
        print("数字核对    通过（每个数字都能在表里找到，或是表里的数算出来的）")
    else:
        print(f"数字核对    未通过（{len(result['problems'])} 处）", file=sys.stderr)
        for problem in result["problems"]:
            print(f"  - {problem}", file=sys.stderr)


def _chat(agent, ds: Dataset, attempts: int) -> int:
    """多轮问答：上一问的问答会进下一问的上下文，追问不用从头再来。"""
    history: list[dict[str, str]] = []
    all_ok = True
    print("多轮问答：一行一问，空行或 Ctrl-D 结束。")
    while True:
        try:
            line = input("问题> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not line:
            break
        result = qa.ask(agent, ds, line, history=history, attempts=attempts)
        _show(result, ds)
        all_ok = all_ok and bool(result["verified"])
        history.append({"role": "user", "content": line})
        history.append({"role": "assistant", "content": result["answer"]})
    return 0 if all_ok else 1


def _cmd_ask(args: argparse.Namespace) -> int:
    """问答也算一次「外部判定」：答案里的数字过不了校验就打回重写。

    和 run 的区别：这里模型不吃工具、不循环动作，只负责写字；
    把关的是 verify()，不是模型自己说「我写对了」。
    """
    if not args.chat and not (args.question or "").strip():
        print("[错误] 要么给 --question，要么用 --chat 进多轮问答", file=sys.stderr)
        return 2

    path = Path(args.data)
    if not path.is_file():
        print(f"[错误] 找不到数据表：{path}", file=sys.stderr)
        return 2

    ds = Dataset(path)
    cfg = config.load(Path(args.config) if args.config else None)
    agent = LLMAgent(cfg.llm)

    if args.chat:
        return _chat(agent, ds, args.attempts)

    result = qa.ask(agent, ds, args.question, attempts=args.attempts)
    _show(result, ds)
    return 0 if result["verified"] else 1


def _normalize_argv(argv: list[str] | None) -> list[str]:
    """没有子命令时默认 ``run``。

    这是给 IDE 准备的：PyCharm 点绿三角时 argv 是空的，
    否则会报 "the following arguments are required: cmd"。
    """
    args = list(sys.argv[1:] if argv is None else argv)
    return args or ["run"]


def main(argv: list[str] | None = None) -> int:
    # Windows 控制台默认 GBK，中文会乱码；统一成 UTF-8
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            with contextlib.suppress(Exception):
                stream.reconfigure(encoding="utf-8")

    raw = list(argv) if argv is not None else sys.argv[1:]
    # bench 有自己的参数，先交给它，免得被主解析器拒掉
    if raw and raw[0] == "bench":
        from .bench import main as bench_main

        return bench_main(raw[1:])

    args = _build_parser().parse_args(_normalize_argv(raw))

    if args.cmd == "run":
        try:
            return _cmd_run(args)
        except KeyboardInterrupt:
            print("\n[中断] 已停止", file=sys.stderr)
            return 130
        except RuntimeError as exc:
            print(f"[错误] {exc}", file=sys.stderr)
            return 1

    if args.cmd == "tasks":
        return _cmd_tasks()

    if args.cmd == "skills":
        return _cmd_skills(args.store)

    if args.cmd == "ask":
        try:
            return _cmd_ask(args)
        except RuntimeError as exc:
            print(f"[错误] {exc}", file=sys.stderr)
            return 1
        except KeyboardInterrupt:
            print("\n[中断] 已停止", file=sys.stderr)
            return 130

    if args.cmd == "bench":
        from .bench import main as bench_main

        rest = (list(argv) if argv is not None else sys.argv[1:])[1:]
        return bench_main(rest)

    if args.cmd == "serve":
        from .web.app import serve

        serve(host=args.host, port=args.port)
        return 0

    return 2
