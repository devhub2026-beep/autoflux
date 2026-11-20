"""批量跑批：同一批任务各跑 N 次，产出可复核的数字。

    python -m autoflux.bench --tasks all --repeats 3
    python -m autoflux.bench --tasks txtlib,calc --repeats 2 --max-steps 30

为什么需要它：单次真跑只能说明「它这次做成了」，不能说明「它做成的概率」。
这里每次 run 都记四样东西——成功/失败、步数、耗时、反思次数，
最后汇总成一张表。没有这张表，「它行不行」就只能听我说。

任务从 `bench/tasks/<名字>/task.json` 读，形如：
    {"goal": "一句话目标", "check": "{python} -m unittest discover -q"}
项目目录是同级的 `project/`，`{python}` 会被替换成当前解释器。
"""
from __future__ import annotations

import argparse
import contextlib
import json
import statistics
import sys
import time
from dataclasses import replace
from pathlib import Path
from typing import Any

from . import config
from .agents.llm import LLMAgent, complete_fn
from .graph import GraphEngine
from .reflector import LLMReflector
from .skillbook import Skillbook
from .stop import StopPolicy
from .tasks.goal import GoalTask
from .tools.fs import default_tools
from .trace import Tracer


def load_task_specs(bench_dir: Path, names: list[str] | None) -> list[dict[str, Any]]:
    root = Path(bench_dir) / "tasks"
    if not root.is_dir():
        raise RuntimeError(f"找不到任务目录：{root}")
    specs: list[dict[str, Any]] = []
    for task_dir in sorted(p for p in root.iterdir() if p.is_dir()):
        meta = task_dir / "task.json"
        if not meta.is_file():
            continue
        if names and task_dir.name not in names:
            continue
        raw = json.loads(meta.read_text(encoding="utf-8"))
        specs.append(
            {
                "name": task_dir.name,
                "goal": str(raw["goal"]),
                "check": str(raw["check"]).replace("{python}", sys.executable),
                "source": task_dir / "project",
            }
        )
    if names:
        missing = set(names) - {s["name"] for s in specs}
        if missing:
            raise RuntimeError(f"没有这些任务：{', '.join(sorted(missing))}")
    return specs


def run_once(
    spec: dict[str, Any],
    cfg: config.Settings,
    *,
    workdir: Path,
    trace_path: Path,
    store: str,
    max_steps: int | None = None,
    max_seconds: float | None = None,
) -> dict[str, Any]:
    limits = cfg.limits
    if max_steps is not None:
        limits = replace(limits, max_steps=max_steps)
    if max_seconds is not None:
        limits = replace(limits, max_seconds=max_seconds)

    task = GoalTask(goal=spec["goal"], check=spec["check"], source=Path(spec["source"]))
    tools = default_tools(workdir)
    agent = LLMAgent(cfg.llm, mission=task.brief())
    reflector = LLMReflector(complete_fn(cfg.llm))
    tracer = Tracer(trace_path)

    started = time.time()
    try:
        with Skillbook(store) as book:
            engine = GraphEngine(
                task=task,
                agent=agent,
                tools=tools,
                reflector=reflector,
                skillbook=book,
                stop_policy=StopPolicy(limits),
                tracer=tracer,
                workdir=workdir,
                thread_id=f"{spec['name']}-{int(started)}",
            )
            result = engine.run()
        seconds = time.time() - started
    except Exception as exc:
        return {
            "task": spec["name"],
            "success": False,
            "best": 0.0,
            "steps": 0,
            "seconds": round(time.time() - started, 1),
            "reflections": 0,
            "attempts": 0,
            "stop_reason": f"崩了：{type(exc).__name__}: {exc}"[:300],
            "curve": [],
            "plan_done": 0,
            "plan_total": 0,
        }

    best = result.best.ratio if result.best else 0.0
    return {
        "task": spec["name"],
        "success": best >= 1.0,
        "best": best,
        "steps": result.steps_used,
        "seconds": round(seconds, 1),
        "reflections": result.reflections,
        "attempts": len(result.attempts),
        "stop_reason": result.stop_reason,
        "curve": [round(a.score.ratio, 3) for a in result.attempts],
        "plan_done": sum(1 for _, done in result.plan if done),
        "plan_total": len(result.plan),
    }


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """总体 + 按任务分开，全是要摆在明面上的数字。"""
    def block(items: list[dict[str, Any]]) -> dict[str, Any]:
        n = len(items)
        if not n:
            return {"n": 0}
        wins = sum(1 for r in items if r["success"])
        return {
            "n": n,
            "success": wins,
            "success_rate": round(wins / n, 3),
            "steps_mean": round(statistics.mean(r["steps"] for r in items), 1),
            "steps_max": max(r["steps"] for r in items),
            "seconds_mean": round(statistics.mean(r["seconds"] for r in items), 1),
            "reflections_mean": round(statistics.mean(r["reflections"] for r in items), 2),
        }

    by_task: dict[str, Any] = {}
    for name in sorted({r["task"] for r in rows}):
        by_task[name] = block([r for r in rows if r["task"] == name])

    failures: dict[str, int] = {}
    for r in rows:
        if not r["success"]:
            reason = r["stop_reason"].split("（")[0]
            failures[reason] = failures.get(reason, 0) + 1

    return {"overall": block(rows), "by_task": by_task, "failure_reasons": failures}


