# Agent Wave (`agvv`)

[English README](./README.md)

`agvv` 是一个专为 AI Agent（如 Codex、Claude 等）设计的安全、并发执行环境。它通过底层的 `git worktree` 技术实现物理隔离，并使用 `SQLite` 实现并发安全的状态追踪。

## 核心特性

1. **绝对隔离 (`git worktree`)**：AI Agent 所有的代码生成和修改都会在一个专属的隐藏工作树中进行，绝对不会污染你的主分支或当前开发目录。
2. **并发后台执行 (`tmux`)**：任务运行在隐藏的 tmux 会话中。你可以随时关闭终端，甚至同时拉起十几个 Agent 并发写不同的需求。
3. **状态容灾 (`sqlite3`)**：所有任务状态都存在 SQLite 数据库中。与脆弱的 JSON 文件相比，SQLite 提供行级并发锁和掉电保护，哪怕服务异常退出任务记录也绝对不会丢失。

## 你需要准备

- Python `>=3.10`
- `git`、`tmux`、`gh`（已登录）
- `uv`

## 安装

```bash
uv tool install agvv
agvv --help
```

源码方式：

```bash
uv sync --dev
uv run agvv --help
```

## 快速开始

### 1）写 `task.json`（只放核心元信息）

保持此文件极简，具体的开发需求应该写在 Markdown 格式的文档里。

```json
{
  "project_name": "demo",
  "feature": "feat_demo",
  "repo": "owner/repo",
  "task_doc": "./task.md"
}
```

### 2）写 `task.md`

在这个 Markdown 文件里，用自然语言把你想让 AI 写的代码需求描述清楚。

### 3）启动任务

如果你想在现有的代码库上让 Agent 开发：

```bash
agvv task run --spec ./task.json --project-dir /path/to/repo
```

如果你想从零开始一个全新项目：

```bash
agvv task run --spec ./task.json
```

### 4）查看与推进

检查你当前提交的所有任务及其状态：

```bash
agvv task status
```

运行后台守护进程（它会自动检查任务是否结束或超时，并流转状态）：

```bash
agvv daemon run --once
```

## 清理任务

任务完成后，你可以随时安全地删掉那个被隔离出来的工作区，不用担心影响你的主仓库：
```bash
agvv task cleanup --task-id <task_id>
```

## 常见问题

- `tmux not found`：安装 `tmux`。
- `gh` 认证问题：执行 `gh auth login`。
- `No git remote 'origin' configured`：先在受管仓库配置远端，例如：`git -C <base_dir>/<project_name>/repo.git remote add origin <repo-url>`。
