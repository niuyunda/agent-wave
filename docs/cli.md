# agvv CLI 参考

## daemon

```bash
agvv daemon start    # 启动后台 daemon
agvv daemon stop     # 停止 daemon
agvv daemon status   # 查看 daemon 运行状态
```

## project

```bash
agvv project add <path>     # 注册一个项目，agvv 在项目中初始化 .agvv/ 目录
agvv project list           # 列出所有已注册项目及状态概览
agvv project remove <path>  # 取消注册（不删除 .agvv/ 目录）
```

## task

```bash
agvv task add --project <path> --file <task.md>
# 将 task.md 注册到项目中
# agvv 从文件中读取 task ID，创建 .agvv/tasks/<id>/task.md

agvv task list [--project <path>]
# 列出所有 task 及状态
# 不指定 project 时列出所有项目的 task

agvv task show <task-id>
# 查看 task 详情：描述、当前状态、run 历史、最新 checkpoint

agvv task merge <task-id>
# 将 task 分支合并到主分支
# 成功后清理 worktree，标记 task 为 done
# 冲突时报错，等待 orchestrator agent 决策
```

## run

```bash
agvv run start <task-id> --purpose=<purpose> --agent=<agent>
# 启动一次 run
# purpose: implement | test | review | repair
# agent: codex | claude | pi | ...
# 自动创建 worktree（如果该 task 还没有）

agvv run stop <task-id>
# 停止当前正在进行的 run

agvv run status [--project <path>]
# 查看所有 run 的状态
# 不指定 project 时查看所有项目
```

## checkpoint

```bash
agvv checkpoint show <task-id>
# 查看 task 最新 checkpoint 的上下文信息
```

## 全局选项

```bash
--project <path>    # 指定项目路径，部分命令可省略（从 task-id 推断）
--json              # 以 JSON 格式输出，便于程序解析
--verbose           # 输出详细信息
```
