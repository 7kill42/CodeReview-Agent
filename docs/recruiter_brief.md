# CodeReview-Agent Recruiter Brief

## 一句话定位

面向 GitHub Pull Request 场景的多智能体代码审查系统，将 diff 解析、风险分类、专项 Agent 审查、结果聚合与 Merge Gate 建议串联为完整流程。

## 为什么适合 Agent 开发岗位

- 不是单个“代码审查 prompt”，而是把审查任务拆成 Style、Security、Logic、Performance 等专项 Agent。
- 通过 RiskProfile 和 review playbook 控制不同 PR 的审查策略，体现任务路由和工作流编排能力。
- 使用 Semgrep、AST 分析和 LLM 推理组合判断问题，避免完全依赖模型自由生成。
- 输出统一的 Finding / AgentResult / AggregatedReport，便于测试、持久化、前端展示和 GitHub 评论回写。

## 核心链路

```text
GitHub PR URL
  -> Fetch & normalize diff
  -> RiskProfile classification
  -> Playbook selection
  -> Specialized agents
  -> Aggregator dedup / severity arbitration
  -> Merge Gate report
```

## 技术亮点

- **多 Agent 分工：** 按审查维度拆分 Agent，降低单一大 prompt 的不稳定性。
- **异步编排：** 基于 FastAPI 后台任务执行审查流程，支持任务创建、状态轮询和事件追踪。
- **工具增强：** 安全问题使用 Semgrep 预扫描，逻辑和复杂度问题引入 AST 结构分析。
- **结果聚合：** 对多个 Agent findings 做去重、置信度加权和严重级别裁决，输出统一 Markdown 报告。
- **工程化接口：** 提供 `/review`、`/agents`、`/playbooks`、`/llm/providers` 等 API，便于演示和扩展。

## 面试可讲问题

- 为什么不做单 Agent，而要拆成多个专项 Agent？
- RiskProfile 如何影响 Agent 选择和 playbook？
- Semgrep / AST / LLM 三类信号如何互补？
- Aggregator 如何处理重复 findings 和 severity 冲突？
- 如果要接入新的 SCM、模型或审查维度，应该改哪些接口？

## 建议展示方式

1. 提交一个 PR URL，说明系统如何解析 diff。
2. 展示 RiskProfile 和 selected playbooks。
3. 展示某个 SecurityAgent 或 LogicAgent 的结构化 finding。
4. 展示 Aggregator 生成的 Merge Gate Markdown 报告。
