"""Streamlit demo UI for CodeReview-Agent."""

import json
import os
import time

import httpx
import streamlit as st

API_BASE = os.getenv("API_BASE", "http://localhost:8000")

SEVERITY_COLOR = {
    "CRITICAL": "🔴",
    "HIGH":     "🟠",
    "MEDIUM":   "🟡",
    "LOW":      "🟢",
}

SEVERITY_ORDER = ["CRITICAL", "HIGH", "MEDIUM", "LOW"]

AGENT_TABS = [
    ("Summary",     None),
    ("Security",    "SecurityAgent"),
    ("Logic",       "LogicAgent"),
    ("Performance", "PerformanceAgent"),
    ("Style",       "StyleAgent"),
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _post_review(pr_url: str) -> int | None:
    """Submit a review task, return task_id or None on error."""
    try:
        resp = httpx.post(f"{API_BASE}/review", json={"pr_url": pr_url}, timeout=10)
        resp.raise_for_status()
        return resp.json()["task_id"]
    except Exception as exc:  # noqa: BLE001
        st.error(f"Failed to submit review: {exc}")
        return None


def _get_status(task_id: int) -> dict | None:
    """Poll task status, return response dict or None on error."""
    try:
        resp = httpx.get(f"{API_BASE}/review/{task_id}", timeout=10)
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:  # noqa: BLE001
        st.error(f"Failed to fetch status: {exc}")
        return None


def _render_finding_card(finding: dict) -> None:
    severity = finding.get("severity", "LOW")
    icon = SEVERITY_COLOR.get(severity, "")
    file_ = finding.get("file", "")
    l_start = finding.get("line_start", "?")
    l_end = finding.get("line_end", "?")
    category = finding.get("category", "")
    description = finding.get("description", "")
    suggestion = finding.get("suggestion", "")
    confidence = finding.get("confidence", 0.0)
    sources = ", ".join(finding.get("source_agents", []))

    with st.container(border=True):
        st.markdown(
            f"{icon} **[{category}]** `{file_}` L{l_start}–{l_end}"
        )
        st.markdown(f"**Description:** {description}")
        st.markdown(f"**Suggestion:** {suggestion}")
        st.caption(f"Confidence: {confidence:.0%} | Sources: {sources}")


def _render_agent_tab(findings: list[dict], agent_name: str | None) -> None:
    """Render findings for one agent tab (None = all agents = Summary)."""
    if agent_name is not None:
        subset = [
            f for f in findings
            if agent_name in f.get("source_agents", [])
        ]
    else:
        subset = findings

    if not subset:
        st.info("No findings.")
        return

    for sev in SEVERITY_ORDER:
        group = [f for f in subset if f.get("severity") == sev]
        if not group:
            continue
        st.markdown(f"### {SEVERITY_COLOR[sev]} {sev} ({len(group)})")
        for finding in group:
            _render_finding_card(finding)


# ---------------------------------------------------------------------------
# Dashboard helpers
# ---------------------------------------------------------------------------

def _get_stats_summary() -> dict | None:
    try:
        resp = httpx.get(f"{API_BASE}/stats/summary", timeout=10)
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:  # noqa: BLE001
        st.error(f"Failed to fetch summary stats: {exc}")
        return None


def _get_top_categories(limit: int = 10) -> list | None:
    try:
        resp = httpx.get(f"{API_BASE}/stats/top_categories", params={"limit": limit}, timeout=10)
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:  # noqa: BLE001
        st.error(f"Failed to fetch category stats: {exc}")
        return None


def _get_trends(days: int = 30) -> dict | None:
    try:
        resp = httpx.get(f"{API_BASE}/stats/trends", params={"days": days}, timeout=10)
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:  # noqa: BLE001
        st.error(f"Failed to fetch trend stats: {exc}")
        return None


def _render_dashboard() -> None:
    st.header("Dashboard")

    days = st.sidebar.slider("Trend window (days)", min_value=7, max_value=90, value=30, step=7)
    if st.sidebar.button("Refresh"):
        st.rerun()

    summary = _get_stats_summary()
    if summary:
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Total Tasks",    summary.get("total_tasks", 0))
        c2.metric("Completed",       summary.get("completed", 0))
        c3.metric("Failed",          summary.get("failed", 0))
        c4.metric("Total Findings",  summary.get("total_findings", 0))

        st.subheader("Findings by Severity")
        sev_data = {row["severity"]: row["count"] for row in summary.get("by_severity", [])}
        if sev_data:
            ordered = {s: sev_data.get(s, 0) for s in SEVERITY_ORDER if s in sev_data}
            st.bar_chart(ordered)
        else:
            st.info("No findings recorded yet.")

    st.divider()

    top_cats = _get_top_categories()
    if top_cats:
        st.subheader("Top 10 Finding Categories")
        cat_data = {row["category"]: row["count"] for row in top_cats}
        st.bar_chart(cat_data)

    st.divider()

    trends = _get_trends(days=days)
    if trends:
        st.subheader(f"Daily Activity (last {days} days)")
        task_points   = trends.get("tasks", [])
        finding_points = trends.get("findings", [])

        if task_points:
            task_chart = {p["date"]: p["count"] for p in task_points}
            st.write("**Reviews submitted per day**")
            st.bar_chart(task_chart)

        if finding_points:
            finding_chart = {p["date"]: p["count"] for p in finding_points}
            st.write("**Findings per day**")
            st.bar_chart(finding_chart)

        if not task_points and not finding_points:
            st.info("No activity in this period.")


# ---------------------------------------------------------------------------
# Page layout
# ---------------------------------------------------------------------------

st.set_page_config(page_title="CodeReview-Agent", page_icon="🔍", layout="wide")

page = st.sidebar.radio("Navigation", ["Review", "Dashboard"], index=0)

if page == "Dashboard":
    _render_dashboard()
    st.stop()

st.title("CodeReview-Agent 🔍")
st.caption("Multi-agent AI code review powered by Claude")

# --- Input ---
col_input, col_btn = st.columns([5, 1])
with col_input:
    pr_url = st.text_input("GitHub PR URL", placeholder="https://github.com/owner/repo/pull/123", label_visibility="collapsed")
with col_btn:
    start = st.button("Start Review", use_container_width=True)

if start and pr_url:
    task_id = _post_review(pr_url)
    if task_id is not None:
        st.session_state["task_id"] = task_id
        st.session_state["data"] = None
        st.rerun()

# --- Polling ---
if "task_id" in st.session_state and st.session_state.get("data") is None:
    task_id = st.session_state["task_id"]
    progress_bar = st.progress(0, text="Submitting review...")
    step = 0
    while True:
        data = _get_status(task_id)
        if data is None:
            break
        current_status = data.get("status", "")
        step = min(step + 10, 90)
        progress_bar.progress(step, text=f"Status: {current_status}...")
        if current_status in ("completed", "failed"):
            progress_bar.progress(100, text=f"Done: {current_status}")
            st.session_state["data"] = data
            time.sleep(0.5)
            st.rerun()
            break
        time.sleep(2)
        st.rerun()

# --- Results ---
if "data" in st.session_state and st.session_state["data"] is not None:
    data = st.session_state["data"]

    if data.get("status") == "failed":
        st.error("Review failed. Check the API logs for details.")

    elif data.get("status") == "completed" and data.get("report"):
        report_raw = data["report"]
        markdown_report: str = report_raw.get("markdown_report", "")

        # Parse JSON report (final_report field)
        try:
            agg: dict = json.loads(report_raw.get("final_report", "{}"))
        except (json.JSONDecodeError, TypeError):
            agg = {}

        findings: list[dict] = agg.get("findings", [])
        executive_summary: str = agg.get("executive_summary", "")
        stats: dict = agg.get("stats", {})

        # --- Tabs ---
        tab_labels = [t[0] for t in AGENT_TABS]
        tabs = st.tabs(tab_labels)

        # Summary tab
        with tabs[0]:
            if executive_summary:
                st.subheader("Executive Summary")
                st.write(executive_summary)

            st.subheader("Statistics")
            sev_counts = {
                sev: sum(1 for f in findings if f.get("severity") == sev)
                for sev in SEVERITY_ORDER
            }
            table_data = {
                "Severity": [f"{SEVERITY_COLOR[s]} {s}" for s in SEVERITY_ORDER],
                "Count":    [sev_counts[s] for s in SEVERITY_ORDER],
            }
            st.table(table_data)

        # Agent tabs
        for i, (label, agent_name) in enumerate(AGENT_TABS[1:], start=1):
            with tabs[i]:
                _render_agent_tab(findings, agent_name)

        # Download button
        st.divider()
        st.download_button(
            label="Download Markdown Report",
            data=markdown_report,
            file_name="code_review_report.md",
            mime="text/markdown",
        )
