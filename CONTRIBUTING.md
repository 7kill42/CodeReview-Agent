# 开发者贡献指南 (CONTRIBUTING)

> 本文档面向所有参与 CodeReview-Agent 开发的工程师。
> 每次新增或修改模块前，请先通读对应章节，确保风格和接口一致。

---

## 目录

1. [项目架构速览](#1-项目架构速览)
2. [目录与模块职责](#2-目录与模块职责)
3. [核心数据模型](#3-核心数据模型)
4. [如何新增一个 Agent](#4-如何新增一个-agent)
5. [如何新增一个 Tool](#5-如何新增一个-tool)
6. [API 路由规范](#6-api-路由规范)
7. [配置项规范](#7-配置项规范)
8. [编码规范](#8-编码规范)
9. [测试规范](#9-测试规范)
10. [提交与 PR 规范](#10-提交与-pr-规范)

---

## 1. 项目架构速览

```
接入层 (FastAPI / Streamlit / GitHub Webhook)
        │
   Orchestrator          ← asyncio 并行调度，去重缓存检查
        │
  ┌─────┴──────────────────────────────┐
StyleAgent  SecurityAgent  LogicAgent  PerformanceAgent
  └─────┬──────────────────────────────┘
        │
    Aggregator            ← 去重 → 严重级别仲裁 → Executive Summary
        │
  ┌─────┼─────────────┐
PostgreSQL  Redis    GitHub PR Comment
```

**数据流**：PR URL → GitHub diff → `FileDiff` 列表 → 各 Agent 并行 review → `AgentResult` 列表 → Aggregator → 结构化报告 → 持久化 / 回写 / 通知

---

## 2. 目录与模块职责

| 路径 | 职责 | 关键类 / 函数 |
|------|------|--------------|
| `agents/base.py` | 共享数据模型 + 抽象基类 | `Finding`, `AgentResult`, `FileDiff`, `BaseReviewAgent` |
| `agents/style_agent.py` | 代码风格检查（6 类） | `StyleAgent` |
| `agents/security_agent.py` | 安全漏洞检测（Semgrep + Claude，8 类） | `SecurityAgent` |
| `agents/logic_agent.py` | 逻辑缺陷检测（AST + Claude，9 类） | `LogicAgent` |
| `agents/performance_agent.py` | 性能问题检测（7 类） | `PerformanceAgent` |
| `agents/aggregator.py` | 跨 Agent 去重、仲裁、生成摘要 | `Aggregator` |
| `agents/orchestrator.py` | 任务调度、扩展功能集成 | `Orchestrator` |
| `tools/github_client.py` | GitHub API 封装 | `GitHubClient` |
| `tools/ast_parser.py` | Python AST 解析 + radon 圈复杂度 | `ASTParser` |
| `tools/semgrep_runner.py` | Semgrep 静态分析封装 | `SemgrepRunner` |
| `api/main.py` | FastAPI 路由层 | `/review`, `/webhook/github`, `/stats/*` |
| `storage/models.py` | SQLAlchemy ORM | `ReviewTask`, `ReviewResult`, `ReviewReport` |
| `storage/cache.py` | Redis 状态缓存 + 去重缓存 | `CacheClient` |
| `notifications/webhook.py` | Slack / 企业微信通知 | `NotificationClient` |
| `ui/app.py` | Streamlit 可视化界面 | — |
| `config.py` | 全局配置（pydantic-settings） | `Settings`, `get_settings()` |
| `graph/workflow.py` | LangGraph 备用编排（非主路径） | — |


---

## 3. 核心数据模型

所有 Agent 共享 `agents/base.py` 中的三个模型，**禁止在各 Agent 内自定义等价结构**。

### `Finding` — 单条问题

```python
class Finding(BaseModel):
    file: str           # 文件路径（相对于仓库根）
    line_start: int     # 问题起始行（diff 中的行号）
    line_end: int       # 问题结束行
    severity: str       # CRITICAL | HIGH | MEDIUM | LOW
    category: str       # Agent 自定义分类，见下表
    description: str    # 人可读的问题描述
    suggestion: str     # 具体修复建议
    confidence: float   # 0.0 ~ 1.0，模型置信度
```

### `AgentResult` — 单个 Agent 的汇总输出

```python
class AgentResult(BaseModel):
    agent_name: str          # 固定字符串，如 "StyleAgent"
    findings: List[Finding]
    summary: str             # 一句话摘要，由 Agent 内部生成
    execution_time: float    # 秒
    token_used: int          # 本次调用消耗的 token 总量
```

### `FileDiff` — 单文件 diff

```python
class FileDiff(BaseModel):
    filename: str
    language: str                          # 默认 "python"
    added_lines: List[tuple[int, str]]     # (行号, 行内容)
    removed_lines: List[tuple[int, str]]
    raw_diff: str                          # 原始 unified diff 字符串
```

> **注意**：Agent 只审查 `added_lines`；`removed_lines` 和 `raw_diff` 提供上下文。

---

## 4. 如何新增一个 Agent

以下是完整步骤，以新增 `DependencyAgent`（检查依赖安全）为例。

### 4.1 新建文件 `agents/dependency_agent.py`

文件顶部必须有模块说明 docstring，列出该 Agent 检查的类别：

```python
"""Dependency Agent – checks third-party dependency risks.

Checks performed on added dependency declarations only:
  1. Known CVE packages
  2. Unpinned version specifiers
  3. Deprecated packages
"""
```

### 4.2 定义 Claude Tool Schema

每个 Agent 使用独立的 tool schema，命名规则：`report_<agent_short_name>_findings`。

```python
REPORT_FINDINGS_TOOL: Dict[str, Any] = {
    "name": "report_dependency_findings",
    "description": "...",
    "input_schema": {
        "type": "object",
        "required": ["findings"],
        "properties": {
            "findings": {
                "type": "array",
                "items": {
                    # 必须包含与 Finding 模型完全对应的字段
                    "required": ["line_start","line_end","severity",
                                 "category","description","suggestion","confidence"],
                    ...
                }
            }
        }
    }
}
```

### 4.3 继承 `BaseReviewAgent`

```python
from agents.base import AgentResult, BaseReviewAgent, FileDiff, Finding

class DependencyAgent(BaseReviewAgent):
    async def review(self, file_diff: FileDiff) -> AgentResult:
        # 1. 过滤出关心的文件（如 requirements.txt / pyproject.toml）
        # 2. 调用 Claude tool-use，传入 REPORT_FINDINGS_TOOL
        # 3. 解析响应，构造 List[Finding]
        # 4. 返回 AgentResult
        ...
```

### 4.4 注册到 Orchestrator

在 `agents/orchestrator.py` 的并行任务列表中加入新 Agent：

```python
from agents.dependency_agent import DependencyAgent

# 在 _run_agents() 内的 agents 列表追加：
agents = [
    StyleAgent(),
    SecurityAgent(),
    LogicAgent(),
    PerformanceAgent(),
    DependencyAgent(),   # ← 新增
]
```

### 4.5 编写测试

在 `tests/test_dependency_agent.py` 中参考 `test_style_agent.py`，mock `anthropic.Anthropic` 客户端，覆盖：
- 正常发现问题的路径
- 无问题（空 findings）的路径
- Claude 返回非 tool_use 内容的容错路径


---

## 5. 如何新增一个 Tool

`tools/` 目录存放与 LLM 无关的基础工具（API 封装、静态分析、解析器）。

规则：
- 每个 tool 文件只做一件事，类名与文件名对应（`ast_parser.py` → `ASTParser`）
- 对外暴露的方法必须是 `async` 或明确标注为同步阻塞（并在调用方用 `asyncio.to_thread` 包裹）
- 不得在 tool 内部直接读取 `settings`，所有配置通过构造函数参数注入
- 新 tool 需在本节补充一行说明（路径、职责、关键方法）

---

## 6. API 路由规范

所有路由定义在 `api/main.py`。

| 规则 | 说明 |
|------|------|
| 路径命名 | 全小写 + 连字符，如 `/stats/top-categories` |
| 请求体 | 使用 Pydantic `BaseModel`，禁止裸 `dict` |
| 响应体 | 统一返回 `{"status": "ok", "data": ...}` 或 `{"status": "error", "message": ...}` |
| 异步 | 所有路由函数必须为 `async def` |
| 错误码 | 4xx 用于客户端错误，5xx 用于服务端错误，不要用 200 包裹错误 |

---

## 7. 配置项规范

所有配置集中在 `config.py` 的 `Settings` 类，通过 `get_settings()` 获取单例。

**新增配置项步骤**：

1. 在 `Settings` 中添加字段，提供合理默认值：
   ```python
   MY_NEW_FEATURE_ENABLED: bool = False
   MY_NEW_FEATURE_TIMEOUT: int = 60
   ```
2. 在 `.env.example` 中同步添加注释说明：
   ```
   # 是否启用新功能
   MY_NEW_FEATURE_ENABLED=false
   MY_NEW_FEATURE_TIMEOUT=60
   ```
3. 禁止在业务代码中直接读取 `os.environ`，统一使用 `settings.MY_NEW_FEATURE_ENABLED`

---

## 8. 编码规范

### 通用
- Python 3.10+，使用 `from __future__ import annotations`
- 类型注解覆盖所有公共函数的参数和返回值
- 每个模块顶部必须有 docstring，说明该模块的职责和检查类别（参考 `style_agent.py`）
- 每个公共类和方法必须有 docstring

### 常量
- 模块级常量全大写，放在 import 区块之后、类定义之前
- Claude model 名统一使用 `config.py` 中的 `settings.LLM_MODEL`，**不要**在各 Agent 内硬编码

### 异步
- 所有 Agent 的 `review()` 方法必须是 `async def`
- 使用 `asyncio.gather()` 做并行，不要使用 `threading`

### 错误处理
- Agent 内部捕获 `anthropic.APIError`，降级返回空 `AgentResult`，不向上抛出
- Tool 层捕获网络/解析异常，记录日志后重新抛出，让调用方决策

---

## 9. 测试规范

```
tests/
├── test_<module_name>.py   # 与被测模块一一对应
```

- 所有测试使用 `pytest` + `pytest-asyncio`
- **外部依赖全部 mock**：`anthropic.Anthropic`、`AsyncSession`、`Redis`、`GitHub`
- 每个 Agent 测试文件至少覆盖以下三个场景：

  | 场景 | 说明 |
  |------|------|
  | 正常路径 | Claude 返回 tool_use，findings 不为空 |
  | 空结果 | Claude 返回 tool_use，findings 为空列表 |
  | 容错路径 | Claude 返回非 tool_use 内容，Agent 不崩溃 |

- 运行全部测试：
  ```bash
  pytest tests/ -v
  ```

---

## 10. 提交与 PR 规范

### Commit Message 格式

```
<type>(<scope>): <简短描述>

[可选正文：说明 why，而非 what]
```

| type | 含义 |
|------|------|
| `feat` | 新功能 |
| `fix` | Bug 修复 |
| `refactor` | 重构（不改变行为） |
| `test` | 测试相关 |
| `docs` | 文档更新 |
| `chore` | 构建/配置/依赖 |

示例：
```
feat(agents): add DependencyAgent for CVE detection
fix(aggregator): deduplicate findings across agents by (file, line, category)
docs: update CONTRIBUTING with Tool addition guide
```

### PR Checklist

提交 PR 前确认以下事项：

- [ ] 新模块顶部有完整 docstring（职责 + 检查类别）
- [ ] `CONTRIBUTING.md` 的目录表已更新（如新增了模块）
- [ ] `.env.example` 同步了新增配置项
- [ ] 新 Agent 已注册到 `orchestrator.py`
- [ ] 测试覆盖三个基本场景，`pytest tests/ -v` 全部通过
- [ ] 无硬编码的 API Key、Token 或 model 名字符串


