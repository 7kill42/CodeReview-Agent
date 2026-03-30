# CodeReview-Agent 实现计划

> 本文档供多窗口并行开发使用。每个模块独立成节，包含完整的接口契约、实现细节和验收标准。
> 开始某个模块前，先阅读「依赖关系」一节，确认前置模块已完成。

---

## 代码库当前状态（基线）

```
CodeReview-Agent/
├── agents/
│   ├── base.py              ✅ 完整  Finding / AgentResult / FileDiff / BaseReviewAgent
│   ├── style_agent.py       ✅ 完整  StyleAgent，Claude tool-use，6类检查
│   ├── security_agent.py    ✅ 完整  SecurityAgent，Semgrep + Claude，8类漏洞
│   ├── logic_agent.py       ✅ 完整  LogicAgent，AST预处理 + Claude tool-use，9类检查
│   ├── performance_agent.py ❌ 待实现
│   ├── aggregator.py        ❌ 待实现（核心亮点）
│   └── orchestrator.py      ❌ 待实现
├── tools/
│   ├── github_client.py     ✅ 完整  GitHubClient，get_pr_diff / post_review_comment
│   ├── ast_parser.py        ✅ 完整  ASTParser，parse_python / get_complexity(radon)
│   └── semgrep_runner.py    ✅ 完整  SemgrepRunner，scan(code, lang) → List[SecurityIssue]
├── graph/
│   └── workflow.py          ❌ 待实现（LangGraph 状态机）
├── api/
│   └── main.py              ⚠️  接口骨架完整，POST /review 未接实际执行
├── storage/
│   ├── models.py            ✅ 完整  ReviewTask / ReviewResult / ReviewReport / TaskStatus
│   └── cache.py             ✅ 完整  Redis set/get_task_status / set/get_all_agent_results
├── ui/
│   └── app.py               ❌ 待实现（Streamlit Demo）
├── eval/
│   └── metrics.py           ❌ 待实现
├── config.py                ✅ 完整  Settings(pydantic-settings)，ANTHROPIC_API_KEY 等
├── requirements.txt         ✅ 完整
└── tests/
    ├── test_style_agent.py  ✅ 完整
    └── ...                  ❌ 其余待实现
```

---

## 关键数据结构（所有模块共用）

```python
# agents/base.py —— 必读

class Finding(BaseModel):
    file: str
    line_start: int
    line_end: int
    severity: str        # "CRITICAL" | "HIGH" | "MEDIUM" | "LOW"
    category: str        # 各 Agent 自定义，见各模块说明
    description: str
    suggestion: str
    confidence: float    # 0.0 – 1.0

class AgentResult(BaseModel):
    agent_name: str
    findings: List[Finding]
    summary: str
    execution_time: float   # seconds
    token_used: int

class FileDiff(BaseModel):
    filename: str
    language: str           # "python" | "javascript" | "typescript" | ...
    added_lines: List[tuple[int, str]]   # (line_number, line_text)
    removed_lines: List[tuple[int, str]]
    raw_diff: str

class BaseReviewAgent(ABC):
    @abstractmethod
    async def review(self, file_diff: FileDiff) -> AgentResult: ...
```

---

## 模块 A：`agents/logic_agent.py`

### 依赖
- `agents/base.py` ✅
- `tools/ast_parser.py` ✅（ASTParser，CodeStructure，FunctionInfo）
- `anthropic` SDK
- 不依赖其他待实现模块，**可立即开始**

### 职责
检测逻辑缺陷：空值解引用、边界条件、异常处理缺失/过宽、高复杂度函数、死循环风险、
未使用的返回值、递归无终止条件。

### category 枚举（tool schema 中使用）
```
null_dereference | boundary_condition | bare_except | missing_error_handling
| high_complexity | infinite_loop_risk | unused_return | infinite_recursion | other
```

### 实现步骤

1. **复制 StyleAgent 结构**，将 tool name 改为 `report_logic_findings`，
   category enum 改为上方枚举。

2. **预处理**：在调用 Claude 前，用 `ASTParser` 提取结构化上下文：
   ```python
   from tools.ast_parser import ASTParser
   parser = ASTParser()
   structure = parser.parse_python(code)  # → CodeStructure
   complexity = parser.get_complexity(code, language)
   ```
   将以下信息注入 prompt：
   - 函数列表（名称 + 行号 + 参数数量）
   - `has_error_handling`（bool）
   - 最高 cyclomatic complexity 值

