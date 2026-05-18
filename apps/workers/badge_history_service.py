from __future__ import annotations

from typing import Dict, Any, List, Optional

from django.db import transaction
from django.db.models import Avg
from django.utils import timezone

from apps.feedback.models import Feedback
from apps.reports.models import Report
from .models import Worker, WorkerBadgeHistory


def calculate_rankings_snapshot(request=None) -> List[Dict[str, Any]]:
    """
    Live leaderboard: sort by resolved_tasks (desc), then avg_rating, then points.
    Ranks and badges apply ONLY to workers with resolved_tasks > 0.
    Tie-break: same resolved count → higher avg_rating ranks higher; same resolved + same rating → same rank & same badge.
    Badge tiers by dense rank among eligible only: 1=Diamond, 2=Gold, 3=Silver, 4+=Bronze.
    Workers with zero resolved tasks get rank=None and badge=None (still listed at the end for the All list).
    """
    workers = Worker.objects.select_related("worker_id").all()
    rankings_data: List[Dict[str, Any]] = []

    for worker in workers:
        lifetime_tasks = Report.objects.filter(worker_id=worker, status="Resolved").count()

        if worker.total_tasks != lifetime_tasks:
            worker.total_tasks = lifetime_tasks
            worker.save(update_fields=["total_tasks"])

        avg_rating = Feedback.objects.filter(worker_id=worker).aggregate(Avg("rating"))["rating__avg"]
        worker_avg_rating = float(avg_rating) if avg_rating else float(worker.avg_rating or 0.0)
        points = lifetime_tasks * 5

        profile_image_url = None
        if request is not None and worker.worker_id.profile_image:
            from apps.accounts.media_url import build_media_file_url

            profile_image_url = build_media_file_url(worker.worker_id.profile_image, request)

        rankings_data.append(
            {
                "worker": worker,
                "worker_id": worker.worker_id.account_id,
                "employee_code": worker.employee_code,
                "name": worker.worker_id.name,
                "profile_image": profile_image_url,
                "points": points,
                "resolved_tasks": lifetime_tasks,
                "avg_rating": worker_avg_rating,
            }
        )

    rankings_data.sort(key=lambda x: (-x["resolved_tasks"], -x["avg_rating"], -x["points"]))

    eligible = [e for e in rankings_data if int(e.get("resolved_tasks") or 0) > 0]
    ineligible = [e for e in rankings_data if int(e.get("resolved_tasks") or 0) <= 0]

    current_rank = None
    previous_key = None
    for index, entry in enumerate(eligible, start=1):
        rank_key = (
            entry["resolved_tasks"],
            round(float(entry["avg_rating"]), 3),
            entry["points"],
        )
        if previous_key is not None and rank_key == previous_key:
            entry["rank"] = current_rank
        else:
            entry["rank"] = index
            current_rank = index
            previous_key = rank_key
        entry["badge"] = _compute_badge(
            rank=int(entry["rank"]),
            resolved=int(entry.get("resolved_tasks") or 0),
        )

    for entry in ineligible:
        entry["rank"] = None
        entry["badge"] = None

    rankings_data.clear()
    rankings_data.extend(eligible)
    ineligible.sort(key=lambda x: (x.get("name") or "").lower())
    rankings_data.extend(ineligible)

    return rankings_data


def _compute_badge(rank: int, resolved: int) -> Optional[str]:
    """Badge from relative rank among workers with at least one resolved report (no fixed rating cutoffs)."""
    if resolved <= 0:
        return None
    if rank == 1:
        return "Diamond"
    if rank == 2:
        return "Gold"
    if rank == 3:
        return "Silver"
    return "Bronze"


@transaction.atomic
def sync_badge_history_from_rankings(rankings_data: List[Dict[str, Any]], as_of=None) -> None:
    """Persist badge transitions with started/ended timestamps."""
    now = as_of or timezone.now()

    for entry in rankings_data:
        worker: Worker = entry["worker"]
        new_badge = entry.get("badge")

        current = (
            WorkerBadgeHistory.objects.select_for_update()
            .filter(worker_id=worker, is_current=True)
            .order_by("-started_at")
            .first()
        )
        current_badge = current.badge if current else None

        if current_badge == new_badge:
            continue

        if current is not None:
            current.is_current = False
            current.ended_at = now
            current.save(update_fields=["is_current", "ended_at"])

        if new_badge:
            WorkerBadgeHistory.objects.create(
                worker_id=worker,
                badge=new_badge,
                is_current=True,
            )


def get_current_badge(worker: Worker) -> Optional[str]:
    row = (
        WorkerBadgeHistory.objects.filter(worker_id=worker, is_current=True)
        .order_by("-started_at")
        .first()
    )
    return row.badge if row else None
