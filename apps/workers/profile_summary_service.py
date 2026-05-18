from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Dict, Any

from django.db.models import Avg, Q

from apps.feedback.models import Feedback
from apps.reports.models import Report
from .models import Worker, WorkerMonthlyStats
from .badge_history_service import get_current_badge


@dataclass(frozen=True)
class WorkerSummary:
    worker: Worker
    rating: float
    completed_tasks: int
    pending_tasks: int
    total_tasks: int
    completion_rate: float


def get_worker_for_user(user) -> Optional[Worker]:
    """Return worker profile for authenticated account, else None."""
    try:
        return Worker.objects.select_related("worker_id").get(worker_id=user)
    except Worker.DoesNotExist:
        return None


def _build_profile_image_url(worker: Worker, request) -> Optional[str]:
    from apps.accounts.media_url import build_media_file_url

    return build_media_file_url(worker.worker_id.profile_image, request)


def compute_worker_summary(worker: Worker) -> WorkerSummary:
    """Compute worker profile stats for profile header/stats cards."""
    reports = Report.objects.filter(worker_id=worker)
    completed_tasks = reports.filter(status="Resolved").count()
    pending_tasks = reports.filter(Q(status="Pending") | Q(status="Assigned")).count()
    total_tasks = reports.count()
    completion_rate = round((completed_tasks / total_tasks), 4) if total_tasks > 0 else 0.0

    rating_value = (
        Feedback.objects.filter(worker_id=worker).aggregate(avg=Avg("rating"))["avg"]
        or worker.avg_rating
        or 0.0
    )
    rating = round(float(rating_value), 2)

    return WorkerSummary(
        worker=worker,
        rating=rating,
        completed_tasks=completed_tasks,
        pending_tasks=pending_tasks,
        total_tasks=total_tasks,
        completion_rate=completion_rate,
    )


def build_profile_summary_payload(worker: Worker, request) -> Dict[str, Any]:
    """Serialize profile + stats payload for mobile profile screen."""
    summary = compute_worker_summary(worker)
    account = worker.worker_id
    latest_monthly = (
        WorkerMonthlyStats.objects.filter(worker_id=worker).order_by("-month").first()
    )
    current_badge = get_current_badge(worker)
    normalized_badge = _normalize_worker_badge(
        current_badge if current_badge is not None else (latest_monthly.badge if latest_monthly else None)
    )

    return {
        "profile": {
            "id": str(account.account_id),
            "name": account.name or "",
            "email": account.email or "",
            "phone": account.phone_number or "",
            "employeeId": worker.employee_code or str(account.account_id),
            "profileImage": _build_profile_image_url(worker, request),
            "badge": normalized_badge,
        },
        "stats": {
            "rating": summary.rating,
            "completedTasks": summary.completed_tasks,
            "pendingTasks": summary.pending_tasks,
            "totalTasks": summary.total_tasks,
            "completionRate": summary.completion_rate,
        },
    }


def _normalize_worker_badge(raw_badge: Optional[str]) -> Optional[str]:
    """
    Normalize backend badge to one of: Diamond, Gold, Silver, Bronze.
    Return None when badge is absent or unsupported.
    """
    if not raw_badge:
        return None

    normalized = raw_badge.strip().lower()
    mapping = {
        "diamond": "Diamond",
        "gold": "Gold",
        "silver": "Silver",
        "bronze": "Bronze",
    }
    return mapping.get(normalized)