3. **Prompt 核心内容**：
   ```
   You are a senior software engineer reviewing code for logical defects.
   Review the following {language} code diff (added lines only) from `{filename}`.

   Code structure analysis:
   - Functions: {function_list}
   - Has error handling: {has_error_handling}
   - Max cyclomatic complexity: {complexity}

   Focus on:
   - Null/None dereference without guard
   - Off-by-one errors and boundary conditions
   - Bare `except:` or `except Exception: pass` (swallowed errors)
   - Missing error handling on I/O, network, or DB calls
   - Functions with cyclomatic complexity > 10 (already detected: {complexity})
   - Loops that may never terminate
   - Recursive functions without a clear base case
   - Return values of important calls being silently ignored

   Rules:
   - Only report issues in the shown added lines.
   - confidence >= 0.7 for HIGH/CRITICAL.
   - Provide concrete fix suggestions.
   ```

4. **分块**：与 StyleAgent 相同，`MAX_ADDED_LINES_PER_CHUNK = 200`。

5. **`_build_summary`**：`"Logic review found N issue(s) – ..."`

### 接口
```python
class LogicAgent(BaseReviewAgent):
    def __init__(self, api_key: str | None = None) -> None: ...
    async def review(self, file_diff: FileDiff) -> AgentResult: ...
```

### 验收标准
- `pytest tests/test_logic_agent.py` 全部通过
- 针对含 `except: pass` 的代码能检出 `bare_except`
- 针对无 None-guard 的代码能检出 `null_dereference`
- 对于干净代码返回空 findings

---

## 模块 B：`agents/performance_agent.py`

### 依赖
- `agents/base.py` ✅
- `tools/ast_parser.py` ✅
- `anthropic` SDK
- 不依赖其他待实现模块，**可立即开始**

### 职责
检测性能问题：N+1 查询、循环内重复计算、不必要的数据复制、
高复杂度函数、低效数据结构选择、阻塞调用（同步 I/O in async context）。

### category 枚举
```
n_plus_one | loop_invariant | unnecessary_copy | high_complexity
| inefficient_structure | blocking_call | redundant_computation | other
```

### 实现步骤

1. **复制 StyleAgent 结构**，tool name 改为 `report_performance_findings`。

2. **预处理**：
   ```python
   complexity = ASTParser().get_complexity(code, language)
   ```
   complexity > 10 时在 prompt 中明确提示。

3. **Prompt 核心内容**：
   ```
   You are a performance engineer reviewing code for efficiency issues.
   Review the following {language} code diff from `{filename}`.

   Complexity analysis: max cyclomatic complexity = {complexity}

   Focus on:
   - N+1 query patterns: ORM calls or DB queries inside loops
   - Loop-invariant computations that could be hoisted out of the loop
   - Unnecessary list/dict copies (e.g. list(some_list) when not needed)
   - High cyclomatic complexity functions (> 10) that are hard to optimize
   - Inefficient data structures (list for membership test instead of set)
   - Synchronous/blocking I/O calls inside async functions
   - Redundant re-computation of the same value in a loop

   Rules:
   - Only report issues in the shown added lines.
   - Do NOT report style issues; focus purely on performance.
   - confidence >= 0.6 for MEDIUM and above.
   ```

4. **`_build_summary`**：`"Performance review found N issue(s) – ..."`

### 接口
```python
class PerformanceAgent(BaseReviewAgent):
    def __init__(self, api_key: str | None = None) -> None: ...
    async def review(self, file_diff: FileDiff) -> AgentResult: ...
```

### 验收标准
- `pytest tests/test_performance_agent.py` 全部通过
- 含 ORM 调用的循环能检出 `n_plus_one`
- 对干净代码返回空 findings

---

## 模块 C：`agents/aggregator.py`（核心亮点）

### 依赖
- `agents/base.py` ✅（Finding, AgentResult）
- `anthropic` SDK
- **不依赖** orchestrator / workflow，可独立实现和测试

### 职责
接收多个 Agent 的结果，执行：
1. **去重**：合并指向同一位置的相同问题
2. **冲突裁决**：不同 Agent 对同一位置有不同判断时，按权重决策
3. **优先级排序**：输出统一的 severity 分级
4. **报告生成**：Markdown 全文 + JSON 摘要

### 数据模型（定义在 aggregator.py 中）

