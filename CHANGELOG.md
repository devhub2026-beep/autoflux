# 变更记录

从 0.5.0 开始单独记；更早的改动散在 README 的实测与限制里。

## 0.6.0 — 2026-11-20

- **Web 历史**：服务启动时扫描 `runs/`，把以前的 run（包括命令行跑的）读回列表；
  左栏「历史」点一条就能回放当时的轨迹。`run.json` 现在在开跑时就落盘，进程中途死掉也留得下记录。
- **多轮问答**：`autoflux ask --chat` 一行一问，上一轮问答进下一轮上下文；
  `POST /api/ask` 接受并返回 `history`，网页左栏新增「问数据」面板，可以连续追问。
- **修续跑会覆盖工作区**：`GraphEngine.run` 在 resume 分支不再执行 `task.prepare`，
  否则上一轮改到一半的文件会被起始目录重新铺一遍。新增 `test_resume_real` 用例守着。
- **发布**：`license` 改成 SPDX 写法（`license = "MIT"` + `license-files`，setuptools>=77）；
  补 `.dockerignore`；镜像带上 `config.toml`（否则容器里跑的是代码默认配置）。
- 测试 131 → 147：CLI 的 run/resume/tasks/skills、跑批的 CLI/JSON/崩溃行、Web 历史、
  问答多轮与 `/api/ask` 的 history。
- 去死代码：`config.toml` 里的 `seed` 从来没被读过（远端模型本来也没法靠它复现），
  `Dataset.find` 也没人调，一并删掉。
- 工程门槛：`ruff check .`（E/F/I/UP/B/SIM/RUF/S/PLW + 忽略中文全角标点的 RUF001-003）
  与 `mypy`（`src/autoflux` 全量，37 个文件）都零报错；CI 里两条都跑，另加覆盖率
  ≥85% 的底线（当前 91%）。`py.typed` 随包发布，`.editorconfig`、`CONTRIBUTING.md` 补齐。
- 照着 mypy 修出来的三处真问题：`SqliteSaver` 的 `put/put_writes/get_tuple/list` 签名
  对齐 LangGraph 1.x 的 `RunnableConfig`（`put` 现在把带新 `checkpoint_id` 的 config 还回去）；
  `Skillbook.add` 在 `lastrowid` 为 None 时不再 `int(None)` 崩；模型传输层拒掉非
  http/https 端点（`file://` 之类打不开本地文件）。`Tool` 协议改成只读的
  `run: Callable[..., str]`，工具清单才通得过类型检查。
- 测试 147 → 148（新增「传输层拒绝 file:// 端点」）。

## 0.5.0 — 2026-11-20

- 新增 `autoflux ask` 与 `POST /api/ask`：先让模型答一版，再用 `verify()` 核对答案里的数字，
  编了就把具体问题塞回去重写。就业示例的问答部分终于有了入口。
- 修 `Dataset.falling`：负增长行业按原表顺序排，不再跟着工资排名走。
- 修 `verify()` 的容差：去掉 0.5% 的相对误差，`150000` 这类编的数不再被 `150285` 认下来。
- 就业示例：表里负增长的是两个行业（房地产业、租赁和商务服务业），README、判分脚本、
  参照报告统一成同一口径。
- 补上 `LICENSE`、`.env.example`；CI 加 Python 3.13；容器镜像带上 `examples/`，
  `/api/ask` 在 Docker 里也能找到默认数据表。
- 测试从 122 增到 131：问答层的编数打回、重写提示词、命令行接线、示例判分脚本自检。
