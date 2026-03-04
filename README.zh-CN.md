# Agent Wave Skill (`agvv`)

[English README](./README.md)

Agent Wave 是一个给编码 Agent 使用的工具。  
它会为每个任务创建独立 Git worktree、在 `tmux` 中运行 Agent、用 SQLite 记录任务状态，并帮助任务从编码走到 PR。

这个仓库最终会打包成一个可复用 skill。  
本文档重点是“使用者如何使用这个 skill”，不讲复杂实现细节。

## 适用人群

- 你在用 AI Agent 做开发任务。
- 你希望并行开发更安全（不直接在主分支工作区改代码）。
- 你希望有清晰的命令流程：启动、监控、重试、清理。

## 这个 Skill 能做什么

对每个任务，Agent Wave 会：

1. 在标准目录结构中创建 feature worktree。
2. 在独立 `tmux` session 中启动 Agent 命令。
3. 在本地 SQLite 数据库中记录任务生命周期和错误。
4. 帮助代码进入 PR，并跟进 PR 反馈循环。
5. 提供重试和清理命令，方便运维。

## 依赖要求

- Python `>=3.10`
- `git`
- `tmux`
- `gh`（GitHub CLI，需要先登录）
- `uv`
- 已配置的 git 远端（受管项目仓库默认远端名为 `origin`）

## 安装与检查

```bash
uv tool install agvv
agvv --help
```

如果你把它当作 skill 使用，请确保 Agent 的运行环境里可以直接调用 `agvv`。
如果你在本仓库本地开发，请使用 `uv sync --dev`，并通过 `uv run agvv ...` 运行命令。
任务规格文件仅支持 JSON。

## 5 分钟快速开始

### 1）准备任务规格文件

创建 `task.json`：

```json
{
  "task_id": "demo_task_1",
  "project_name": "demo",
  "feature": "feat_demo",
  "repo": "owner/repo",
  "base_dir": "~/Code",
  "from_branch": "main",
  "agent": {
    "provider": "codex",
    "model": "gpt-5",
    "extra_args": ["--approval-mode", "auto"]
  },
  "create_dirs": ["src", "tests"],
  "pr_title": "[agvv] feat_demo",
  "pr_body": "Implement demo feature",
  "timeout_minutes": 240,
  "max_retry_cycles": 5,
  "auto_cleanup": true
}
```

### 2）启动任务

```bash
agvv task run --spec ./task.json [--project-dir /path/to/existing/repo]
```

输出中会包含 task id、状态和 tmux session 名称。
如果传入 `--project-dir`，会自动按已有项目执行 adopt。
如果不传入，会自动初始化新项目布局（init）后再启动任务。

### 3）查看状态

```bash
agvv task status
```

### 4）执行一次调度

```bash
agvv daemon run --once
```

这是 skill 的核心循环：检查活跃任务并推进状态。

## 命令说明（面向使用者）

### `task run`

根据 JSON spec 创建并启动任务：

```bash
agvv task run --spec ./task.json [--db-path ./tasks.db] [--agent codex] [--model gpt-5] [--project-dir /path/to/repo]
```

常见用途：启动新任务，也可以临时覆盖 agent/model。
行为说明：
- 传入 `--project-dir`：自动 adopt 现有本地项目；
- 不传入 `--project-dir`：自动 init 新项目布局。

### `task status`

查看任务和当前状态：

```bash
agvv task status [--db-path ./tasks.db] [--task-id demo_task_1] [--state coding]
```

常见用途：监控多个任务，或筛选单个任务。

### `task retry`

重试可恢复任务：

```bash
agvv task retry --task-id demo_task_1 [--db-path ./tasks.db] [--session custom-session]
```

常见用途：失败后恢复、超时后重试、收到 PR 反馈后继续。

### `task cleanup`

停止 session 并清理任务资源：

```bash
agvv task cleanup --task-id demo_task_1 [--db-path ./tasks.db] [--force]
```

常见用途：合并/关闭后清理，或必要时强制清理。

### `daemon run`

运行一次或持续运行任务调度：

```bash
agvv daemon run [--db-path ./tasks.db] [--once] [--interval-seconds 30] [--max-loops 10] [--max-workers 1]
```

常见用途：脚本里用 `--once`，长期自动化用循环模式。

## Task Spec 常用字段

必填字段：

- `project_name`
- `feature`
- `repo`
- `base_dir`

高频字段：

- `task_id`：自定义任务 ID（不填会自动生成）
- `task_id` 格式：仅允许字母、数字、`_`、`-`
- `base_dir`：项目/worktree 根目录（必填）
- `from_branch`：起始分支（默认 `main`）
- `session`：tmux session 名称覆盖（默认 `agvv-<task_id>`）
- `agent`：
  - `provider`：`codex` 或 `claude_code`（也接受 `claude` / `claude-code`）
  - `model`：可选模型名
  - `extra_args`：可选参数列表
- `agent_cmd`：可选完整命令覆盖（不填则按 provider/model/extra_args 自动生成）
- `ticket`：可选外部需求单号，会写入任务上下文
- `params`：可选键值参数，会写入任务上下文
- `create_dirs`：预创建目录
- `pr_title` / `pr_body`：PR 标题与描述
- `task_doc`：可作为 PR 描述的文件路径
- `pr_base`：PR 目标分支（默认与 `from_branch` 一致）
- `branch_remote`：推送使用的远程名（默认 `origin`）
- `commit_message`：最终提交时的自定义 commit message
- `timeout_minutes`：超时时间
- `max_retry_cycles`：PR 反馈最大自动修复轮次
- `auto_cleanup`：合并/关闭/超时后自动清理
- `keep_branch_on_cleanup`：清理时保留分支

## 推荐 Skill 使用流程

把这个仓库当 skill 使用时，可以按下面流程：

1. Agent 接收需求。
2. Agent 生成 `task.json`。
3. Agent 执行 `agvv task run`。
4. Agent 或自动化定时执行 `agvv daemon run --once`。
5. Agent 执行 `agvv task status` 查看结果。
6. 必要时执行 `agvv task retry` 或 `agvv task cleanup`。

## 状态含义（简明版）

- `pending`：任务已创建，等待启动
- `coding`：Agent 编码中
- `pr_open`：代码已推送，PR 已打开
- `pr_merged`：PR 已合并
- `pr_closed`：PR 已关闭（未合并）
- `timed_out`：任务超时
- `failed`：任务失败
- `cleaned`：资源已清理
- `blocked`：任务被阻塞

## 环境变量

- `AGVV_DB_PATH`：任务 SQLite 数据库默认路径

## 常见问题

- `tmux not found`：先安装 `tmux`。
- `gh` 相关报错：先执行 `gh auth login` 并确认仓库权限。
- `No git remote 'origin' configured`：先配置远端（例如 `git -C <managed-repo.git> remote add origin <repo-url>`），或改用/配置 `branch_remote` 指定的远端。
- `Task id already exists`：更换 `task_id` 或复用已有任务。
- `Feature worktree has uncommitted changes`：先提交/暂存，或使用 `task cleanup --force`。
- `Unsupported agent provider`：仅支持 `codex` 与 `claude_code`。
