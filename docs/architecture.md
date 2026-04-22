# Architecture Notes

CodeReview-Agent is organized around a small set of framework responsibilities rather than a full product stack.

## Core Flow

`GitHub PR -> FileDiff normalization -> Orchestrator -> Specialized Agents -> Aggregator -> Structured report`

## Main Responsibilities

### Orchestrator

- fetches the pull request diff from the configured SCM adapter
- filters supported languages
- dispatches review agents concurrently
- persists status transitions and final results

### Specialized Agents

Each review agent implements the same contract:

- input: `FileDiff`
- output: `AgentResult`
- purpose: inspect one review dimension with a focused strategy

Current agents:

- `StyleAgent`
- `SecurityAgent`
- `LogicAgent`
- `PerformanceAgent`

### Aggregator

- deduplicates overlapping findings
- arbitrates final severity based on weighted confidence
- generates the executive summary and Markdown report

## Extension Points

### New agent

Implement `BaseReviewAgent.review(file_diff) -> AgentResult`.

### New SCM backend

Implement `SCMClient` and wire it through `tools/scm_factory.py`.

### New model backend

Add a provider implementation in `llm/provider.py` and return it from `get_provider`.

## Design Tradeoff

The project deliberately keeps a thin public API and a thin demo UI. The interesting engineering work lives in:

- decomposition across specialized agents
- framework-level orchestration
- structured result merging
- replaceable adapters around SCM, static analysis, and LLM providers
