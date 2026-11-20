"""校验 report.md：数字对不对、该说的有没有说。

这个文件**不在** agent 的工作区里（工作区是 data/ 目录的副本），
所以它改不了判分规则，也看不到这里的期望值。

用法：在工作区里执行
    python "D:\\autoflux\\examples\\employment\\_check.py"
退出码 0 = 全部通过。
"""
from __future__ import annotations

import contextlib
import re
import sys
from pathlib import Path

# ---- 期望值：逐字来自国家统计局表 2（见 data/sources.md）-------------------
TOTAL = 129441
TOP_NAME, TOP_VALUE = "信息传输、软件和信息技术服务业", 248752
LOW_NAME, LOW_VALUE = "住宿和餐饮业", 62461
FAST_NAME, FAST_VALUE = "农、林、牧、渔业", 10.3
# 表里负增长的有两个，不是一个——这里必须跟着数据说话
NEG_GROWTH = {"房地产业": -2.4, "租赁和商务服务业": -0.2}
ABOVE_TOTAL = 10                      # 19 个行业里高于全国合计的个数
RATIO_LO, RATIO_HI = 3.9, 4.05        # 248752 / 62461 ≈ 3.98

WAGES = {
    "农、林、牧、渔业": (74424, 10.3),
    "采矿业": (143361, 1.9),
    "制造业": (113594, 5.2),
    "电力、热力、燃气及水生产和供应业": (160897, 7.1),
    "建筑业": (92036, 2.8),
    "批发和零售业": (135749, 4.7),
    "交通运输、仓储和邮政业": (133981, 4.8),
    "住宿和餐饮业": (62461, 3.7),
    "信息传输、软件和信息技术服务业": (248752, 4.1),
    "金融业": (211164, 4.6),
    "房地产业": (89679, -2.4),
    "租赁和商务服务业": (110162, -0.2),
    "科学研究和技术服务业": (182064, 3.8),
    "水利、环境和公共设施管理业": (70172, 2.7),
    "居民服务、修理和其他服务业": (70226, 3.0),
    "教育": (133539, 5.8),
    "卫生和社会工作": (146266, 2.2),
    "文化、体育和娱乐业": (129447, 2.7),
    "公共管理、社会保障和社会组织": (119465, 4.0),
}


def numbers(text: str) -> str:
    """把 129,441 / 129441 元 这类写法抹平，便于找数。"""
    return re.sub(r"[\s,，]", "", text)


def main() -> int:
    # Windows 的默认控制台编码可能是 cp1252/GBK，中文直接 print 会 UnicodeEncodeError
    # （CI 上就是这样挂的），先统一切 UTF-8
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            with contextlib.suppress(Exception):
                stream.reconfigure(encoding="utf-8")

    path = Path("report.md")
    if not path.exists():
        print("FAIL 没有 report.md")
        return 1
    text = path.read_text(encoding="utf-8", errors="replace")
    flat = numbers(text)

    checks: list[tuple[str, bool, str]] = []

    def want(key: str, ok: bool, why: str = "") -> None:
        checks.append((key, ok, why))

    want("报告不是空壳", len(text) >= 600, f"当前 {len(text)} 字")
    want("写清了口径（城镇非私营单位）", "非私营" in text, "没写口径的报告数字会被误读")
    want("写清了不含个体工商户", "个体" in text or "自由职业" in text, "")
    want("全国合计 129441", str(TOTAL) in flat, "")

    # 19 个行业的名字都要出现，工资数至少出现 17 个
    missing = [k for k in WAGES if k not in text]
    want("19 个行业门类全部点名", not missing, "缺：" + "、".join(missing[:5]))
    hit = sum(1 for v, _ in WAGES.values() if str(v) in flat)
    want("行业工资数至少 17 个", hit >= 17, f"只找到 {hit} 个")

    want("最高薪行业点名", TOP_NAME in text, "")
    want("最高薪数值 248752", str(TOP_VALUE) in flat, "")
    want("最低薪行业点名", LOW_NAME in text, "")
    want("最低薪数值 62461", str(LOW_VALUE) in flat, "")
    want("增速最快行业点名", FAST_NAME in text, "")
    want("增速最快数值 10.3", "10.3" in text, "")
    want(
        "点出两个负增长行业（房地产业 -2.4%、租赁和商务服务业 -0.2%）",
        all(name in text for name in NEG_GROWTH)
        and "负增长" in text
        and all(re.search(re.escape(str(abs(v))), flat) for v in NEG_GROWTH.values()),
        "别把两个说成一个，也别漏掉降幅",
    )
    want(
        "高于全国合计的行业个数 10",
        re.search(r"(高于|超过)[^。\n]{0,24}(10|十)\s*个", text) is not None
        or re.search(r"(10|十)\s*个[^。\n]{0,16}(高于|超过)", text) is not None,
        "",
    )

    m = re.search(r"(3\.9\d?|4\.0\d?)\s*倍?", text)
    want("最高/最低 约 3.98 倍", m is not None, "要算出来，不要只说差距大")

    bad = [f"{k}（{why}）" if why else k for k, ok, why in checks if not ok]
    for key, ok, why in checks:
        print(("PASS " if ok else "FAIL ") + key + (f"  <- {why}" if not ok and why else ""))
    print(f"\n{len(checks) - len(bad)}/{len(checks)} 通过")
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())
