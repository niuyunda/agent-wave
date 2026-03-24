# Agent Wave (`agvv`)

`agvv` 是一个面向编码 Agent 的轻量任务编排工具。
它为每个任务创建隔离的 git worktree，通过 `acpx` 启动 agent 会话，并将任务状态持久化到 SQLite。

## 它能做什么

- 用 `git worktree` 隔离任务改动（主工作树 + 每个 feature 独立工作树）。
- 通过 `acpx` 启动 agent（`codex` 或 `claude`），并在 `.agvv/` 写入启动产物。
- 用 SQLite 持久化任务状态/事件（`pending`、`running`、`done`、`failed`、`timed_out`、`cleaned`）。
- 提供统一命令：`task run/status/retry/cleanup` 与 `daemon run`。

## 环境要求

- Python `>=3.10`
- `git`
- `acpx`
- `PATH` 中可用的编码 agent 命令：
  - `codex`（默认）
  - `claude`（使用 `--agent claude` 或 `--agent claude_code` 时）
- `uv`（推荐用于安装和运行）

Agent provider 说明：

- `--agent claude` 与 `--agent claude_code` 是等价输入。
- 两者都会归一化到内部 provider `claude_code`，实际调用 `claude` 可执行文件。

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

### 1）编写 `task.md`（YAML + Markdown）

`task.md` 由 YAML front matter + Markdown 正文组成：

```md
---
project_name: demo
feature: feat/demo
repo: owner/repo
constraints:
  - 保持现有 API 兼容性。
---

## 目标
实现所需功能并补充测试。
```

Markdown 正文会作为主需求文本。

### 2）启动任务

在已有本地仓库上运行：

```bash
agvv task run --spec ./task.md --project-dir /path/to/repo
```

创建受管新项目（在当前目录下）：

```bash
agvv task run --spec ./task.md
```

改用 Claude Code：

```bash
agvv task run --spec ./task.md --agent claude
```

### 3）查看与推进状态

```bash
agvv task status
agvv daemon run --once
```

重复执行 `daemon run --once` 以推进活跃任务状态。

### 4）重试与清理

重试任务：

```bash
agvv task retry --task-id <task_id>
```

重试时强制重启已有会话：

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

## `task.md` 约定（CLI）

### 必填字段

- 由 `---` 包裹的 YAML front matter
- `project_name`：`^[A-Za-z0-9_-]+$`
- `feature`：`^[A-Za-z0-9_-]+(/[A-Za-z0-9_-]+)*$`
  - 支持 `feat/demo` 这类带斜杠命名
  - 保留值：`main`、`worktrees`
- 需求文本必须存在：
  - 推荐：Markdown 正文
  - 兜底：front matter 的 `requirements`（非空字符串）

### 常用可选字段

- `repo`：可选仓库标识
- `from_branch`：feature 工作树基线分支（默认 `main`）
- `session`：自定义 `acpx` 会话名
- `ticket`：可选工单标识（仅元数据）
- `constraints`：额外约束列表
- `timeout_minutes`：会话超时分钟数（默认 `240`）
- `agent_extra_args`：传给所选 agent 命令的额外参数

### 关键运行时行为

- `task_id` 由运行时生成，front matter 中同名字段会被忽略。
- front matter 的 `agent`/`agent_model` 会被运行时重置；切换 provider 请使用 CLI `--agent`。
- front matter 的 `base_dir` 会被运行时覆盖：
  - 不传 `--project-dir`：使用当前工作目录
  - 传 `--project-dir`：使用该目录的父目录

## CLI 命令速查

```bash
agvv task run --spec <path> [--db-path <path>] [--agent <codex|claude|claude_code>] [--project-dir <path>]
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
  .git/                  # git 仓库元数据
  worktrees/             # feature 工作树（通过 .git/info/exclude 忽略）
    feat-<slug>/         # 每个 feature 一个工作树（"/" -> "-"）
```

## 说明

- `daemon run --once` 会将活跃任务（`pending`/`running`）推进到最新状态。
- `task cleanup` 默认会删除 feature 工作树并删除对应分支。
