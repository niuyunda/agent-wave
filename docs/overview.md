# agvv 总览

## 定位

agvv 是一个纯确定性的项目编排引擎，以 CLI + daemon 的形式运行。它为 orchestrator agent 提供多项目、多任务并行编码所需的全部机械性能力。

agvv 不含 LLM，不做任何需要判断的决策。遇到决策点时，agvv 暴露状态并通知 orchestrator agent，由其做出判断后通过 CLI 下达指令。

## 核心原则

**代码库即真相** — 无数据库。所有持久状态以文件形式存在于项目仓库的 `.agvv/` 目录中。任何 agent 进入项目仓库即可获得完整上下文。

**Checkpoint 即 Git Commit** — 每次有意义的工作成果都体现为一次 git commit，包含代码变更和结构化上下文文件，让下一个 agent 无需聊天历史即可接续工作。

**纯工具，不做决策** — agvv 只执行机械性操作（创建 worktree、启动进程、记录状态、检测超时）。所有判断性决策（优先级、重试策略、结果评估）由 orchestrator agent 负责。

**最小设计** — 从第一性原理和奥卡姆剃刀出发，只保留必须的概念和模块。使用过程中遇到问题再考虑添加。

## 角色分工

```
用户
  ↕  对话
Orchestrator Agent（项目管理角色）
  │  - 理解用户意图，创建 task
  │  - 调 agvv 管理项目和任务
  │  - 在决策点做判断
  │  - 决定下一步动作
  ↕  CLI
agvv（确定性引擎）
  │  - task 状态管理
  │  - worktree 生命周期（内部实现，不对外暴露）
  │  - coding agent 进程管理
  │  - checkpoint commit
  │  - 超时/stall 检测
  │  - 并发控制
  │  - 状态变更通知
  ↕  子进程
Coding Agents（Codex / Claude / 其他）
  - 在独立 worktree 中执行具体编码工作
  - 完成后产出 checkpoint
```

Orchestrator agent 只关心"哪个项目有什么 task、目前状态如何"，不关心 worktree 怎么建、进程怎么管。

## 核心概念

整个系统只有三个核心概念：

### Task

一件需要完成的工作。由 orchestrator agent 以 Markdown + front matter 格式提交。

### Run

对某个 task 的一次执行。每个 run 有一个 purpose：

- `implement` — 实现功能或修复 bug
- `test` — 运行测试验证
- `review` — 代码审查
- `repair` — 修复上一次 run 发现的问题

一个 task 可以有多次 run（implement → review → repair → test → ...）。

### Checkpoint

一次 git commit。包含：

- 代码变更
- 结构化上下文文件（run 结果摘要、失败信息、下一步建议等）

下一个 agent 只需读取仓库中的文件就能接续工作，不依赖任何聊天历史。
