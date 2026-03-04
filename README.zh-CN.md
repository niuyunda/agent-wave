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
任务规格文件仅支持 JSON，且建议只描述开发需求本身。

## 5 分钟快速开始

### 1）准备任务规格文件

创建 `task.json`：

```json
{
  "project_name": "demo",
  "feature": "feat_demo",
  "repo": "owner/repo",
  "requirements": "实现 demo 功能",
  "constraints": ["不修改公开 API"],
  "acceptance_criteria": ["相关测试通过"],
  "create_dirs": ["src", "tests"],
  "pr_title": "[agvv] feat_demo",
  "pr_body": "Implement demo feature",
  "timeout_minutes": 240,
  "max_retry_cycles": 5,
  "auto_cleanup": true
}
```

### 2）配置 git 远端（必需）

在执行 `task run` 前，请先为受管裸仓库配置推送远端：

```bash
git -C ./demo/repo.git remote add origin <repo-url>
```

请按你的 `project_name` 替换路径。
如果你在 spec 中通过 `branch_remote` 使用了非默认远端名，请配置对应远端。

### 3）启动任务

```bash
agvv task run --spec ./task.json [--project-dir /path/to/existing/repo]
```

输出中会包含 task id、状态和 tmux session 名称。
如果传入 `--project-dir`，会自动按已有项目执行 adopt。
如果不传入，会自动初始化新项目布局（init）后再启动任务。

### 4）查看状态

```bash
agvv task status
```

### 5）执行一次调度

```bash
agvv daemon run --once
```

这是 skill 的核心循环：检查活跃任务并推进状态。

## 命令说明（面向使用者）

### `task run`

根据 JSON spec 创建并启动任务：

```bash
agvv task run --spec ./task.json [--db-path ./tasks.db] [--agent codex] [--project-dir /path/to/repo]
```

常见用途：启动新任务，也可以临时覆盖 agent provider。
行为说明：
- 传入 `--project-dir`：自动 adopt 现有本地项目；
- 不传入 `--project-dir`：自动 init 新项目布局。
- 运行时会忽略 spec 里的 `task_id`、`agent*`、`agent_cmd`、`from_branch`。

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

高频字段：

- `task_id`：可写可不写；运行时会自动生成并忽略 spec 中该值
- `base_dir`：可选；运行时会自动按 CLI 上下文决定（通常无需填写）
- `ticket`：可选外部需求单号，会写入任务上下文
- `requirements`：任务主需求文本（作为传给 Agent 的单一事实源）
- `constraints`：可选约束列表（实现时必须满足）
- `acceptance_criteria`：可选验收标准清单（完成定义）
- `params`：可选键值参数，会写入任务上下文
- `create_dirs`：预创建目录
- `pr_title` / `pr_body`：PR 标题与描述
- `task_doc`：可选需求/说明文档路径；当 `requirements` 或 `pr_body` 缺失时作为兜底
- `pr_base`：PR 目标分支（默认 `main`）
- `branch_remote`：推送使用的远程名（默认 `origin`）
- `commit_message`：最终提交时的自定义 commit message
- `timeout_minutes`：超时时间
- `max_retry_cycles`：PR 反馈最大自动修复轮次
- `auto_cleanup`：合并/关闭/超时后自动清理
- `keep_branch_on_cleanup`：清理时保留分支

DoD 说明：

- `acceptance_criteria` 为可机读字段；若填写，必须是 2-5 条。
- 若不填写，运行时会注入稳定的默认 2 条验收项。
- PR finalize 前，Agent 必须写入 `.agvv/dod_result.json`，并将每条验收项标记为通过。

运行时会忽略的 spec 字段：

- `task_id`
- `agent`
- `agent_model`
- `agent_extra_args`
- `agent_cmd`
- `from_branch`

任务启动后，会在 feature worktree 写入最小审计文件：

- `.agvv/input_snapshot.json`：本次运行使用的输入快照
- `.agvv/rendered_prompt.md`：最终传给 Agent 的 prompt
- `.agvv/agent_output.log`：Agent 标准输出/错误输出日志
- `.agvv/agent_output_summary.txt`：收尾阶段输出摘要（finalize 前生成）
- `.agvv/dod_result.json`：Agent 产出的 DoD 机读校验结果（finalize 必需）

`base_dir` 的运行时规则：

- 传入 `--project-dir`：使用该路径的父目录作为 `base_dir`
- 不传 `--project-dir`：使用当前工作目录作为 `base_dir`，并自动创建 `<cwd>/<project_name>/...` 目录布局
- 因此建议 `task.json` 中不填写 `base_dir`

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
- `Feature worktree has uncommitted changes`：先提交/暂存，或使用 `task cleanup --force`。
- `Unsupported agent provider`：仅支持 `codex` 与 `claude_code`。
