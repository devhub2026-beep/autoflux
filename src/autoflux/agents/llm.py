"""LLM agent：唯一真正的「自主」来源。

每一轮它看到：工具清单、已有规则、最近动作、当前文件列表、上次评分，
然后**自己决定**下一步是调工具、要求反思、提交、还是放弃。

注意：它能决定「怎么做」，但不能决定「算不算过」——分数永远来自 evaluator。
"""
from __future__ import annotations

import http.client
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from ..config import LLMSettings
from ..protocols import Tool
from ..types import Action, Observation
from ..usage import Meter

# 传输层签名：给一个 Request 和超时，返回一个可 with、可 read 的对象。
# 默认是 urllib；测试时换成假实现，整条 LLM 路径就能离线跑。
Transport = Callable[[Any, float], Any]


def _urllib_transport(req: Any, timeout: float) -> Any:
    # 端点来自配置/环境变量，顺手把 scheme 卡死在 http(s)，免得 file:// 或自定义协议也能被打开
    scheme = urllib.parse.urlsplit(getattr(req, "full_url", "")).scheme
    if scheme not in ("http", "https"):
        raise ValueError(f"模型端点只允许 http/https，收到的是 {scheme or '空'}")
    return urllib.request.urlopen(req, timeout=timeout)  # noqa: S310 —— scheme 上面已校验


def _load_env_file() -> None:
    """把项目根（或当前目录）下 `.env` 里的键补进环境变量。

    只在变量还空着的时候填，已有的不覆盖；解析很土但够用：
    一行 `KEY=VALUE`，`#` 开头是注释，值两边的引号去掉。
    """
    roots = [Path.cwd(), Path(__file__).resolve().parents[3]]
    for root in roots:
        path = root / ".env"
        if not path.is_file():
            continue
        try:
            lines = path.read_text(encoding="utf-8-sig").splitlines()
        except OSError:
            continue
        for raw in lines:
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and value and not os.environ.get(key):
                os.environ[key] = value

_SYSTEM = """你是一个在受限工作区里工作的软件 agent。

规则：
- 你只能通过工具改变世界，不要假装做过什么。
- 你可以随时选择：
  {"action":"plan","steps":["先看懂失败原因","改实现","再跑一次"]}
                                             # 给自己定/改一份子目标清单；做完一项就把该项标 true：
                                             # {"action":"plan","steps":[{"text":"...","done":true}, ...]}
  {"action":"tool","tool":"<名字>","args":{...}}
  {"action":"reflect"}                       # 复盘上一轮评测为何失败，产出一条规则
  {"action":"submit"}                        # 提交当前工作区接受评测
  {"action":"stop","reason":"<为什么放弃>"}
- 每次只输出一个 JSON 对象，不要输出任何别的文字。
- action 只能是 "tool" / "plan" / "reflect" / "submit" / "stop" 这五个字符串之一，
  不要把工具名当成 action。
- reflect 不是自言自语：它会去把这次评测的**详细日志**捞出来给你。
  有些任务只告诉你一个总分（比如 7/10），这时 reflect 是你唯一能知道
  「到底哪几项挂了」的办法，代价是一步。
- 看到失败细节后再动手，不要盲改。
- 提交前先自己跑一遍可见测试。
- 任务超过一步时，先把计划写出来（plan），再照着做；中途发现计划错了就整个重写。
- 【任务】里写的是你这次要达成的目标；下面的示例只是 JSON 格式，不要照着示例去猜任务。

示例（写计划）：
{"action":"plan","steps":["看失败的那条测试断言了什么","改实现","跑测试"]}
示例（调工具）：
{"action":"tool","tool":"read_file","args":{"path":"README.md"}}
示例（反思，只有在你已经看到过一次评测结果之后才有意义）：
{"action":"reflect"}
"""


class _Retryable(RuntimeError):
    """网络层抖动：重试有意义，不该让整次 run 作废。"""