```python
from pydantic import BaseModel
from typing import List, Dict, Any

class DeduplicatedFinding(BaseModel):
    """A finding after dedup and arbitration."""
    file: str
    line_start: int
    line_end: int
    severity: str                  # final severity after arbitration
    category: str
    description: str
    suggestion: str
    confidence: float              # weighted confidence
    source_agents: List[str]       # which agents contributed

class AggregatedReport(BaseModel):
    task_id: int | None
    pr_url: str
    findings: List[DeduplicatedFinding]
    executive_summary: str         # 3-5 sentence Claude-generated summary
    markdown_report: str           # full Markdown for PR comment
    stats: Dict[str, Any]          # total counts by severity and agent
```

### Agent 权重（常量）
```python
AGENT_WEIGHTS: Dict[str, float] = {
    "SecurityAgent":     1.0,
    "LogicAgent":        0.8,
    "PerformanceAgent":  0.6,
    "StyleAgent":        0.4,
}
```

### 去重算法

```
输入：List[Finding]（来自所有 Agent，已打 agent_name 标记）

步骤：
1. 按 (file, category) 分组
2. 同组内，若两条 finding 满足以下条件，则合并：
   - abs(f1.line_start - f2.line_start) <= 3
   - f1.category == f2.category
3. 合并规则：
   - description: 取较长者
   - suggestion:  取较长者
   - confidence:  加权平均 = sum(w_i * c_i) / sum(w_i)
     其中 w_i = AGENT_WEIGHTS[agent_name]
   - source_agents: 合并所有来源 agent 名称（去重）

步骤：
4. 最终 severity 由加权置信度决定：
   - weighted_confidence >= 0.85 → CRITICAL
   - weighted_confidence >= 0.65 → HIGH
   - weighted_confidence >= 0.40 → MEDIUM
   - 其余                        → LOW
   注意：Security findings 的 severity 不能被其他 Agent 降级
```

### 冲突裁决规则

```
对同一位置（±3行，同 category）的多个 findings：
1. 计算每条 finding 的 weighted_confidence = AGENT_WEIGHTS[agent] * confidence
2. 取 weighted_confidence 最高者作为主 finding
3. 其余 findings 的 description/suggestion 若更详细则补充进来
4. 安全规则：SecurityAgent 的 CRITICAL 不能被任何其他 Agent 降级
```

### 报告 Markdown 格式

```markdown
# Code Review Report

## Executive Summary
{claude 生成的 3-5 句话总结}

## Statistics
| Severity | Count |
|----------|-------|
| CRITICAL | N |
| HIGH     | N |
| MEDIUM   | N |
| LOW      | N |

## Findings

### 🔴 CRITICAL
#### [{category}] `{file}` L{line_start}-{line_end}
**Description:** {description}
**Suggestion:** {suggestion}
**Confidence:** {confidence:.0%} | **Sources:** {source_agents}

### 🟠 HIGH
...

### 🟡 MEDIUM
...

### 🟢 LOW
...
```

### 接口
```python
class Aggregator:
    def __init__(self, api_key: str | None = None) -> None: ...

    def aggregate(
        self,
        agent_results: List[AgentResult],
        pr_url: str = "",
        task_id: int | None = None,
    ) -> AggregatedReport:
        """主入口：去重 + 裁决 + 生成报告。同步方法。"""
        ...

    def _deduplicate(self, findings_with_agent: List[tuple[Finding, str]]) -> List[DeduplicatedFinding]:
        """去重合并逻辑。"""
        ...

    def _generate_executive_summary(self, findings: List[DeduplicatedFinding]) -> str:
        """调用 Claude 生成执行摘要（≤5句话）。"""
        ...

    def _render_markdown(self, report: AggregatedReport) -> str:
        """将 findings 渲染为 Markdown 字符串。"""
        ...
```

### 验收标准
- 两个 Agent 报告同文件同位置同 category → 合并为 1 条
- SecurityAgent CRITICAL 不被 StyleAgent 降级
- 加权置信度计算正确
- 输出 Markdown 包含所有 severity section
- `pytest tests/test_aggregator.py` 全部通过

---

## 模块 D：`agents/orchestrator.py`

### 依赖
- `agents/logic_agent.py` ❌（模块A完成后）
- `agents/performance_agent.py` ❌（模块B完成后）
- `agents/style_agent.py` ✅
- `agents/security_agent.py` ✅
- `agents/aggregator.py` ❌（模块C完成后）
- `tools/github_client.py` ✅
- `storage/models.py` ✅
- `storage/cache.py` ✅
- `config.py` ✅
- **前置条件：A + B + C 全部完成**

