# CI/CD 流程说明

## 概览

本项目使用 GitHub Actions 实现自动化 CI/CD，包含两条独立的流水线：

| 流水线 | 文件 | 触发条件 | 用途 |
|--------|------|----------|------|
| CI | `.github/workflows/ci.yml` | push / PR | 质量门禁：lint、格式、文档、测试、构建 |
| Publish | `.github/workflows/publish.yml` | git tag `v*` | 发布包到 PyPI |

---

## CI 流水线

### 触发条件

```
push 到以下分支：main、feat-*、fix-*、refactor-*、codex/*
任意 Pull Request
手动触发（workflow_dispatch）
```

### 执行步骤

```
┌─────────────────────────────────────────────────────────┐
│  lint job                    test job (matrix)          │
│  ─────────────────           ──────────────────────     │
│  ruff check .                Python 3.10                │
│  ruff format --check .       Python 3.12                │
│  interrogate --fail-under=100│  pytest --cov=agvv       │
└──────────────┬───────────────┴──────────────┬──────────┘
               │         都通过               │
               └──────────────┬───────────────┘
                              ▼
                        build job
                        ─────────
                        uv build
                        上传 dist/ artifact
```

### Job 说明

#### `lint` — 代码质量检查

在 Python 3.12 上运行以下三项检查，任意一项失败则整个 CI 失败：

| 命令 | 检查内容 |
|------|----------|
| `uv run ruff check .` | 代码风格和错误（linting） |
| `uv run ruff format --check .` | 代码格式（不自动修复，只检查） |
| `uv run interrogate agvv --fail-under=100 --quiet` | docstring 覆盖率必须达到 100% |

> **为什么 docstring 在 CI 中检查？**
> 项目通过 `.githooks/pre-commit` 在本地也有此检查，但 git hooks 是可选安装的。在 CI 中强制执行可确保所有合并到 main 的代码都满足要求。

#### `test` — 多版本矩阵测试

在 **Python 3.10 和 3.12** 两个版本上分别运行完整测试套件：

```
uv run pytest --cov=agvv --cov-branch --cov-report=term-missing --cov-report=xml
```

- 覆盖率报告（`coverage.xml`）仅在 Python 3.12 环境上传为 artifact
- 项目声明 `requires-python = ">=3.10"`，矩阵测试确保最低支持版本可用

#### `build` — 构建验证

仅在 `lint` 和 `test` 全部通过后执行：

```
uv build
```

产物（wheel + sdist）上传为 `dist` artifact，供后续调试或手动下载。

### 并发控制

同一分支/PR 的新 push 会自动取消正在运行的旧 CI，避免资源浪费：

```yaml
concurrency:
  group: ${{ github.workflow }}-${{ github.ref }}
  cancel-in-progress: true
```

---

## Publish 流水线

### 触发条件

```
push git tag，格式为 v*（例如：v0.1.2、v1.0.0）
手动触发（workflow_dispatch）— 仅运行 verify job，不发布
```

### 执行步骤

```
verify job
─────────────────────────────────
ruff check .
ruff format --check .
interrogate --fail-under=100 --quiet
pytest
         │
         │ 通过
         ▼
publish job（仅 tag 触发时执行）
─────────────────────────────────
验证 pyproject.toml version == git tag version
uv build
pypa/gh-action-pypi-publish（OIDC）
         │
         ▼
PyPI: agent-wave==x.y.z
```

### Job 说明

#### `verify` — 发布前质量验证

与 CI 的 lint + test 相同的检查，确保被发布的代码是干净的。即使 CI 已经在该 commit 上通过，发布前也会重新验证。

#### `publish` — 发布到 PyPI

**触发条件**：`if: startsWith(github.ref, 'refs/tags/')`，只有 tag push 才执行，手动触发不会发布。

**版本一致性校验**：

发布前自动验证 `pyproject.toml` 中的 `version` 字段与 git tag 是否一致：

```bash
TAG="${GITHUB_REF#refs/tags/v}"          # 从 tag 提取版本号，如 0.1.2
PKG_VER=$(grep '^version = ' pyproject.toml | ...)
[ "$TAG" != "$PKG_VER" ] && exit 1       # 不一致则中止发布
```

