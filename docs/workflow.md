# agvv 工作流

## 完整生命周期

一个 task 从创建到完成的典型流程：

```
task add → run(implement) → checkpoint → run(review/test)
    → 通过 → merge
    → 未通过 → run(repair) → checkpoint → run(review/test) → ...
```

## 流程详解

### 1. 添加任务

Orchestrator agent 准备 task.md，调用 agvv 注册：

```bash
agvv task add --project ~/projects/my-project --file task.md
```

agvv 读取文件，提取 ID，在项目仓库中创建 `.agvv/tasks/<id>/task.md`，标记 `status: pending`。

### 2. 启动实现

Orchestrator agent 指定 purpose 和 agent 类型：

```bash
agvv run start fix-login-bug --purpose=implement --agent=codex
```

agvv 内部：
1. 创建 git worktree（如果该 task 还没有）
2. 执行 `before_run` hook
3. 启动 coding agent 子进程，工作目录指向 worktree
4. 更新 task status 为 `running`
5. daemon 开始监控进程

### 3. Coding agent 工作

Coding agent 在独立 worktree 中编码。完成后产出 checkpoint：
- 代码变更
- 上下文文件（结果摘要、变更说明）
- 通过 git commit 持久化

### 4. Run 完成

agvv 检测到进程退出：
1. 执行 `after_run` hook
2. 记录 run 结果到 `.agvv/tasks/<id>/runs/`
3. 更新 task status
4. 通知 orchestrator agent

### 5. Orchestrator agent 评估

Orchestrator agent 查看结果：

```bash
agvv checkpoint show fix-login-bug
```

根据结果做判断：
- **结果正常** → 启动 review 或 test
- **结果失败** → 重试、repair、或放弃
- **超时/stall** → 重试或调整参数

### 6. Review / Test

```bash
agvv run start fix-login-bug --purpose=review --agent=claude
agvv run start fix-login-bug --purpose=test --agent=codex
```

同样的 run 机制，不同的 purpose。Review/test agent 在同一个 worktree 上工作，能看到之前的 checkpoint。

### 7. 合并

审查通过后，orchestrator agent 指示合并：

```bash
agvv task merge fix-login-bug
```

agvv 内部：
1. 尝试将 worktree 分支合并到主分支
2. 成功 → 清理 worktree，更新 task status 为 `done`
3. 冲突 → 报错，通知 orchestrator agent 决策

## 并行工作

多个 task 可以同时进行：

```bash
# Orchestrator agent 同时启动三个任务
agvv run start feature-1 --purpose=implement --agent=claude
agvv run start feature-2 --purpose=implement --agent=pi
agvv run start fix-bug-1 --purpose=implement --agent=codex
```

每个 task 在独立 worktree 中并行工作，互不干扰。合并时可能出现冲突，由 orchestrator agent 决定处理方式。

## 合并冲突处理

当 `agvv task merge` 遇到冲突时：

1. agvv 报告冲突，列出冲突文件
2. Orchestrator agent 决定处理方式：
   - 启动一个 `purpose=repair` 的 run，让 coding agent 解决冲突
   - 调整合并顺序（先合并无冲突的 task）
   - 其他策略

## 状态查询

Orchestrator agent 随时可以查询全局状态：

```bash
agvv run status                          # 所有项目的 run 状态
agvv task list --project ~/projects/x    # 某项目的所有 task
agvv task show fix-login-bug             # 某个 task 的详情和 run 历史
```