class LLMAgent:
    retries = 3
    backoff = 0.8
    def __init__(
        self,
        settings: LLMSettings,
        transport: Transport | None = None,
        mission: str = "",
        meter: Meter | None = None,
    ) -> None:
        self.settings = settings
        self._transport: Transport = transport or _urllib_transport
        # 记账不是必须的：单独用 agent 时不传 meter，就不会统计 token
        self.meter = meter
        # 任务由外部给：模型决定「怎么做」，不决定「要什么」
        self.mission = mission.strip()
        _load_env_file()
        key = os.environ.get(settings.api_key_env, "")
        if not key:
            raise RuntimeError(
                f"缺少 API key：设置环境变量 {settings.api_key_env}，"
                "或在项目根放一个 .env（一行 KEY=VALUE）"
            )
        self._key = key

    # -- Agent 协议 ----------------------------------------------------
    def decide(self, obs: Observation, tools: Sequence[Tool], skills: Sequence[str]) -> Action:
        prompt = self._build_prompt(obs, tools, skills)
        text = self._chat([
            {"role": "system", "content": _SYSTEM},
            {"role": "user", "content": prompt},
        ])
        return self._parse(text, {t.name for t in tools})

    def complete(self, messages: list[dict[str, str]]) -> str:
        """给「问答」这类不经过动作解析的调用方用：原样发 messages，返回文本。"""
        return self._chat(messages)

    # -- 内部 ----------------------------------------------------------
    def _build_prompt(self, obs: Observation, tools: Sequence[Tool], skills: Sequence[str]) -> str:
        tool_lines = "\n".join(f"- {t.name}: {t.description}" for t in tools)
        skill_lines = "\n".join(f"- {s}" for s in skills) or "（还没有）"
        recent = "\n".join(f"{i + 1}. {r}" for i, r in enumerate(obs.recent)) or "（无）"
        signal = str(obs.last_signal) if obs.last_signal else "（还没评测过）"
        plan = (
            "\n".join(
                f"{'[x]' if done else '[ ]'} {text}" for text, done in obs.plan
            )
            or "（还没写过）"
        )
        note = f"【提醒】\n{obs.note}\n\n" if obs.note else ""

        mission = f"【任务】\n{self.mission}\n\n" if self.mission else ""
        return f"""{mission}【第 {obs.attempt} 次尝试，第 {obs.step} 步】

{note}你的计划：
{plan}

可用工具：
{tool_lines}

工作区文件：
{chr(10).join(obs.workspace) or "（空）"}

上次评测：
{signal}

最近动作：
{recent}

已掌握的规则：
{skill_lines}

下一步做什么？只输出一个 JSON。"""

    def _chat(self, messages: list[dict[str, str]]) -> str:
        """调一次模型。网络层的抖动（断包、超时、5xx）重试，别的错直接抛。"""
        last: Exception | None = None
        for attempt in range(self.retries):
            try:
                return self._chat_once(messages)
            except _Retryable as exc:
                last = exc
                if attempt + 1 < self.retries:
                    time.sleep(self.backoff * (2**attempt))
        raise RuntimeError(f"连不上模型端点（重试 {self.retries} 次）：{last}") from last

    def _chat_once(self, messages: list[dict[str, str]]) -> str:
        url = self.settings.base_url.rstrip("/") + "/chat/completions"
        payload = json.dumps({
            "model": self.settings.model,
            "messages": messages,
            "temperature": self.settings.temperature,
        }).encode("utf-8")

        req = urllib.request.Request(  # noqa: S310 —— scheme 已在 transport 里校验
            url,
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self._key}",
            },
            method="POST",
        )
        try:
            with self._transport(req, self.settings.timeout) as resp:
                raw = resp.read()
            body = json.loads(raw.decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:500]
            if exc.code >= 500 or exc.code == 429:
                raise _Retryable(f"LLM 调用失败 {exc.code}: {detail}") from exc
            raise RuntimeError(f"LLM 调用失败 {exc.code}: {detail}") from exc
        except (urllib.error.URLError, TimeoutError, OSError, http.client.HTTPException,
                ValueError) as exc:
            # IncompleteRead / 断包 / 非 UTF-8，都是网络层的问题，重试有意义
            raise _Retryable(f"连不上模型端点：{exc}") from exc

        self._record_usage(body)
        try:
            return body["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError(f"模型返回格式异常：{str(body)[:300]}") from exc

    def _record_usage(self, body: Any) -> None:
        """端点回了 usage 就记账；没回也要记一笔「这次没报账」。"""
        if self.meter is None:
            return
        usage = body.get("usage") if isinstance(body, dict) else None
        if not isinstance(usage, dict):
            self.meter.add_unreported()
            return
        self.meter.add(_token_count(usage.get("prompt_tokens")),
                       _token_count(usage.get("completion_tokens")))
    def _parse(self, text: str, tool_names: set[str] | None = None) -> Action:
        """解析模型输出。

        模型偶尔会把工具名直接写进 action、或者把参数放在别的键里。
        这些都不该让整次 run 作废——能救就救，救不了才停，并且说清楚为什么停。
        """
        raw = text.strip()
        raw = re.sub(r"^```(?:json)?|```$", "", raw, flags=re.MULTILINE).strip()
        start, end = raw.find("{"), raw.rfind("}")
        if start >= 0 and end > start:
            raw = raw[start : end + 1]

        try:
            data: dict[str, Any] = json.loads(raw)
        except json.JSONDecodeError:
            return Action("stop", text=f"模型输出无法解析：{text[:200]}")

        known = tool_names or set()
        kind = str(data.get("action", "")).strip()
        args = _pick_args(data)

        if kind == "tool":
            name = str(data.get("tool") or data.get("name") or "")
            return Action("tool", name=name, args=args)
        if kind == "plan":
            steps = data.get("steps") or args.get("steps") or []
            return Action("plan", args={"steps": steps})
        if kind == "reflect":
            return Action("reflect")
        if kind == "submit":
            return Action("submit")
        if kind == "stop":
            return Action("stop", text=str(data.get("reason", "")))

        # 宽容处理：没写 action，只写了 steps，当成写计划
        if not kind and data.get("steps"):
            return Action("plan", args={"steps": data["steps"]})

        # 宽容处理：action 里直接写了工具名
        if kind in known:
            return Action("tool", name=kind, args=args)

        # 宽容处理：没写 action，但写了 tool
        fallback_tool = str(data.get("tool") or data.get("name") or "")
        if fallback_tool in known:
            return Action("tool", name=fallback_tool, args=args)

        return Action("stop", text=f"未知动作 {kind!r}")


def _token_count(value: Any) -> int:
    """usage 里的数字偶尔是字符串或者干脆没有；拿不准就当 0，别炸整次调用。"""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0
    return max(int(value), 0)


def _pick_args(data: dict[str, Any]) -> dict[str, Any]:
    """参数可能藏在 args / parameters / arguments / kwargs 里。"""
    for key in ("args", "parameters", "arguments", "kwargs", "params"):
        value = data.get(key)
        if isinstance(value, dict):
            return dict(value)
    # 兜底：把顶层的标量键当成参数
    reserved = {"action", "tool", "name", "reason"}
    return {k: v for k, v in data.items() if k not in reserved and not isinstance(v, (dict, list))}


def complete_fn(settings: LLMSettings, transport: Transport | None = None,
                meter: Meter | None = None):
    """给 LLMReflector 用的单次补全函数。和主 agent 共用一本账。"""
    agent = LLMAgent(settings, transport=transport, meter=meter)

    def _complete(prompt: str) -> str:
        return agent._chat([{"role": "user", "content": prompt}])

    return _complete
