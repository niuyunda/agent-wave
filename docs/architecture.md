# agvv 架构

## 运行模式

agvv 以 daemon 形式运行，在后台持续监控所有已注册项目的任务和运行状态。

```bash
agvv daemon start    # 启动后台进程
agvv daemon stop     # 停止
```

daemon 的内存状态是缓存，不是真相。真相永远在各项目仓库的 `.agvv/` 文件中。daemon 重启后从文件重建状态。

## 状态持久化

所有持久状态存储在项目仓库内：

```
my-project/
├── src/
├── .agvv/
│   ├── config.md              # 项目级配置
│   └── tasks/
│       └── fix-login-bug/
│           ├── task.md        # orchestrator agent 提交的任务描述
│           └── runs/          # agvv 自动维护的 run 记录
│               ├── 001-implement.md
│               └── 002-review.md
└── package.json
```

### task.md 格式

front matter 给 agvv 机器读，body 给 coding agent 读：

```markdown
---
status: pending
created_at: 2026-03-30
---

## 目标
修复登录页面在 Safari 下的白屏问题

## 上下文
用户反馈 Safari 17 下点击登录按钮后页面白屏。
相关文件：src/pages/login.tsx, src/styles/auth.css

## 验收标准
- Safari 17 下登录流程正常
- 现有测试通过
```

front matter 中 `status` 由 agvv 管理，orchestrator agent 提交时无需填写。

### run 记录格式

每次 run 完成后 agvv 自动生成：

```markdown
---
purpose: implement
agent: codex
status: completed
started_at: 2026-03-30T10:00:00Z
finished_at: 2026-03-30T10:15:00Z
checkpoint: abc1234
---

## 结果摘要
修复了 CSS 兼容性问题，添加了 Safari 专用的 flex 布局回退方案。

## 变更文件
- src/styles/auth.css
- src/pages/login.tsx
```

run 记录的 body 由 coding agent 在 checkpoint 中提供，agvv 负责归档。

## 全局注册表

daemon 需要知道它管理哪些项目：

```
~/.agvv/projects.md
---
projects:
  - path: ~/projects/my-project
  - path: ~/projects/another-project
---
```

## Worktree 管理

Worktree 是 agvv 的内部实现细节，不对 orchestrator agent 暴露。

- `agvv run start` 时自动创建 worktree（如果该 task 还没有）
- 一个 task 对应一个 worktree，多次 run 复用
- `agvv task merge` 后自动清理 worktree
- task 被删除或归档时清理 worktree

### 路径安全

- worktree 路径必须在 workspace root 内
- task ID 仅允许 `[A-Za-z0-9._-]`
- 创建时做 symlink-safe 规范化校验，防止路径穿越

### Hooks

在 worktree 生命周期的关键节点执行 shell 脚本，在 `config.md` 中配置：

```yaml
hooks:
  after_create: "./scripts/bootstrap.sh"    # 首次创建后（装依赖等）
  before_run: "./scripts/pre-check.sh"      # 每次 run 前（失败则中止 run）
  after_run: "./scripts/cleanup.sh"         # 每次 run 后（失败只记录）
```

Hooks 在 worktree 目录下执行，有超时限制。

## 进程监控

daemon 持续监控所有 coding agent 进程：

- **超时检测**：run 超过配置时限，标记为 `timed_out`
- **Stall 检测**：run 长时间无输出，标记为 `stalled`
- 检测到异常后通知 orchestrator agent，不做决策

## 并发控制

- agvv 内置 `max_concurrent_runs` 硬上限
- 超出时拒绝启动新 run，返回错误
- orchestrator agent 负责决定优先级和排队策略

## 启动对账（Reconciliation）

daemon 启动时从文件系统重建真实状态：

- 扫描所有项目的 `.agvv/tasks/` 目录
- 检查标记为 `running` 的 task，对应进程是否存活
- 进程已死但状态未更新的，自动修正为 `failed`
- 检查 worktree 是否实际存在

## 通知机制

agvv 在状态变更时主动通知 orchestrator agent（具体协议取决于 OpenClaw 机制），同时支持轮询作为兜底。

状态变更事件包括：

- run 完成（成功/失败/超时/stall）
- task 状态变化
- 合并成功/冲突