### 职责
整个系统的执行引擎：拉取 diff → 并行调度 Agent → 聚合 → 持久化。

### 实现细节

```python
import asyncio
from agents.style_agent import StyleAgent
from agents.security_agent import SecurityAgent
from agents.logic_agent import LogicAgent
from agents.performance_agent import PerformanceAgent
from agents.aggregator import Aggregator
from tools.github_client import GitHubClient
from storage.models import AsyncSessionLocal, ReviewTask, ReviewResult, ReviewReport, TaskStatus
from storage.cache import set_task_status, set_agent_result
from config import settings

class Orchestrator:
    def __init__(self) -> None:
        api_key = settings.ANTHROPIC_API_KEY
        self.agents = [
            StyleAgent(api_key=api_key),
            SecurityAgent(api_key=api_key),
            LogicAgent(api_key=api_key),
            PerformanceAgent(api_key=api_key),
        ]
        self.aggregator = Aggregator(api_key=api_key)
        self.github = GitHubClient()

    async def run(self, task_id: int, pr_url: str) -> None:
        """主执行流程，由 API 层 asyncio.create_task() 启动。"""
        ...
```

### 执行流程（`run` 方法内）

```
1. await set_task_status(task_id, "running")
2. pr_diff = github.get_pr_diff(pr_url)
   - 失败 → set_task_status("failed")，写 error 到 DB，return

3. 过滤文件：只处理 language in {python, javascript, typescript, go, java}
   （可在 config.py 中加 SUPPORTED_LANGUAGES 配置项）

4. 对每个 file_diff，为每个 Agent 创建任务：
   tasks = []
   for agent in self.agents:
       for file_diff in pr_diff.files:
           tasks.append(_run_one_agent(agent, file_diff, task_id))

5. 并行执行，带超时：
   results = await asyncio.gather(*tasks, return_exceptions=True)
   - 超时/异常的任务：记录 warning，返回空 AgentResult（降级策略）

6. 聚合：
   agent_results = [r for r in results if isinstance(r, AgentResult)]
   report = self.aggregator.aggregate(agent_results, pr_url=pr_url, task_id=task_id)

7. 持久化（写 DB）：
   - 为每个 AgentResult 写一条 ReviewResult 记录
   - 写 ReviewReport（final_report=JSON, markdown_report=Markdown）
   - 更新 ReviewTask.status = COMPLETED

8. 更新 Redis：set_task_status(task_id, "completed")

9. 可选：github.post_review_comment(pr_url, report.markdown_report)
```

### `_run_one_agent` 辅助函数

```python
async def _run_one_agent(
    agent: BaseReviewAgent,
    file_diff: FileDiff,
    task_id: int,
    timeout: int = settings.AGENT_TIMEOUT_SECONDS,
) -> AgentResult:
    try:
        result = await asyncio.wait_for(agent.review(file_diff), timeout=timeout)
        # 缓存到 Redis
        await set_agent_result(task_id, result.agent_name, result.model_dump())
        return result
    except asyncio.TimeoutError:
        return AgentResult(
            agent_name=type(agent).__name__,
            findings=[],
            summary=f"Agent timed out after {timeout}s.",
            execution_time=float(timeout),
            token_used=0,
        )
    except Exception as exc:
        return AgentResult(
            agent_name=type(agent).__name__,
            findings=[],
            summary=f"Agent failed: {exc}",
            execution_time=0.0,
            token_used=0,
        )
```

### 接口
```python
class Orchestrator:
    async def run(self, task_id: int, pr_url: str) -> None: ...
```

### 验收标准
- mock 4个 Agent 后，`run()` 能写入 DB 并更新 Redis 状态
- 某个 Agent 超时时，其余 Agent 结果仍被正常处理
- `pytest tests/test_orchestrator.py` 全部通过

---

## 模块 E：`graph/workflow.py`（LangGraph 状态机）

### 依赖
- `agents/orchestrator.py` ❌（模块D完成后）
- `langgraph`（已在 requirements.txt）
- **前置条件：A + B + C + D 全部完成**

### 职责
用 LangGraph 将 Orchestrator 的执行流程显式建模为状态机，
使整个 pipeline 可观测、可断点续跑、可在 LangGraph Studio 可视化。

### State 定义

