# 参与进来

这个项目的规则很少，但有几条是硬的。

## 环境

```bash
python -m venv .venv
.venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -e .
pip install ruff mypy coverage
```

Python 3.11+。`tests/__init__.py` 会把 `src/` 放进 `sys.path`，所以不装也能跑测试。

## 提交前的三条门槛

```bash
ruff check .
mypy
python -m unittest discover -s tests -t .
```

前两条必须零报错（CI 也一样）。覆盖率底线 85%：

```bash
coverage run --source=src/autoflux -m unittest discover -s tests -t .
coverage report --fail-under=85
```

改到 `graph.py` 的停止逻辑、`evaluator.py` 的判分、`employment/verify.py` 的数字核对时，
顺手补一个「先失败、改完通过」的用例——这三处出错的方式都很安静。

## 代码约定

- **注释写「为什么」**，不写「做了什么」。`# 拿到 rowid 再转 int` 这种没用；
  `# LangGraph 1.x 要求 put 把带新 checkpoint_id 的 config 还回去` 才有用。
- **分数只能来自 evaluator**。任何「模型自己说做完了」就当通过的路子都不要进主干。
- **提示词里不能有隐藏用例**。`test_blind_task` 和 `test_prompt_contract` 盯着这条。
- 中文是主要书写语言，日志/报错也写中文；标识符和 API 保持英文。
- 工具只能在工作区内读写（`WorkspaceTool._resolve` 拦 `..`），新工具必须继承它。

## 加一个 bench 任务

在 `bench/tasks/<名字>/` 下放：

```
task.json     {"goal": "一句话目标", "check": "{python} -m unittest discover -q"}
project/      起始工作区（故意坏着）
```

跑 `python run.py bench --tasks <名字> --repeats 1 --max-steps 30` 试一次。
任务不要泄漏答案：判定用的隐藏用例放 `src/autoflux/tasks/bugfix/hidden/` 那一类位置，
而不是 `project/` 里。

## 加一个新的任务类型

实现 `autoflux.protocols.Task`：`name`、`prepare(dest)`、`evaluate(workspace) -> Score`，
必要的话再加 `brief()`（给模型的任务说明）和 `diagnose(workspace)`（反思时能看到的细节）。
然后在 `autoflux/tasks/__init__.py` 里注册。

## 提交信息

一行说清改了什么，正文写为什么。示例：

```
修 resume 会覆盖工作区

resume 分支也调了 task.prepare，上一轮改到一半的文件被起始目录重新铺了一遍。
现在只有全新跑才 prepare。
```
