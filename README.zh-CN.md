# Agent Wave (`agvv`)

[English README](./README.md)

`agvv` 用于把一个开发任务放到独立 git worktree 中执行，并用 SQLite 记录状态。

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

```json
{
  "project_name": "demo",
  "feature": "feat_demo",
  "repo": "owner/repo",
  "task_doc": "./task.md",
  "create_dirs": ["src", "tests"],
  "pr_title": "[agvv] feat_demo"
}
```

### 2）启动任务

已有本地仓库：

```bash
agvv task run --spec ./task.json --project-dir /path/to/repo
```

在当前目录新建受管项目：

```bash
agvv task run --spec ./task.json
```

### 3）查看与推进

```bash
agvv task status
agvv daemon run --once
```

## 常用命令

```bash
agvv task run --spec ./task.json [--db-path ./tasks.db] [--agent codex] [--agent-non-interactive/--agent-interactive] [--project-dir /path/to/repo]
agvv task status [--db-path ./tasks.db] [--task-id <task_id>] [--state coding]
agvv task retry --task-id <task_id> [--db-path ./tasks.db] [--session custom-session] [--force-restart]
agvv task cleanup --task-id <task_id> [--db-path ./tasks.db] [--force]
agvv daemon run [--db-path ./tasks.db] [--once] [--interval-seconds 30] [--max-loops 10] [--max-workers 1]
```

## `task.json` 规则

必填：

- `project_name`
- `feature`
- `repo`

必填：

- `task_doc`（强制为 Markdown `.md`；把详细 requirements / constraints / acceptance criteria 都写在这里）

推荐：

- `pr_title`、`pr_body`、`pr_base`
- `branch_remote`（默认 `origin`）

运行时会忽略（不要依赖）：

- `task_id`
- `agent`
- `agent_model`
- `agent_extra_args`
- `agent_cmd`
- `from_branch`

说明：

- `task.json` 保持精简，只放任务标识和流程元信息。
- 具体开发要求请写在 `task_doc`，不要放到 `requirements` / `constraints` 等字段。
- `task_doc` 是必填项，且必须以 `.md` 结尾。
- `acceptance_criteria` 若填写，必须为 2-5 条。
- 不填写时，运行时会注入默认 2 条。
- `base_dir` 由运行时推导：
  - 传 `--project-dir`：取其父目录
  - 不传：取当前工作目录

## 运行产物（在 worktree 的 `.agvv/` 下）

- `input_snapshot.json`
- `rendered_prompt.md`
- `agent_output.log`
- `agent_output_summary.txt`
- `dod_result.json`（finalize 前必需）

## 常见问题

- `tmux not found`：安装 `tmux`。
- `gh` 认证问题：执行 `gh auth login`。
- `No git remote 'origin' configured`：先在受管仓库配置远端，例如：`git -C <base_dir>/<project_name>/repo.git remote add origin <repo-url>`。
