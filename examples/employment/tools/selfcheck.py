"""自检：用「标准答案报告」验证 _check.py 本身是好的。

不是给 agent 看的——它在 examples/employment/tools/ 下，工作区只复制 data/。
用法：
    python tools/selfcheck.py
"""
from __future__ import annotations

import contextlib
import csv
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]


def build_report(rows: list[tuple[str, int, float]]) -> str:
    ranked = sorted(rows, key=lambda r: r[1], reverse=True)
    top = ranked[0]
    low = ranked[-1]
    fast = max(rows, key=lambda r: r[2])
    total = 129441
    above = [r for r in rows if r[1] > total]
    ratio = top[1] / low[1]
    lines = [
        "# 2025 年城镇单位分行业薪资报告",
        "",
        "一句话结论：19 个行业门类的年平均工资从 6.2 万到 24.9 万，",
        f"信息传输、软件和信息技术服务业最高，住宿和餐饮业最低，相差约 {ratio:.2f} 倍。",
        "",
        "## 口径",
        "",
        "本报告数据为国家统计局《2025年城镇单位就业人员年平均工资情况》表 2，",
        "口径是**城镇非私营单位**，即城镇地域内 5 人及以上法人单位，",
        "**不含个体工商户和自由职业者**；平均工资含代扣代缴的个税、社保与公积金，",
        "因此高于多数人到手工资。全国合计 129441 元。",
        "",
        "## 排名",
        "",
        "| 排名 | 行业 | 2025 年平均工资（元） | 名义增长率 |",
        "| --- | --- | ---: | ---: |",
    ]
    for i, (name, wage, growth) in enumerate(ranked, 1):
        lines.append(f"| {i} | {name} | {wage} | {growth}% |")
    lines += [
        "",
        "## 三条发现",
        "",
        f"1. 最高薪是 **{top[0]}**，{top[1]} 元。",
        f"2. 最低薪是 **{low[0]}**，{low[1]} 元，最高与最低相差 **{ratio:.2f} 倍**。",
        f"3. 增长最快的是 **{fast[0]}**，名义增长 **{fast[2]}%**；",
        "   负增长的是 **房地产业**（-2.4%）和 **租赁和商务服务业**（-0.2%），共 2 个。",
        "",
        f"高于全国合计 129441 元的行业共 {len(above)} 个。",
        "",
        "## 给求职者的建议",
        "",
        "1. 站在工资绝对值上，信息传输、软件和信息技术服务业与金融业仍是第一梯队。",
        "2. 增速比绝对值更能说明方向：农林牧渔增速最快但基数最低，属于低基数修复。",
        "3. 房地产与租赁和商务服务业是仅有的两个负增长行业，转入前要按「薪资不涨」做预算。",
        "",
        "## 局限",
        "",
        "本数据不含私营单位、个体户与自由职业者，也不含岗位数量与招聘需求，",
        "只能回答「哪个行业平均工资高」，回答不了「哪个行业好找工作」。",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    # 和 _check.py 一样：控制台编码可能是 cp1252/GBK，先把中文输出切到 UTF-8
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            with contextlib.suppress(Exception):
                stream.reconfigure(encoding="utf-8")

    rows: list[tuple[str, int, float]] = []
    with (HERE / "data" / "wages_2025.csv").open(encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            if row["行业门类"] == "合计":
                continue
            rows.append(
                (
                    row["行业门类"],
                    int(row["2025_年平均工资_元"]),
                    float(row["名义增长率_百分比"]),
                )
            )
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / "report.md").write_text(build_report(rows), encoding="utf-8")
        proc = subprocess.run(
            [sys.executable, str(HERE / "_check.py")],
            cwd=tmp,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        # 把判分输出原样转出来，不然自检「静默通过」，人看不到它核了哪些项
        sys.stdout.write(proc.stdout or "")
        sys.stdout.write(proc.stderr or "")
        return proc.returncode


if __name__ == "__main__":
    sys.exit(main())
