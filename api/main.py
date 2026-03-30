"""FastAPI application for CodeReview-Agent."""

import asyncio
import hashlib
import hmac
import json
from contextlib import asynccontextmanager
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.responses import JSONResponse
from pydantic import AnyHttpUrl, BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from agents.orchestrator import Orchestrator
from config import settings
from storage.models import (
    Base,
    ReviewReport,
    ReviewResult,
    ReviewTask,
    TaskStatus,
    engine,
    get_db,
)
from storage.cache import get_task_status, set_task_status


# ---------------------------------------------------------------------------
# Lifespan: create tables on startup
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    await engine.dispose()


# ---------------------------------------------------------------------------
# App instance
# ---------------------------------------------------------------------------

app = FastAPI(
    title="CodeReview-Agent",
    description="Multi-agent AI code review service",
    version="0.1.0",
    lifespan=lifespan,
)


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class ReviewRequest(BaseModel):
    pr_url: AnyHttpUrl = Field(..., description="Full URL of the GitHub Pull Request")


class ReviewCreateResponse(BaseModel):
    task_id: int
    status: str
    message: str


class AgentResultSchema(BaseModel):
    agent_name: str
    findings: dict[str, Any]
    confidence: float


class ReportSchema(BaseModel):
    final_report: str
    markdown_report: str
    created_at: str


class ReviewStatusResponse(BaseModel):
    task_id: int
    pr_url: str
    status: str
    created_at: str
    updated_at: str
    results: list[AgentResultSchema] = []
    report: ReportSchema | None = None


class HealthResponse(BaseModel):
    status: str
    version: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _enqueue_review(pr_url: str, db: AsyncSession) -> ReviewTask:
    """Create a pending review task and launch the background orchestrator."""
    task = ReviewTask(pr_url=pr_url, status=TaskStatus.PENDING)
    db.add(task)
    await db.flush()
    await db.refresh(task)
    await set_task_status(task.id, TaskStatus.PENDING.value)
    await db.commit()

    orchestrator = Orchestrator()
    asyncio.create_task(orchestrator.run(task_id=task.id, pr_url=pr_url))
    return task


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.post(
    "/review",
    response_model=ReviewCreateResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Submit a PR for code review",
)
async def create_review(
    payload: ReviewRequest,
    db: AsyncSession = Depends(get_db),
) -> ReviewCreateResponse:
    """
    Accept a Pull Request URL and create a new review task.

    Returns the **task_id** which can be used to poll for results.
    """
    task = await _enqueue_review(str(payload.pr_url), db)

    return ReviewCreateResponse(
        task_id=task.id,
        status=task.status.value,
        message="Review task created. Poll GET /review/{task_id} for updates.",
    )


@app.get(
    "/review/{task_id}",
    response_model=ReviewStatusResponse,
    summary="Get review task status and results",
)
async def get_review(
    task_id: int,
    db: AsyncSession = Depends(get_db),
) -> ReviewStatusResponse:
    """
    Return the current status of a review task.

    Once the task reaches **completed** status the response also includes
    per-agent findings and the aggregated final report.
    """
    stmt = (
        select(ReviewTask)
        .where(ReviewTask.id == task_id)
        .options(
            selectinload(ReviewTask.results),
            selectinload(ReviewTask.report),
        )
    )
    result = await db.execute(stmt)
    task: ReviewTask | None = result.scalar_one_or_none()

    if task is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Review task {task_id} not found.",
        )

    # Prefer Redis for status (fast path); fall back to DB value
    cached_status = await get_task_status(task_id)
    current_status = cached_status if cached_status is not None else task.status.value

    results = [
        AgentResultSchema(
            agent_name=r.agent_name,
            findings=r.findings,
            confidence=r.confidence,
        )
        for r in task.results
    ]

    report_schema: ReportSchema | None = None
    if task.report is not None:
        report_schema = ReportSchema(
            final_report=task.report.final_report,
            markdown_report=task.report.markdown_report,
            created_at=task.report.created_at.isoformat(),
        )

    return ReviewStatusResponse(
        task_id=task.id,
        pr_url=task.pr_url,
        status=current_status,
        created_at=task.created_at.isoformat(),
        updated_at=task.updated_at.isoformat(),
        results=results,
        report=report_schema,
    )


@app.get(
    "/health",
    response_model=HealthResponse,
    summary="Service health check",
)
async def health_check() -> HealthResponse:
    """Return a simple liveness probe response."""
    return HealthResponse(status="ok", version=app.version)


# ---------------------------------------------------------------------------
# GitHub Webhook
# ---------------------------------------------------------------------------

