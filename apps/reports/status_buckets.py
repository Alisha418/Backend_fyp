"""Admin/worker report buckets for citizen accept window (60 minutes)."""
from datetime import timedelta

from django.db.models import Q
from django.utils import timezone

ACCEPT_WINDOW_MINUTES = 60


def accept_window_cutoff():
    return timezone.now() - timedelta(minutes=ACCEPT_WINDOW_MINUTES)


def accept_window_elapsed(submitted_at) -> bool:
    if not submitted_at:
        return False
    return submitted_at <= accept_window_cutoff()


def is_citizen_awaiting_accept(report) -> bool:
    return (
        getattr(report, 'report_source', 'citizen') == 'citizen'
        and report.status == 'Pending'
        and report.worker_id is None
        and not accept_window_elapsed(report.submitted_at)
    )


def is_citizen_unassigned_expired(report) -> bool:
    return (
        getattr(report, 'report_source', 'citizen') == 'citizen'
        and report.status == 'Pending'
        and report.worker_id is None
        and accept_window_elapsed(report.submitted_at)
    )


def awaiting_accept_q() -> Q:
    return Q(
        report_source='citizen',
        status='Pending',
        worker_id__isnull=True,
        submitted_at__gt=accept_window_cutoff(),
    )


def unassigned_expired_q() -> Q:
    return Q(
        report_source='citizen',
        status='Pending',
        worker_id__isnull=True,
        submitted_at__lte=accept_window_cutoff(),
    )


def pending_workload_q() -> Q:
    return Q(status='Assigned') | Q(status='Pending', worker_id__isnull=False)