def _print_table(summary: dict[str, Any]) -> None:
    overall = summary["overall"]
    print(f"\n=== 汇总：{overall.get('success', 0)}/{overall.get('n', 0)} 成功"
          f"（{overall.get('success_rate', 0):.0%}）===")
    print(f"{'任务':<14}{'成功':>8}{'平均步数':>10}{'平均秒数':>10}{'平均反思':>10}")
    for name, row in summary["by_task"].items():
        print(
            f"{name:<14}{row['success']}/{row['n']:>6}"
            f"{row['steps_mean']:>10}{row['seconds_mean']:>10}{row['reflections_mean']:>10}"
        )
    if summary["failure_reasons"]:
        print("\n失败原因：")
        for reason, count in sorted(
            summary["failure_reasons"].items(), key=lambda kv: -kv[1]
        ):
            print(f"  {reason}: {count}")


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            with contextlib.suppress(Exception):
                stream.reconfigure(encoding="utf-8")

    p = argparse.ArgumentParser(prog="autoflux bench", description="同一批任务跑 N 次，出数字")
    p.add_argument("--tasks", default="all", help="逗号分隔的任务名，或 all")
    p.add_argument("--repeats", type=int, default=1, help="每个任务跑几次")
    p.add_argument("--bench", default="bench", help="任务目录（默认 bench/）")
    p.add_argument("--out", help="结果 JSON 路径（默认 bench/results/<时间戳>.json）")
    p.add_argument("--config", default="config.toml")
    p.add_argument("--workdir", default="runs/bench", help="工作区根目录")
    p.add_argument("--max-steps", type=int, default=None)
    p.add_argument("--max-seconds", type=float, default=None)
    args = p.parse_args(argv)

    names = None if args.tasks.strip() in ("all", "") else [
        n.strip() for n in args.tasks.split(",") if n.strip()
    ]

    try:
        specs = load_task_specs(Path(args.bench), names)
    except RuntimeError as exc:
        print(f"[错误] {exc}", file=sys.stderr)
        return 2
    if not specs:
        print("[错误] 一个任务都没找到", file=sys.stderr)
        return 2

    cfg = config.load(Path(args.config) if args.config else None)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    out = Path(args.out) if args.out else Path(args.bench) / "results" / f"{stamp}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    store = str(out.parent / f"{stamp}.db")
    workroot = Path(args.workdir).resolve()

    rows: list[dict[str, Any]] = []
    for spec in specs:
        for i in range(args.repeats):
            tag = f"{spec['name']}-{stamp}-{i + 1}"
            workdir = workroot / tag
            trace_path = out.parent / f"trace-{tag}.jsonl"
            print(f"[跑] {spec['name']} #{i + 1}/{args.repeats} ...", flush=True)
            try:
                row = run_once(
                    spec,
                    cfg,
                    workdir=workdir,
                    trace_path=trace_path,
                    store=store,
                    max_steps=args.max_steps,
                    max_seconds=args.max_seconds,
                )
            except KeyboardInterrupt:
                print("\n[中断]", file=sys.stderr)
                break
            except RuntimeError as exc:
                row = {
                    "task": spec["name"],
                    "success": False,
                    "best": 0.0,
                    "steps": 0,
                    "seconds": 0.0,
                    "reflections": 0,
                    "attempts": 0,
                    "stop_reason": f"ERROR {exc}",
                    "curve": [],
                    "plan_done": 0,
                    "plan_total": 0,
                }
            rows.append(row)
            print(
                f"     {'成功' if row['success'] else '失败'}  "
                f"{row['steps']} 步  {row['seconds']}s  反思 {row['reflections']}"
                f"  曲线 {row['curve']}",
                flush=True,
            )

    summary = summarize(rows)
    _print_table(summary)
    out.write_text(
        json.dumps(
            {"stamp": stamp, "rows": rows, "summary": summary},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"\n结果    {out}")
    return 0 if summary["overall"].get("success") else 1


if __name__ == "__main__":
    raise SystemExit(main())
