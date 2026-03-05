# Agent Wave (`agvv`)

`agvv` 是一个面向编码 Agent 的轻量任务编排工具。
它为每个任务创建隔离的 git worktree，在后台 tmux 会话中运行 agent，并把任务状态持久化到 SQLite。

## 它能做什么

- 用 `git worktree` 隔离任务改动（`main` + 每个 feature 独立工作树）。
- 用 `tmux` 后台运行 agent，关闭终端后任务仍可继续。
- 用 SQLite 持久化任务状态/事件（`pending`、`running`、`done`、`failed`、`timed_out`、`cleaned`）。
- 提供统一命令：`task run/status/retry/cleanup` 与 `daemon run`。

## 环境要求

- Python `>=3.10`
- `git`
- `tmux`
- `PATH` 中可用的编码 agent 命令：
  - `codex`（默认）
  - `claude`（使用 `--agent claude` 时）
- `uv`（推荐用于安装和运行）

## 安装

PyPI 安装：

```bash
uv tool install agent-wave
agvv --help
```

源码运行：

```bash
uv sync --dev
uv run agvv --help
```

## 快速开始

### 1）编写 `task.md`

把完整开发需求写到 Markdown 文件中。

### 2）编写 `task.json`

最小合法示例：

```json
{
  "project_name": "demo",
  "feature": "feat_demo",
  "task_doc": "./task.md"
}
```

`task_doc` 和 `requirements` 至少要提供一个。

### 3）启动任务

在已有本地仓库上运行：

```bash
agvv task run --spec ./task.json --project-dir /path/to/repo
```

创建受管新项目（在当前目录下）：

```bash
agvv task run --spec ./task.json
```

改用 Claude Code：

```bash
agvv task run --spec ./task.json --agent claude
```

### 4）查看与推进状态

```bash
agvv task status
agvv daemon run --once
```

需要重复执行 `daemon run --once`，状态才会从 `running` 推进到 `done/timed_out`。

### 5）重试与清理

重试任务：

```bash
agvv task retry --task-id <task_id>
```

重试时强制重启已有 tmux 会话：

```bash
agvv task retry --task-id <task_id> --force-restart
```

清理任务资源：

```bash
agvv task cleanup --task-id <task_id>
```

工作树有未提交改动时强制清理：

```bash
agvv task cleanup --task-id <task_id> --force
```

## `task.json` 约定（CLI）

### 必填字段

- `project_name`：匹配 `^[A-Za-z0-9_-]+$`
- `feature`：匹配 `^[A-Za-z0-9_-]+$`，且不能是 `main` 或 `repo.git`
- 二选一至少一个：
  - `task_doc`（必须以 `.md` 结尾）
  - `requirements`（非空字符串）

### 常用可选字段

- `repo`：可选仓库标识
- `from_branch`：feature 工作树基线分支（默认 `main`）
- `session`：自定义 tmux 会话名
- `constraints`：额外约束列表
- `timeout_minutes`：会话超时分钟数（默认 `240`）
- `agent_extra_args`：传给 agent 命令的额外参数

### 关键运行时行为

- `task_id` 由运行时生成，`task.json` 中的同名字段会被忽略。
- spec 内的 `agent`/`agent_model` 会被运行时重置；如需切换 provider，请用 CLI `--agent`。
- spec 内 `base_dir` 会被运行时覆盖：
  - 不传 `--project-dir`：使用当前工作目录
  - 传 `--project-dir`：使用该目录的父目录

## CLI 命令速查

```bash
agvv task run --spec <path> [--db-path <path>] [--agent <codex|claude|claude_code>] [--agent-non-interactive|--agent-interactive] [--project-dir <path>]
agvv task status [--db-path <path>] [--task-id <id>] [--state <pending|running|done|failed|timed_out|cleaned>]
agvv task retry --task-id <id> [--db-path <path>] [--session <name>] [--force-restart]
agvv task cleanup --task-id <id> [--db-path <path>] [--force]
agvv daemon run [--db-path <path>] [--once] [--interval-seconds <n>] [--max-loops <n>] [--max-workers <n>]
```

## 数据与目录布局

- 默认数据库路径：`~/.agvv/tasks.db`
- 可通过 `--db-path` 或环境变量 `AGVV_DB_PATH` 覆盖
- 受管项目目录结构：

```text
<runtime_base>/<project_name>/
  repo.git/      # 裸仓库
  main/          # 主工作树
  <feature>/     # 某个任务的 feature 工作树
```

## 说明

- `daemon run --once` 是后台任务状态流转的必要步骤。
- `task cleanup` 会删除 feature 工作树，并在受管仓库中删除该 feature 分支。