**PyPI 认证**：使用 [OIDC Trusted Publishing](https://docs.pypi.org/trusted-publishers/)，无需存储 PyPI token，通过 GitHub 环境 `pypi` 进行授权。

**权限最小化**：`id-token: write` 权限仅在 `publish` job 级别声明，`verify` job 只有只读权限。

---

## 发版 SOP（标准操作流程）

以下是将新功能发布到 PyPI 的完整步骤：

### 第一步：确认 main 分支状态

```bash
# 确认本地与远端同步
git checkout main
git pull origin main

# 确认 CI 在 main 上是绿色的（在 GitHub Actions 页面确认）
```

### 第二步：修改版本号

编辑 `pyproject.toml`，将 `version` 字段改为新版本号：

```toml
[project]
version = "0.1.2"   # 从 0.1.1 改为 0.1.2
```

遵循[语义化版本规范（SemVer）](https://semver.org/lang/zh-CN/)：

| 版本类型 | 格式 | 适用场景 |
|----------|------|----------|
| Patch | `0.1.1 → 0.1.2` | bug 修复、文档更新 |
| Minor | `0.1.1 → 0.2.0` | 新增向后兼容的功能 |
| Major | `0.1.1 → 1.0.0` | 不兼容的 API 变更 |

### 第三步：提交版本变更

```bash
git add pyproject.toml
git commit -m "chore: bump version to 0.1.2"
git push origin main
```

### 第四步：打 tag 并推送

```bash
git tag v0.1.2
git push origin v0.1.2
```

tag 推送后，GitHub Actions 会自动触发 `publish.yml`。

### 第五步：确认发布结果

在 GitHub Actions 页面确认 `Publish to PyPI` workflow 运行成功，然后验证 PyPI 上的新版本：

```
https://pypi.org/project/agent-wave/
```

---

## Action 版本固定策略

### 为什么固定 SHA 而不是使用标签？

使用浮动标签（如 `@v4`）存在供应链攻击风险：action 维护者或攻击者可以将标签指向恶意 commit，导致 CI 执行任意代码。

本项目所有 action 均固定到 commit SHA：

```yaml
# 不安全（浮动标签）
uses: actions/checkout@v4

# 安全（固定 SHA）
uses: actions/checkout@34e114876b0b11c390a56381ad16ebd13914f8d5  # v4
```

### 当前使用的 action 版本

| Action | 固定 SHA | 对应版本 |
|--------|----------|----------|
| `actions/checkout` | `34e114876b0b11c390a56381ad16ebd13914f8d5` | v4 |
| `astral-sh/setup-uv` | `e58605a9b6da7c637471fab8847a5e5a6b8df081` | v5 |
| `actions/setup-python` | `a26af69be951a213d495a4c3e4e4022e16d87065` | v5 |
| `pypa/gh-action-pypi-publish` | `ed0c53931b1dc9bd32cbe73a98c7f6766f8a527e` | — |

### 如何升级 action 版本？

1. 在 action 仓库的 Releases 页面找到新版本的 commit SHA
2. 更新 `.github/workflows/ci.yml` 和 `.github/workflows/publish.yml` 中对应的 SHA
3. 提 PR 验证后合并

---

## 常见问题

### CI 报 `ruff format` 失败怎么办？

本地执行自动格式化，然后提交：

```bash
uv run ruff format .
git add -u && git commit -m "style: apply ruff format"
```

### CI 报 docstring 覆盖率不足怎么办？

查看缺失 docstring 的函数：

```bash
uv run interrogate agvv --fail-under=100
```

为所有缺失的函数/类/模块补充 docstring。

### publish 失败，报版本号不匹配怎么办？

确认 `pyproject.toml` 中的 `version` 与打的 tag 一致：

```bash
grep '^version' pyproject.toml
```

如果 tag 打错了，删除并重新打：

```bash
git tag -d v0.1.2
git push origin :refs/tags/v0.1.2
# 修正 pyproject.toml 后重新提交、打 tag
```

### 如何在本地运行与 CI 相同的检查？

```bash
uv run ruff check .
uv run ruff format --check .
uv run interrogate agvv --fail-under=100 --quiet
uv run pytest --cov=agvv --cov-branch --cov-report=term-missing
```

安装 git pre-commit hook（项目已内置）：

```bash
git config core.hooksPath .githooks
```