@app.post(
    "/webhook/github",
    summary="Receive GitHub PR events and auto-trigger review",
    status_code=status.HTTP_202_ACCEPTED,
)
async def github_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Handle GitHub ``pull_request`` webhook events.

    Verifies the HMAC-SHA256 signature when GITHUB_WEBHOOK_SECRET is set,
    then triggers a review for ``opened`` and ``synchronize`` actions.
    """
    body = await request.body()

    # --- Signature verification -------------------------------------------
    secret = settings.GITHUB_WEBHOOK_SECRET
    if secret:
        sig_header = request.headers.get("X-Hub-Signature-256", "")
        expected = "sha256=" + hmac.new(
            secret.encode(), body, hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(sig_header, expected):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid signature")

    # --- Parse payload ----------------------------------------------------
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid JSON")

    event = request.headers.get("X-GitHub-Event", "")
    if event != "pull_request":
        return {"ignored": True, "reason": f"event '{event}' not handled"}

    action = payload.get("action", "")
    if action not in {"opened", "synchronize", "reopened"}:
        return {"ignored": True, "reason": f"action '{action}' not handled"}

    pr_url = payload.get("pull_request", {}).get("html_url")
    if not pr_url:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing pull_request.html_url")

    # --- Create review task (reuse same logic as POST /review) ------------
    task = await _enqueue_review(pr_url, db)

    return {"task_id": task.id, "pr_url": pr_url, "status": "queued"}


# ---------------------------------------------------------------------------
# Stats / Dashboard API
# ---------------------------------------------------------------------------

class SeverityCount(BaseModel):
    severity: str
    count: int


class StatsSummaryResponse(BaseModel):
    total_tasks: int
    completed: int
    failed: int
    total_findings: int
    by_severity: list[SeverityCount]


class TrendPoint(BaseModel):
    date: str       # YYYY-MM-DD
    count: int


class TrendResponse(BaseModel):
    tasks: list[TrendPoint]
    findings: list[TrendPoint]


class CategoryCount(BaseModel):
    category: str
    count: int


@app.get(
    "/stats/summary",
    response_model=StatsSummaryResponse,
    summary="Overall review statistics",
)
async def stats_summary(db: AsyncSession = Depends(get_db)) -> StatsSummaryResponse:
    """Return aggregate counts across all review tasks."""
    total = await db.scalar(select(func.count()).select_from(ReviewTask))
    completed = await db.scalar(
        select(func.count()).select_from(ReviewTask).where(ReviewTask.status == TaskStatus.COMPLETED)
    )
    failed = await db.scalar(
        select(func.count()).select_from(ReviewTask).where(ReviewTask.status == TaskStatus.FAILED)
    )

    # Pull all findings from ReviewResult JSON column
    rows = (await db.execute(select(ReviewResult.findings))).scalars().all()
    sev_counts: dict[str, int] = {}
    total_findings = 0
    for row in rows:
        findings_list = row.get("findings", []) if isinstance(row, dict) else []
        for f in findings_list:
            sev = f.get("severity", "UNKNOWN")
            sev_counts[sev] = sev_counts.get(sev, 0) + 1
            total_findings += 1

    by_severity = [
        SeverityCount(severity=sev, count=cnt)
        for sev, cnt in sorted(sev_counts.items())
    ]

    return StatsSummaryResponse(
        total_tasks=total or 0,
        completed=completed or 0,
        failed=failed or 0,
        total_findings=total_findings,
        by_severity=by_severity,
    )


@app.get(
    "/stats/top_categories",
    response_model=list[CategoryCount],
    summary="Top finding categories across all reviews",
)
async def stats_top_categories(
    limit: int = 10,
    db: AsyncSession = Depends(get_db),
) -> list[CategoryCount]:
    """Return the most frequently occurring finding categories."""
    rows = (await db.execute(select(ReviewResult.findings))).scalars().all()
    cat_counts: dict[str, int] = {}
    for row in rows:
        findings_list = row.get("findings", []) if isinstance(row, dict) else []
        for f in findings_list:
            cat = f.get("category", "unknown")
            cat_counts[cat] = cat_counts.get(cat, 0) + 1

    top = sorted(cat_counts.items(), key=lambda x: x[1], reverse=True)[:limit]
    return [CategoryCount(category=cat, count=cnt) for cat, cnt in top]


@app.get(
    "/stats/trends",
    response_model=TrendResponse,
    summary="Daily task and finding counts over past N days",
)
async def stats_trends(
    days: int = 30,
    db: AsyncSession = Depends(get_db),
) -> TrendResponse:
    """Return per-day counts of submitted tasks and total findings."""
    from datetime import datetime, timedelta, timezone
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    task_rows = (
        await db.execute(
            select(
                func.date(ReviewTask.created_at).label("day"),
                func.count().label("cnt"),
            )
            .where(ReviewTask.created_at >= cutoff)
            .group_by(func.date(ReviewTask.created_at))
            .order_by(func.date(ReviewTask.created_at))
        )
    ).all()

    result_rows = (
        await db.execute(
            select(ReviewResult.findings)
            .join(ReviewTask, ReviewTask.id == ReviewResult.task_id)
            .where(ReviewTask.created_at >= cutoff)
        )
    ).scalars().all()

    # Aggregate findings per day requires loading tasks with dates;
    # simplified: return task trend + total findings trend using task dates.
    task_points = [TrendPoint(date=str(r.day), count=r.cnt) for r in task_rows]

    # For findings trend, count per day from ReviewResult join
    day_finding_counts: dict[str, int] = {}
    finding_with_date_rows = (
        await db.execute(
            select(
                func.date(ReviewTask.created_at).label("day"),
                ReviewResult.findings,
            )
            .join(ReviewTask, ReviewTask.id == ReviewResult.task_id)
            .where(ReviewTask.created_at >= cutoff)
        )
    ).all()
    for row in finding_with_date_rows:
        day = str(row.day)
        findings_list = row.findings.get("findings", []) if isinstance(row.findings, dict) else []
        day_finding_counts[day] = day_finding_counts.get(day, 0) + len(findings_list)

    finding_points = [
        TrendPoint(date=day, count=cnt)
        for day, cnt in sorted(day_finding_counts.items())
    ]

    return TrendResponse(tasks=task_points, findings=finding_points)
