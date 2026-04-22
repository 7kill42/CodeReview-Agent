# Legacy / Deprioritized Capabilities

These modules remain in the repository, but they are not the main framing of the project.

## Demo and Platform Extras

- `ui/`: demo client for submitting and inspecting review tasks
- `deploy/`: nginx, docker, systemd, and environment templates
- `notifications/`: Slack and WeChat webhook integration
- `graph/`: alternate orchestration experiments
- `eval/`: evaluation helpers and metrics scripts

## Why They Still Exist

- They are useful for local demos and operational experiments.
- They show that the framework can be embedded in a larger system.
- They are intentionally secondary to the agent framework itself.

## Resume Framing

If this project is presented on a resume or portfolio, the recommended emphasis is:

1. multi-agent decomposition
2. orchestration and aggregation design
3. structured review output
4. extensibility across SCM and LLM adapters

Deployment assets, dashboards, and webhook integrations should be treated as optional supporting context rather than the headline story.