```python
from typing import TypedDict, List, Dict, Optional
from agents.base import AgentResult, FileDiff
from agents.aggregator import AggregatedReport

class ReviewState(TypedDict):
    task_id: int
    pr_url: str
    # fetch_diff 节点填充
    file_diffs: List[dict]          # FileDiff.model_dump() 列表
    # dispatch 节点填充
    agent_tasks: List[dict]         # {agent: str, file: str} 任务单元
    # 各 Agent 节点填充
    agent_results: Dict[str, List[dict]]   # agent_name → List[AgentResult.model_dump()]
    # aggregate 节点填充
    report: Optional[dict]          # AggregatedReport.model_dump()
    # 错误信息
    error: Optional[str]
```

### 节点定义

```python
# 节点函数签名：(state: ReviewState) -> ReviewState（部分更新）

def fetch_diff(state: ReviewState) -> ReviewState:
    """调用 GitHubClient 获取 PR diff，填充 file_diffs。"""
    ...

def dispatch_agents(state: ReviewState) -> ReviewState:
    """将 file_diffs × agents 展开为 agent_tasks。"""
    ...

# 每个 Agent 对应一个节点（异步）
async def run_style_agent(state: ReviewState) -> ReviewState: ...
async def run_security_agent(state: ReviewState) -> ReviewState: ...
async def run_logic_agent(state: ReviewState) -> ReviewState: ...
async def run_performance_agent(state: ReviewState) -> ReviewState: ...

def aggregate(state: ReviewState) -> ReviewState:
    """调用 Aggregator，填充 report。"""
    ...

def save_results(state: ReviewState) -> ReviewState:
    """将 report 写入 DB，更新 Redis 状态。"""
    ...

def error_handler(state: ReviewState) -> ReviewState:
    """写入错误状态，清理资源。"""
    ...
```

### 图结构

```python
from langgraph.graph import StateGraph, END

def build_workflow() -> StateGraph:
    graph = StateGraph(ReviewState)

    graph.add_node("fetch_diff",          fetch_diff)
    graph.add_node("dispatch_agents",     dispatch_agents)
    graph.add_node("run_style",           run_style_agent)
    graph.add_node("run_security",        run_security_agent)
    graph.add_node("run_logic",           run_logic_agent)
    graph.add_node("run_performance",     run_performance_agent)
    graph.add_node("aggregate",           aggregate)
    graph.add_node("save_results",        save_results)
    graph.add_node("error_handler",       error_handler)

    graph.set_entry_point("fetch_diff")

    # 正常流
    graph.add_edge("fetch_diff",      "dispatch_agents")
    # fan-out
    graph.add_edge("dispatch_agents", "run_style")
    graph.add_edge("dispatch_agents", "run_security")
    graph.add_edge("dispatch_agents", "run_logic")
    graph.add_edge("dispatch_agents", "run_performance")
    # fan-in
    graph.add_edge("run_style",       "aggregate")
    graph.add_edge("run_security",    "aggregate")
    graph.add_edge("run_logic",       "aggregate")
    graph.add_edge("run_performance", "aggregate")
    graph.add_edge("aggregate",       "save_results")
    graph.add_edge("save_results",    END)

    # 条件边：任意节点 error 字段非空 → error_handler
    for node in ["fetch_diff", "dispatch_agents", "aggregate", "save_results"]:
        graph.add_conditional_edges(
            node,
            lambda s: "error_handler" if s.get("error") else node + "__next__",
        )
    graph.add_edge("error_handler", END)

    return graph.compile()

workflow = build_workflow()
```

### 验收标准
- `workflow.invoke({"task_id": 1, "pr_url": "...", ...})` 能完整跑通
- fetch_diff 失败时进入 error_handler 而非抛异常
- 图结构可通过 `workflow.get_graph().draw_mermaid()` 导出 Mermaid 图

---

## 模块 F：接通 `api/main.py`

### 依赖
- `agents/orchestrator.py` ❌（模块D完成后）
- `api/main.py` ⚠️（现有骨架）
- **前置条件：D完成**

### 需要修改的部分

当前 `POST /review` 只创建 DB 记录并返回，未启动任何 Agent。

### 修改内容（仅改动约 10 行）

