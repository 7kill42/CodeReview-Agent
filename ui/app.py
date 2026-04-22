"""Minimal Streamlit demo for the CodeReview-Agent framework."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import httpx
import streamlit as st
from dotenv import load_dotenv


load_dotenv(Path(__file__).resolve().parent.parent / ".env")

API_BASE = os.getenv("API_BASE", "http://127.0.0.1:8000")
STATUS_LABELS = {
    "pending": "Queued",
    "running": "Running",
    "completed": "Completed",
    "failed": "Failed",
}
STATUS_ICONS = {
    "pending": "⏳",
    "running": "⚙️",
    "completed": "✅",
    "failed": "❌",
}
SEVERITY_ORDER = ["CRITICAL", "HIGH", "MEDIUM", "LOW"]

st.set_page_config(
    page_title="CodeReview-Agent Demo",
    page_icon="🧭",
    layout="wide",
)


def _inject_css() -> None:
    st.markdown(
        """
        <style>
          .stApp {
            background:
              radial-gradient(circle at top left, rgba(255, 212, 170, 0.35), transparent 30%),
              radial-gradient(circle at bottom right, rgba(177, 214, 197, 0.3), transparent 25%),
              linear-gradient(180deg, #faf7f2 0%, #f2eadf 100%);
          }
          .block {
            background: rgba(255, 252, 247, 0.92);
            border: 1px solid rgba(130, 96, 60, 0.15);
            border-radius: 16px;
            padding: 20px 22px;
            box-shadow: 0 10px 28px rgba(28, 22, 16, 0.06);
            margin-bottom: 16px;
          }
          .hero h1 {
            margin-bottom: 0.25rem;
            font-size: 2rem;
          }
          .hero p {
            color: #5f564c;
            margin-bottom: 0;
          }
          .muted {
            color: #6a6158;
            font-size: 0.95rem;
          }
          .status-pill {
            display: inline-block;
            padding: 4px 10px;
            border-radius: 999px;
            background: #f2e5d6;
            color: #6b4c2f;
            font-size: 0.85rem;
            font-weight: 600;
          }
          .finding {
            border-left: 4px solid #d9c2a6;
            padding: 12px 14px;
            margin-bottom: 12px;
            background: rgba(255,255,255,0.72);
            border-radius: 10px;
          }
          .finding code {
            white-space: pre-wrap;
          }
        </style>
        """,
        unsafe_allow_html=True,
    )


@st.cache_resource
def _http_client() -> httpx.Client:
    return httpx.Client(
        base_url=API_BASE,
        timeout=httpx.Timeout(connect=5.0, read=30.0, write=10.0, pool=5.0),
        limits=httpx.Limits(max_keepalive_connections=5, max_connections=10),
    )


def _safe_get(path: str, **kwargs: Any) -> dict[str, Any] | list[dict[str, Any]] | None:
    try:
        response = _http_client().get(path, **kwargs)
        response.raise_for_status()
        return response.json()
    except Exception as exc:  # noqa: BLE001
        st.error(f"Request failed: {exc}")
        return None


def _safe_post(path: str, payload: dict[str, Any]) -> dict[str, Any] | None:
    try:
        response = _http_client().post(path, json=payload)
        response.raise_for_status()
        return response.json()
    except Exception as exc:  # noqa: BLE001
        st.error(f"Request failed: {exc}")
        return None


@st.cache_data(ttl=3, show_spinner=False)
def _get_task(task_id: int, include_results: bool) -> dict[str, Any] | None:
    data = _safe_get(f"/review/{task_id}", params={"include_results": str(include_results).lower()})
    return data if isinstance(data, dict) else None


@st.cache_data(ttl=10, show_spinner=False)
def _get_recent_tasks(limit: int = 8) -> list[dict[str, Any]]:
    data = _safe_get("/reviews/recent", params={"limit": limit})
    return data if isinstance(data, list) else []


def _clear_caches() -> None:
    _get_task.clear()
    _get_recent_tasks.clear()


def _status_text(status: str) -> str:
    return f"{STATUS_ICONS.get(status, '•')} {STATUS_LABELS.get(status, status)}"


def _render_hero() -> None:
    st.markdown(
        """
        <div class="hero">
          <h1>CodeReview-Agent Demo</h1>
          <p>Multi-agent code review framework for GitHub pull requests.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.markdown(
        """
        <div class="block muted">
          <strong>Framework flow:</strong> PR diff → Orchestrator → Specialized Agents → Aggregator → Structured report
        </div>
        """,
        unsafe_allow_html=True,
    )


def _render_submit() -> None:
    st.markdown('<div class="block">', unsafe_allow_html=True)
    st.subheader("Submit a Pull Request")
    st.caption("Use the demo client to create a review task through the framework API.")
    pr_url = st.text_input(
        "GitHub PR URL",
        placeholder="https://github.com/owner/repo/pull/123",
        label_visibility="collapsed",
    )
    submit = st.button("Start Review", use_container_width=True, type="primary")
    if submit:
        if not pr_url.strip():
            st.warning("Please enter a GitHub PR URL.")
        else:
            data = _safe_post("/review", {"pr_url": pr_url.strip()})
            if data:
                task_id = data["task_id"]
                st.session_state["selected_task_id"] = task_id
                _clear_caches()
                st.success(f"Task #{task_id} created.")
                st.rerun()
    st.markdown('</div>', unsafe_allow_html=True)


@st.experimental_fragment(run_every="4s")
def _render_task_list() -> None:
    st.markdown('<div class="block">', unsafe_allow_html=True)
    top_left, top_right = st.columns([3, 1])
    with top_left:
        st.subheader("Recent Tasks")
    with top_right:
        if st.button("Refresh", use_container_width=True):
            _clear_caches()
            st.rerun()

    tasks = _get_recent_tasks()
    if not tasks:
        st.caption("No review tasks yet.")
    for task in tasks:
        label = f"#{task['task_id']} · {_status_text(task['status'])}"
        if st.button(label, key=f"task_{task['task_id']}", use_container_width=True):
            st.session_state["selected_task_id"] = task["task_id"]
            st.rerun()
        st.caption(task["pr_url"])
    st.markdown('</div>', unsafe_allow_html=True)


def _render_findings(findings: list[dict[str, Any]]) -> None:
    if not findings:
        st.success("No findings reported.")
        return

    ordered = sorted(
        findings,
        key=lambda item: (
            SEVERITY_ORDER.index(item["severity"]) if item["severity"] in SEVERITY_ORDER else 99,
            item["file"],
            item["line_start"],
        ),
    )
    for finding in ordered:
        st.markdown(
            f"""
            <div class="finding">
              <strong>{finding['severity']}</strong> · <code>{finding['file']}:{finding['line_start']}</code> · {finding['category']}<br/>
              {finding['description']}<br/><br/>
              <strong>Suggestion:</strong> {finding['suggestion']}
            </div>
            """,
            unsafe_allow_html=True,
        )


@st.experimental_fragment(run_every="4s")
def _render_task_detail() -> None:
    task_id = st.session_state.get("selected_task_id")
    st.markdown('<div class="block">', unsafe_allow_html=True)
    st.subheader("Task Detail")

    if task_id is None:
        st.caption("Select a task from the left or submit a new PR to inspect the report.")
        st.markdown('</div>', unsafe_allow_html=True)
        return

    task = _get_task(task_id, include_results=True)
    if task is None:
        st.info(f"Could not load task #{task_id}.")
        st.markdown('</div>', unsafe_allow_html=True)
        return

    status = task["status"]
    st.markdown(
        f'<span class="status-pill">Task #{task_id} · {_status_text(status)}</span>',
        unsafe_allow_html=True,
    )
    st.caption(task["pr_url"])

    if status in {"pending", "running"}:
        st.info("The orchestrator is still running. Task status updates every 4 seconds without reloading the page.")
        st.markdown('</div>', unsafe_allow_html=True)
        return

    report = task.get("report")
    if report:
        st.markdown("### Executive Report")
        st.markdown(report["markdown_report"])

    results = task.get("results", [])
    merged_findings: list[dict[str, Any]] = []
    for result in results:
        merged_findings.extend(result.get("findings", {}).get("findings", []))

    st.markdown("### Raw Findings")
    _render_findings(merged_findings)
    st.markdown('</div>', unsafe_allow_html=True)


def main() -> None:
    _inject_css()
    _render_hero()

    left, right = st.columns([1, 1.6], gap="large")
    with left:
        _render_submit()
        _render_task_list()
    with right:
        _render_task_detail()


if __name__ == "__main__":
    main()
