# AGVV Comprehensive Test Loop (Agent Playbook)

本文件是给执行型 Agent 的测试作战手册。目标是对 `agvv` 做持续、闭环、可追踪的全面测试。

## 1. 目标

- 在真实项目中验证 `agvv` 的任务编排、并行执行、评审、修复、合并与鲁棒性行为。
- 每轮测试都产出结构化报告，并驱动 `agvv` 本体修复。
- 持续循环直到无有效缺陷（见退出标准）。

## 2. 强制约束

- 测试根目录固定为 `~/projects/test/`。
- 测试项目目录按轮次命名：`test1`、`test2`、`test3` ...。
- 每轮至少覆盖以下场景：
  1. 新建项目目录
  2. 已有项目目录
  3. 已初始化 Git 仓库
  4. 未初始化 Git 仓库
- 每轮必须并行开发不少于 4 个 feature。
- 每个 feature 完成后，必须执行 review，再按 review 结果修复。
- 每轮必须包含一个完整前后端 Web 项目：
  - 前端：Next.js
  - 后端：FastAPI
  - 数据库：PostgreSQL（Docker 容器）
- 每轮必须产出测试报告，并据此修复 `agvv` 代码。
- 修复后进入下一轮回归，直到退出标准达成。

## 3. 轮次目录规范

以 `testN` 为当前轮次目录（`N` 从 1 开始递增）：

```text
~/projects/test/testN/
├── app-web/                 # Next.js + FastAPI + PostgreSQL 被测项目
├── cases/                   # 本轮其他场景项目（新建/已有/git/非git）
├── tasks/                   # 所有 task markdown
├── reports/
│   ├── feature/             # 各 feature 的 review/test 报告
│   ├── robustness/          # 鲁棒性专项报告
│   └── round-summary.md     # 本轮总报告
└── artifacts/               # 日志、命令输出、截图等证据
```

## 4. 每轮执行流程

### Phase A: 环境与能力探测

1. 创建轮次目录并记录时间戳。
2. 运行 `agvv --help`，记录可用命令面

### Phase B: 构造测试项目矩阵

在 `cases/` 下至少准备 4 个仓库，覆盖以下组合：

1. 新建目录 + 非 Git
2. 新建目录 + Git
3. 已有目录 + 非 Git
4. 已有目录 + Git（包含至少一次脏工作区）

要求对每个项目至少执行一次 `agvv tasks add`，并验证状态可观测。

### Phase C: 全栈项目并行 feature 开发（>=4）

在 `app-web` 中实现并行开发，至少 4 个 feature，建议如下：

1. `feat-api-auth`: FastAPI 鉴权与会话
2. `feat-api-crud`: FastAPI + PostgreSQL CRUD
3. `feat-ui-auth`: Next.js 登录与鉴权状态
4. `feat-ui-crud`: Next.js 列表/创建/编辑页面

数据库要求：使用 Docker 创建 PostgreSQL 容器（或 compose）。

关键检查：

- 并行 run 是否都进入运行态。
- 每个 feature 是否产生 checkpoint（新 commit）。
- 失败 run 是否有可读反馈与错误原因。

### Phase D: 对每个 feature 执行 review

对每个 feature 必须执行 review，并生成报告。

替代 review 路径（任选其一）：

1. 为任务重新添加 review任务：`agvv tasks add --project <repo> --file <task.md>` 并设置 purpose 为 review
2. 依赖 daemon 在任务完成后的自动 review 编排
3. 使用 `agvv feedback` 记录评审结果

### Phase E: 按 review 结果修复

- 为每个 feature 创建 `repair` 类任务（或等价修复任务）。
- 修复后重新执行测试任务并更新报告。
- 若修复引入回归，记录为新缺陷并阻止合并。

### Phase F: 鲁棒性专项

每轮至少覆盖以下异常场景：

1. 任务名非法字符
2. 重复任务名
3. 任务文件缺少 `name`
4. agent 进程异常退出
5. agent 超时
6. 无新 checkpoint 的“伪成功”
7. review run 缺失 report
8. merge 冲突
9. daemon 重启后的状态恢复
10. 项目路径不存在/被删除
11. 脏工作区下的行为
12. 并发任务中一个失败、其余继续运行

每个异常场景必须记录：触发步骤、预期行为、实际行为、结论。

### Phase G: 本轮收敛与回归入口

1. 汇总本轮缺陷（严重级别、复现率、影响范围）。
2. 在 `agvv` 代码仓库修复缺陷。
3. 修复后启动下一轮 `testN+1`，重复 Phase A-F。

## 5. 全栈项目最小验收标准（每轮必须满足）

- 前端 Next.js 可启动并完成至少一条完整用户路径（登录或 CRUD）。
- 后端 FastAPI 可启动并提供健康检查与业务接口。
- PostgreSQL 容器可启动、可连接、可读写。
- 前后端联调至少覆盖 1 条成功路径和 1 条失败路径。
- 相关任务在 `agvv` 中可追踪到状态变化、run 记录、checkpoint/反馈。

## 6. 报告模板

每轮生成：`~/projects/test/testN/reports/round-summary.md`

```markdown
# Test Round N Summary

## Meta
- Date:
- Agent:
- agvv version/commit:
- Test root: ~/projects/test/testN

## Coverage
- Project matrix covered: [ ] new+non-git [ ] new+git [ ] existing+non-git [ ] existing+git
- Parallel features (>=4):
- Fullstack project included: yes/no

## Results
- Total scenarios:
- Passed:
- Failed:
- Blocked:

## Defects
| ID | Severity | Scenario | Repro Steps | Expected | Actual | Status |
|----|----------|----------|-------------|----------|--------|--------|

## Robustness
- Case:
- Outcome:
- Evidence:

## Fixes Applied To agvv
- Commit:
- Change summary:
- Risk:

## Next Round Plan
- testN+1 focus:
- Known risks:
```

## 7. 退出标准（停止循环）

满足全部条件才可停止：

1. 连续 2 轮无 `Critical/High` 缺陷。
2. 当前轮所有必测项通过。
3. 并行 feature（>=4）全部完成 review 与修复闭环。
4. 全栈项目验收标准全部通过。
5. 无未关闭的可复现阻塞问题。

未达成时，必须进入下一轮 `testN+1`。

## 8. 执行纪律

- 不跳过失败用例，失败必须可复现并有证据。
- 不以“单次通过”视为稳定，关键流程至少复验 2 次。
- 不手工修改结果统计，报告由执行事实生成。
- 每轮结束前，确保测试资产完整落盘（任务、日志、报告、修复记录）。