```python
# api/main.py  POST /review  handler 末尾，替换 return 前的部分

from agents.orchestrator import Orchestrator

@app.post("/review", ...)
async def create_review(request: ReviewRequest, db: AsyncSession = Depends(get_db)):
    # 1. 创建 DB 记录（现有代码保留）
    task = ReviewTask(pr_url=str(request.pr_url), status=TaskStatus.PENDING)
    db.add(task)
    await db.flush()          # 获取 task.id
    await set_task_status(task.id, "pending")
    await db.commit()

    # 2. 后台异步启动 Orchestrator（新增）
    orchestrator = Orchestrator()
    asyncio.create_task(orchestrator.run(task.id, str(request.pr_url)))

    return ReviewCreateResponse(
        task_id=task.id,
        status="pending",
        message="Review task created. Poll GET /review/{task_id}/status for results.",
    )
```

### 注意事项
- `asyncio.create_task()` 要求调用方在 async 上下文中，FastAPI handler 天然满足
- Orchestrator 内部捕获所有异常并写入 DB，不会导致未处理的 Task 异常
- 无需引入 Celery/Redis Queue，asyncio 即可满足演示需求

### 验收标准
- `POST /review` 返回 `task_id` 后，后台任务开始执行
- `GET /review/{task_id}/status` 轮询能看到 pending→running→completed 变化
- `pytest tests/test_api.py` 全部通过

---

## 模块 G：`ui/app.py`（Streamlit Demo）

### 依赖
- `api/main.py` 已接通（模块F完成后）
- `streamlit`（已在 requirements.txt）
- **前置条件：F完成；也可 mock API 独立开发**

### 页面结构

```
┌─────────────────────────────────────────┐
│  CodeReview-Agent  🔍                   │
├─────────────────────────────────────────┤
│  GitHub PR URL: [________________] [Go] │
├─────────────────────────────────────────┤
│  Status: ⏳ Running...  [████░░░░] 60%  │
├─────────────────────────────────────────┤
│  Tabs: [Summary] [Security] [Logic]     │
│        [Performance] [Style]            │
├─────────────────────────────────────────┤
│  Summary tab:                           │
│    Executive Summary 文字               │
│    Statistics 表格（severity × count）  │
├─────────────────────────────────────────┤
│  每个 Agent tab:                        │
│    按 severity 分组的 findings 卡片     │
│    CRITICAL=红色, HIGH=橙色, ...        │
├─────────────────────────────────────────┤
│  [下载 Markdown 报告]                   │
└─────────────────────────────────────────┘
```

### 实现步骤

```python
import streamlit as st
import httpx
import time

API_BASE = "http://localhost:8000"

st.title("CodeReview-Agent")
st.caption("Multi-agent AI code review powered by Claude")

pr_url = st.text_input("GitHub PR URL")
if st.button("Start Review") and pr_url:
    # 1. 提交任务
    resp = httpx.post(f"{API_BASE}/review", json={"pr_url": pr_url})
    task_id = resp.json()["task_id"]
    st.session_state["task_id"] = task_id

# 2. 轮询状态
if "task_id" in st.session_state:
    task_id = st.session_state["task_id"]
    with st.spinner("Reviewing..."):
        while True:
            status_resp = httpx.get(f"{API_BASE}/review/{task_id}/status")
            data = status_resp.json()
            if data["status"] in ("completed", "failed"):
                break
            time.sleep(2)
            st.rerun()

    # 3. 展示结果
    if data["status"] == "completed" and data["report"]:
        report = data["report"]
        # Summary tab, Agent tabs, 下载按钮...
```

### Severity 颜色映射
```python
SEVERITY_COLOR = {
    "CRITICAL": "🔴",
    "HIGH":     "🟠",
    "MEDIUM":   "🟡",
    "LOW":      "🟢",
}
```

### 验收标准
- `streamlit run ui/app.py` 能正常启动
- 输入 PR URL 后能看到轮询进度
- 结果按 Agent 分 Tab 展示，severity 有颜色标注
- 下载按钮能下载 Markdown 报告

---

## 模块 H：`eval/metrics.py`

### 依赖
- `agents/base.py` ✅
- 不依赖其他待实现模块，**可立即开始**

### 数据集格式（`eval/dataset/` 下的 JSON 文件）

```json
[
  {
    "pr_url": "https://github.com/owner/repo/pull/123",
    "human_findings": [
      {
        "file": "src/auth.py",
        "line_start": 42,
        "line_end": 42,
        "severity": "CRITICAL",
        "category": "sql_injection",
        "description": "SQL injection via string format"
      }
    ]
  }
]
```

### 匹配规则（TP 判定）

