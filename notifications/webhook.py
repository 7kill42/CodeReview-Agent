"""Notification helpers – Slack and WeChat Work (企业微信) webhooks."""
from __future__ import annotations

import logging

import httpx

from config import settings

logger = logging.getLogger(__name__)

_SEVERITY_ICON = {
    "CRITICAL": "\U0001f534",
    "HIGH":     "\U0001f7e0",
    "MEDIUM":   "\U0001f7e1",
    "LOW":      "\U0001f7e2",
}

_NOTIFY_SEVERITIES: set[str] = {
    s.strip().upper()
    for s in settings.NOTIFY_ON_SEVERITIES.split(",")
    if s.strip()
}


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

async def notify_review_complete(
    pr_url: str,
    task_id: int,
    stats: dict,
    executive_summary: str,
) -> None:
    """Send a review-complete notification to configured channels.

    Silently skips if ENABLE_NOTIFY is False or no webhook URLs are set.
    """
    if not settings.ENABLE_NOTIFY:
        return

    # Decide whether this review is worth notifying about
    by_severity: dict[str, int] = stats.get("by_severity", {})
    triggered = any(
        by_severity.get(sev, 0) > 0 for sev in _NOTIFY_SEVERITIES
    )
    if not triggered:
        logger.info("[task=%s] No findings above notify threshold – skipping notification", task_id)
        return

    message = _build_message(pr_url, task_id, stats, executive_summary)

    async with httpx.AsyncClient(timeout=10) as client:
        if settings.SLACK_WEBHOOK_URL:
            await _send_slack(client, message, pr_url, stats)
        if settings.WECHAT_WEBHOOK_URL:
            await _send_wechat(client, message)


async def notify_review_failed(
    pr_url: str,
    task_id: int,
    reason: str,
) -> None:
    """Send a failure notification. Only fires if ENABLE_NOTIFY is True."""
    if not settings.ENABLE_NOTIFY:
        return

    async with httpx.AsyncClient(timeout=10) as client:
        msg = f"CodeReview-Agent task #{task_id} failed\nPR: {pr_url}\nReason: {reason}"
        if settings.SLACK_WEBHOOK_URL:
            await _send_slack_text(client, msg)
        if settings.WECHAT_WEBHOOK_URL:
            await _send_wechat_text(client, msg)


# ---------------------------------------------------------------------------
# Message builders
# ---------------------------------------------------------------------------

def _build_message(
    pr_url: str,
    task_id: int,
    stats: dict,
    executive_summary: str,
) -> str:
    by_sev = stats.get("by_severity", {})
    total  = stats.get("total", 0)
    lines  = [f"*CodeReview-Agent* finished task #{task_id}"]
    lines.append(f"PR: {pr_url}")
    lines.append(f"Total findings: {total}")
    for sev in ["CRITICAL", "HIGH", "MEDIUM", "LOW"]:
        count = by_sev.get(sev, 0)
        if count:
            icon = _SEVERITY_ICON.get(sev, "")
            lines.append(f"{icon} {sev}: {count}")
    if executive_summary:
        lines.append("")
        lines.append(executive_summary[:400])   # truncate for webhook
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Slack
# ---------------------------------------------------------------------------

async def _send_slack(client: httpx.AsyncClient, text: str, pr_url: str, stats: dict) -> None:
    payload = {
        "blocks": [
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": text},
            },
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "View PR"},
                        "url": pr_url,
                    }
                ],
            },
        ]
    }
    try:
        resp = await client.post(settings.SLACK_WEBHOOK_URL, json=payload)
        resp.raise_for_status()
    except Exception as exc:
        logger.warning("Slack notification failed: %s", exc)


async def _send_slack_text(client: httpx.AsyncClient, text: str) -> None:
    try:
        resp = await client.post(settings.SLACK_WEBHOOK_URL, json={"text": text})
        resp.raise_for_status()
    except Exception as exc:
        logger.warning("Slack notification failed: %s", exc)


# ---------------------------------------------------------------------------
# WeChat Work (企业微信)
# ---------------------------------------------------------------------------

async def _send_wechat(client: httpx.AsyncClient, text: str) -> None:
    payload = {"msgtype": "markdown", "markdown": {"content": text}}
    try:
        resp = await client.post(settings.WECHAT_WEBHOOK_URL, json=payload)
        resp.raise_for_status()
    except Exception as exc:
        logger.warning("WeChat notification failed: %s", exc)


async def _send_wechat_text(client: httpx.AsyncClient, text: str) -> None:
    payload = {"msgtype": "text", "text": {"content": text}}
    try:
        resp = await client.post(settings.WECHAT_WEBHOOK_URL, json=payload)
        resp.raise_for_status()
    except Exception as exc:
        logger.warning("WeChat notification failed: %s", exc)
