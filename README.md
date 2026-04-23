# CodeReview-Agent

An interview-ready AI engineering project that automates GitHub pull request review with specialized agents, async orchestration, severity arbitration, and structured report generation.

This repository is positioned as an **agent framework first** and a **demo application second**. It focuses on how a multi-agent review pipeline is designed, coordinated, and exposed as a usable product.

`PR diff -> Orchestrator -> Specialized Agents -> Aggregator -> Structured report`

## Recruiter Snapshot

- **What it does:** reviews GitHub pull requests with multiple AI agents instead of a single generic reviewer
- **Why it matters:** demonstrates practical LLM application design, async orchestration, modular architecture, and productization
- **Tech highlights:** FastAPI, Streamlit, Pydantic, GitHub integration, provider abstraction, structured evaluation-friendly outputs

## Why This Project Exists

Most AI code review demos stop at a single generic reviewer. This project explores a different design:

- **Specialized agents** focus on one review dimension at a time.
- **The orchestrator** runs agents in parallel over a normalized diff representation.
- **The aggregator** deduplicates overlapping findings and arbitrates severity.
- **Adapters** keep SCM access, static analysis, and LLM providers replaceable.

That makes the project useful for interviews as a compact example of agent decomposition, async orchestration, and framework-oriented design.

## Framework Overview

### Core pipeline

1. Fetch and normalize a GitHub pull request diff into `FileDiff`.
2. Dispatch the diff to multiple review agents.
3. Collect `AgentResult` payloads in parallel.
4. Merge and arbitrate findings into an `AggregatedReport`.
5. Return a structured report through a small API and demo UI.

### Core modules

- `agents/`: specialized review agents, aggregation, orchestration
- `tools/`: SCM access, AST helpers, static analysis adapters
- `llm/`: provider abstraction for Anthropic and OpenAI-compatible backends
- `api/`: minimal HTTP interface for creating and polling review tasks
- `tests/`: unit tests around orchestration and API behavior

### Optional / non-core modules

- `ui/`: minimal Streamlit demo client
- `deploy/`: nginx, docker, and systemd deployment examples
- `notifications/`: optional webhook integrations
- `graph/`: experimental / alternate orchestration flow
- `eval/`: evaluation utilities

## Public Interfaces

### Primary API surface

- `POST /review`
- `GET /review/{task_id}`

These two endpoints are the main resume-facing interface for the framework. Other endpoints remain in the codebase as optional extensions for demo and operations use cases.

### Core data structures

```python
class FileDiff(BaseModel):
    filename: str
    language: str
    added_lines: list[tuple[int, str]]
    removed_lines: list[tuple[int, str]]
    raw_diff: str

class Finding(BaseModel):
    file: str
    line_start: int
    line_end: int
    severity: str
    category: str
    description: str
    suggestion: str
    confidence: float

class AgentResult(BaseModel):
    agent_name: str
    findings: list[Finding]
    summary: str
    execution_time: float
    token_used: int
```

The aggregated output is emitted as `AggregatedReport`, which provides the final deduplicated findings and Markdown report.

## Specialized Agents

Each agent follows the same contract:

- **Input:** `FileDiff`
- **Output:** structured `Finding[]` wrapped in `AgentResult`
- **Strategy:** rules, static analysis, or LLM reasoning tuned to one review dimension

### StyleAgent

- Focus: naming, docstrings, duplication, magic numbers, import hygiene
- Strategy: LLM review over added lines only

### SecurityAgent

- Focus: injection, secrets, traversal, deserialization, dangerous APIs
- Strategy: Semgrep pre-scan plus LLM validation

### LogicAgent

- Focus: boundary conditions, missing error handling, recursion, null dereference
- Strategy: AST preprocessing plus LLM review

### PerformanceAgent

- Focus: N+1 queries, redundant work, inefficient structures, blocking I/O
- Strategy: complexity hints plus LLM review

## Why Not A Single Agent

- **Role separation:** each agent can use narrower prompts, heuristics, and validation rules.
- **Parallelism:** independent agents can run concurrently and reduce end-to-end latency.
- **Aggregation:** the framework can reconcile duplicates and severity conflicts after specialization.
- **Extensibility:** adding a new review dimension does not require redesigning the entire system.

## Extensibility

- Add a new review dimension by implementing `BaseReviewAgent`.
- Add a new source-control provider by implementing `SCMClient`.
- Add a new model backend by implementing a provider adapter in `llm/provider.py`.

This keeps the framework open to new review domains, repositories, and model stacks without changing the public task API.

## Sample Report

Below is a representative condensed output shape:

```json
{
  "task_id": 12,
  "status": "completed",
  "results": [
    {
      "agent_name": "SecurityAgent",
      "findings": {
        "findings": [
          {
            "file": "api/routes.py",
            "line_start": 42,
            "line_end": 42,
            "severity": "HIGH",
            "category": "sql_injection",
            "description": "User input is interpolated into a SQL statement.",
            "suggestion": "Use parameterized queries or ORM placeholders.",
            "confidence": 0.91
          }
        ]
      },
      "confidence": 0.91
    }
  ],
  "report": {
    "markdown_report": "## Executive Summary\n\n1 high-confidence security finding..."
  }
}
```

## Quick Start

### 1. Install dependencies

```bash
cd /root/project/CodeReview-Agent
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Start PostgreSQL and Redis

```bash
docker run -d --name codereview-postgres \
  -p 5432:5432 \
  -e POSTGRES_PASSWORD=postgres \
  -e POSTGRES_DB=codereview \
  postgres:15

docker run -d --name codereview-redis -p 6379:6379 redis:7
```

### 3. Configure environment

```bash
cp .env.example .env
```

Minimum useful variables:

- `LLM_PROVIDER`
- `LLM_MODEL`
- `OPENAI_API_KEY` or `ANTHROPIC_API_KEY`
- `GITHUB_TOKEN`
- `DATABASE_URL`
- `REDIS_URL`

### 4. Start the framework API

```bash
uvicorn api.main:app --host 0.0.0.0 --port 8000
```

### 5. Start the demo UI

```bash
streamlit run ui/app.py
```

## Demo Usage

### Create a review task

```bash
curl -X POST http://127.0.0.1:8000/review \
  -H "Content-Type: application/json" \
  -d '{"pr_url":"https://github.com/owner/repo/pull/42"}'
```

### Poll task status

```bash
curl http://127.0.0.1:8000/review/1
```

### Demo UI

The Streamlit app is intentionally minimal:

- submit a GitHub PR URL
- inspect recent tasks
- view the final report and raw findings

## Testing

Run the targeted test suite:

```bash
pytest tests/test_api_main.py tests/test_orchestrator.py
```

These tests cover:

- task creation and background orchestration
- task status retrieval
- recent task listing
- orchestrator success, timeout, and SCM failure paths

## Optional Extensions

These capabilities remain in the repository, but they are not the main framing of the project:

- GitHub webhook trigger
- PR comment write-back
- stats endpoints
- notification webhooks
- deployment examples
- alternate orchestration experiments

See [docs/architecture.md](docs/architecture.md) for the framework-focused design summary and [docs/legacy.md](docs/legacy.md) for the deprioritized platform capabilities.
