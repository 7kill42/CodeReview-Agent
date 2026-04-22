from __future__ import annotations

import importlib
import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import MagicMock, patch

from agents.base import AgentResult, Finding
from agents.orchestrator import Orchestrator
from llm.provider import OpenAIProvider, get_provider


def _import_graph_workflow(monkeypatch):
    fake_langgraph = ModuleType("langgraph")
    fake_graph = ModuleType("langgraph.graph")

    class FakeStateGraph:
        def __init__(self, *_args, **_kwargs):
            pass

        def add_node(self, *_args, **_kwargs):
            return None

        def set_entry_point(self, *_args, **_kwargs):
            return None

        def add_conditional_edges(self, *_args, **_kwargs):
            return None

        def add_edge(self, *_args, **_kwargs):
            return None

        def compile(self):
            return "compiled"

    fake_graph.END = "__end__"
    fake_graph.StateGraph = FakeStateGraph
    fake_langgraph.graph = fake_graph

    monkeypatch.setitem(sys.modules, "langgraph", fake_langgraph)
    monkeypatch.setitem(sys.modules, "langgraph.graph", fake_graph)
    sys.modules.pop("graph.workflow", None)
    return importlib.import_module("graph.workflow")


def test_openai_provider_maps_input_schema_to_parameters(monkeypatch):
    captured: dict = {}

    class FakeCompletions:
        def create(self, **kwargs):
            captured.update(kwargs)
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(
                            content=None,
                            tool_calls=[
                                SimpleNamespace(
                                    function=SimpleNamespace(
                                        name="report_findings",
                                        arguments='{"findings": []}',
                                    )
                                )
                            ],
                        )
                    )
                ],
                usage=SimpleNamespace(prompt_tokens=12, completion_tokens=3),
            )

    class FakeOpenAIClient:
        def __init__(self, **_kwargs):
            self.chat = SimpleNamespace(completions=FakeCompletions())

    fake_openai = ModuleType("openai")
    fake_openai.OpenAI = FakeOpenAIClient
    monkeypatch.setitem(sys.modules, "openai", fake_openai)

    provider = OpenAIProvider(api_key="test-key", base_url="https://example.com/v1")
    response = provider.messages_create(
        model="test-model",
        max_tokens=256,
        messages=[{"role": "user", "content": "review this"}],
        tools=[
            {
                "name": "report_findings",
                "description": "Report findings.",
                "input_schema": {
                    "type": "object",
                    "properties": {"findings": {"type": "array"}},
                },
            }
        ],
        tool_choice={"type": "any"},
    )

    assert captured["tools"][0]["function"]["parameters"] == {
        "type": "object",
        "properties": {"findings": {"type": "array"}},
    }
    assert captured["tool_choice"] == "required"
    assert response.tool_calls[0].name == "report_findings"
    assert response.tool_calls[0].input == {"findings": []}
    assert response.total_tokens == 15


def test_openai_provider_accepts_parameters_schema(monkeypatch):
    captured: dict = {}

    class FakeCompletions:
        def create(self, **kwargs):
            captured.update(kwargs)
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content="ok", tool_calls=None))],
                usage=SimpleNamespace(prompt_tokens=5, completion_tokens=2),
            )

    class FakeOpenAIClient:
        def __init__(self, **_kwargs):
            self.chat = SimpleNamespace(completions=FakeCompletions())

    fake_openai = ModuleType("openai")
    fake_openai.OpenAI = FakeOpenAIClient
    monkeypatch.setitem(sys.modules, "openai", fake_openai)

    provider = OpenAIProvider(api_key="test-key", base_url="https://example.com/v1")
    provider.messages_create(
        model="test-model",
        max_tokens=128,
        messages=[{"role": "user", "content": "hello"}],
        tools=[
            {
                "name": "report_findings",
                "description": "Report findings.",
                "parameters": {
                    "type": "object",
                    "properties": {"severity": {"type": "string"}},
                },
            }
        ],
    )

    assert captured["tools"][0]["function"]["parameters"] == {
        "type": "object",
        "properties": {"severity": {"type": "string"}},
    }


def test_qwenapi_alias_uses_openai_compatible_provider(monkeypatch):
    class FakeOpenAIClient:
        def __init__(self, **_kwargs):
            self.chat = SimpleNamespace(completions=MagicMock())

    fake_openai = ModuleType("openai")
    fake_openai.OpenAI = FakeOpenAIClient
    monkeypatch.setitem(sys.modules, "openai", fake_openai)

    provider = get_provider(
        provider="qwenapi",
        api_key="test-key",
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
    )

    assert isinstance(provider, OpenAIProvider)


def test_orchestrator_uses_default_agent_and_aggregator_constructors():
    with (
        patch("agents.orchestrator.StyleAgent", return_value="style") as mock_style,
        patch("agents.orchestrator.SecurityAgent", return_value="security") as mock_security,
        patch("agents.orchestrator.LogicAgent", return_value="logic") as mock_logic,
        patch("agents.orchestrator.PerformanceAgent", return_value="performance") as mock_perf,
        patch("agents.orchestrator.Aggregator", return_value="aggregator") as mock_agg,
    ):
        orchestrator = Orchestrator()

    assert orchestrator.agents == ["style", "security", "logic", "performance"]
    assert orchestrator.aggregator == "aggregator"
    mock_style.assert_called_once_with()
    mock_security.assert_called_once_with()
    mock_logic.assert_called_once_with()
    mock_perf.assert_called_once_with()
    mock_agg.assert_called_once_with()


def test_langgraph_helpers_use_default_constructors(monkeypatch):
    workflow_module = _import_graph_workflow(monkeypatch)
    with (
        patch.object(workflow_module, "StyleAgent", return_value="style") as mock_style,
        patch.object(workflow_module, "SecurityAgent", return_value="security") as mock_security,
        patch.object(workflow_module, "LogicAgent", return_value="logic") as mock_logic,
        patch.object(workflow_module, "PerformanceAgent", return_value="performance") as mock_perf,
    ):
        agents = workflow_module._make_agents()

    assert agents == {
        "StyleAgent": "style",
        "SecurityAgent": "security",
        "LogicAgent": "logic",
        "PerformanceAgent": "performance",
    }
    mock_style.assert_called_once_with()
    mock_security.assert_called_once_with()
    mock_logic.assert_called_once_with()
    mock_perf.assert_called_once_with()


def test_langgraph_aggregate_uses_default_aggregator_constructor(monkeypatch):
    workflow_module = _import_graph_workflow(monkeypatch)
    agent_result = AgentResult(
        agent_name="StyleAgent",
        findings=[
            Finding(
                file="app.py",
                line_start=1,
                line_end=1,
                severity="LOW",
                category="naming",
                description="desc",
                suggestion="fix",
                confidence=0.6,
            )
        ],
        summary="ok",
        execution_time=0.1,
        token_used=10,
    )
    fake_report = MagicMock()
    fake_report.model_dump.return_value = {"markdown_report": "# Report"}
    state = {
        "task_id": 1,
        "pr_url": "https://github.com/example/repo/pull/1",
        "agent_results": {"StyleAgent": [agent_result.model_dump()]},
        "pr_metadata": {},
        "error": None,
    }

    with patch.object(workflow_module, "Aggregator") as mock_agg_cls:
        mock_agg = mock_agg_cls.return_value
        mock_agg.aggregate.return_value = fake_report

        updated = workflow_module.aggregate(state)

    mock_agg_cls.assert_called_once_with()
    assert updated["report"] == {"markdown_report": "# Report"}
    assert updated["error"] is None