```
 predicted finding p 与 ground-truth finding g 匹配，当且仅当：
 - p.file == g.file
 - abs(p.line_start - g.line_start) <= 5
 - p.category == g.category
```

### 实现接口

```python
from dataclasses import dataclass
from typing import List
from agents.base import Finding

@dataclass
class EvalResult:
    tp: int
    fp: int
    fn: int
    precision: float
    recall: float
    f1: float

def match_findings(
    predicted: List[Finding],
    ground_truth: List[dict],
    line_tolerance: int = 5,
) -> tuple[int, int, int]:  # (tp, fp, fn)
    """匹配预测与真实 findings，返回 TP/FP/FN 计数。"""
    ...

def compute_metrics(
    predicted: List[Finding],
    ground_truth: List[dict],
) -> EvalResult:
    """计算 Precision / Recall / F1。"""
    tp, fp, fn = match_findings(predicted, ground_truth)
    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall    = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1        = (2 * precision * recall / (precision + recall)
                 if (precision + recall) > 0 else 0.0)
    return EvalResult(tp=tp, fp=fp, fn=fn,
                      precision=precision, recall=recall, f1=f1)

def evaluate_dataset(dataset_path: str, agent_results: List[dict]) -> dict:
    """对整个数据集批量评估，返回汇总指标。"""
    ...
```

### 验收标准
- 完美预测（全匹配）时 precision=recall=f1=1.0
- 空预测时 precision=1.0（无 FP），recall=0.0
- `pytest tests/test_metrics.py` 全部通过

---

## 模块 I：测试补全

### 依赖：对应模块完成后编写

### `tests/test_logic_agent.py`

```python
# 测试场景：
# 1. 含 except: pass 的代码 → 检出 bare_except
# 2. 含 None 解引用的代码  → 检出 null_dereference
# 3. 干净代码              → 空 findings
# mock 方式与 test_style_agent.py 完全相同：
#   patch agent._client.messages.create, return_value = _make_response([...])
```

### `tests/test_performance_agent.py`

```python
# 测试场景：
# 1. 循环内 ORM 调用    → 检出 n_plus_one
# 2. 循环内常量计算      → 检出 loop_invariant
# 3. 干净代码            → 空 findings
```

### `tests/test_aggregator.py`

```python
# 测试场景：
# 1. 两个 Agent 报告同位置同 category → 合并为 1 条
# 2. SecurityAgent CRITICAL + StyleAgent LOW 同位置 → 保持 CRITICAL
# 3. 加权置信度计算验证
# 4. Markdown 输出包含所有 severity 标题
# 注意：mock Claude client 避免真实 API 调用
```

### `tests/test_orchestrator.py`

```python
# 测试场景：
# 1. 正常流：mock 4个 Agent + GitHubClient，run() 写入 DB
# 2. 某 Agent 超时：其余结果仍被处理，task 状态为 completed
# 3. GitHubClient 抛异常：task 状态写为 failed
# 使用 pytest-asyncio，mock DB session
```

### `tests/test_api.py`

```python
# 使用 FastAPI TestClient（httpx）
# 测试场景：
# 1. POST /review 返回 202 + task_id
# 2. GET /review/{task_id}/status 返回正确结构
# 3. GET /review/9999/status 返回 404
# 4. GET /health 返回 {status: ok}
# mock Orchestrator.run 避免真实执行
```

### `tests/test_metrics.py`

```python
# 1. 完美匹配 → f1=1.0
# 2. 无预测   → recall=0.0, precision=1.0
# 3. 全误报   → precision=0.0, recall=0.0
# 4. 行号容差：±5行内算匹配
```

---

## 并行开发指南

### 依赖图

```
模块A (logic_agent)      ┐
模块B (performance_agent)┤→ 模块D (orchestrator) → 模块E (workflow)
模块C (aggregator)       ┘         ↓
                               模块F (api) → 模块G (ui)

模块H (eval/metrics)  — 无依赖，可任意时间开始
模块I (tests)         — 各模块完成后立即编写
```

### 可并行的窗口分配

| 窗口 | 负责模块 | 可立即开始 |
|------|---------|----------|
| 窗口 1 | 模块A：`logic_agent.py` + `tests/test_logic_agent.py` | ✅ 是 |
| 窗口 2 | 模块B：`performance_agent.py` + `tests/test_performance_agent.py` | ✅ 是 |
| 窗口 3 | 模块C：`aggregator.py` + `tests/test_aggregator.py` | ✅ 是 |
| 窗口 4 | 模块H：`eval/metrics.py` + `tests/test_metrics.py` | ✅ 是 |
| 窗口 5 | 模块D：`orchestrator.py`（等 A+B+C 完成）+ `tests/test_orchestrator.py` | ⏳ 等待 |
| 窗口 6 | 模块E：`graph/workflow.py`（等 D 完成）| ⏳ 等待 |
| 窗口 7 | 模块F+G：接通 API + `ui/app.py`（等 D 完成）| ⏳ 等待 |

### 开发时序（建议）

```
Day 1-2  [窗口1+2+3+4 并行]
  窗口1: logic_agent.py + test_logic_agent.py
  窗口2: performance_agent.py + test_performance_agent.py
  窗口3: aggregator.py + test_aggregator.py
  窗口4: eval/metrics.py + test_metrics.py

Day 3-4  [A+B+C 完成后]
  窗口5: orchestrator.py + test_orchestrator.py

Day 5    [D 完成后，窗口6+7 并行]
  窗口6: graph/workflow.py
  窗口7: 接通 api/main.py + ui/app.py

Day 6    [全部完成后]
  联调测试：pytest tests/ -v
  README 补全
  .env.example 检查
```

---

## 开发规范

### 统一约定

1. **模型常量**：每个 Agent 文件顶部 `MODEL = "claude-opus-4-6"`
2. **分块大小**：`MAX_ADDED_LINES_PER_CHUNK = 200`
3. **tool name 命名**：`report_{agent_type}_findings`
4. **`_build_summary` 格式**：`"{AgentName} review found N issue(s) – CRITICAL: x, HIGH: y, ..."`
5. **`agent_name` 字符串**：与类名完全一致，如 `"LogicAgent"`、`"PerformanceAgent"`

### mock 测试模板（所有 Agent 测试通用）

```python
from unittest.mock import MagicMock, patch
import pytest
from agents.base import FileDiff
from agents.logic_agent import LogicAgent  # 替换为对应 Agent

def _make_response(findings: list) -> MagicMock:
    block = MagicMock()
    block.type = "tool_use"
    block.name = "report_logic_findings"  # 替换为对应 tool name
    block.input = {"findings": findings}
    resp = MagicMock()
    resp.content = [block]
    resp.usage = MagicMock(input_tokens=100, output_tokens=50)
    return resp

def _diff(added_lines, filename="example.py"):
    return FileDiff(filename=filename, language="python", added_lines=added_lines)

@pytest.mark.asyncio
async def test_xxx():
    agent = LogicAgent(api_key="test-key")
    mock_resp = _make_response([...])  # 填入期望的 findings
    with patch.object(agent._client.messages, "create", return_value=mock_resp):
        result = await agent.review(_diff([...]))
    assert ...
```

### imports 约定

```python
# 每个新 Agent 文件的标准 import 头
from __future__ import annotations

import os
import textwrap
import time
from typing import Any, Dict, List

import anthropic

from agents.base import AgentResult, BaseReviewAgent, FileDiff, Finding
```

---

## FAQ

**Q: `FileDiff.language` 的取值范围是什么？**

A: 见 `tools/github_client.py` 的 `_EXT_TO_LANG` 字典：`python, javascript, typescript, java, go, ruby, rust, cpp, c, csharp, php, swift, kotlin, scala, bash, sql, html, css, json, yaml, toml, markdown, unknown`

**Q: Agent 中如何获取 ANTHROPIC_API_KEY？**

A: `__init__` 接收可选的 `api_key` 参数，fallback 到环境变量：
```python
self._client = anthropic.Anthropic(
    api_key=api_key or os.environ.get("ANTHROPIC_API_KEY", "")
)
```

**Q: `FileDiff` 里 `added_lines` 的行号是 PR diff 中的实际行号吗？**

A: 是的，`github_client.py` 的 `_parse_patch` 函数已将 unified diff 解析为带真实行号的 `(line_number, line_text)` 元组列表。

**Q: Aggregator 需要调用 Claude 吗？**

A: 仅 `_generate_executive_summary` 需要，其余去重/裁决/排序逻辑是纯 Python。可以在 Claude 调用失败时 fallback 到一段固定模板摘要。

**Q: LangGraph 版本兼容性？**

A: `requirements.txt` 中是 `langgraph==0.0.55`，API 与新版本有差异。`StateGraph` 的 fan-out 在此版本中用多个 `add_edge` 实现，不用 `Send` API。