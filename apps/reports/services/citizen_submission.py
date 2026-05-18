"""
Citizen report submission — single-responsibility helpers for CitizenReportSubmissionView.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Optional, Tuple

from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone
from datetime import timedelta

logger = logging.getLogger(__name__)


def normalize_citizen_temp_id(raw: Any) -> Optional[str]:
    """Return a non-empty client temp id or None."""
    if raw is None:
        return None
    s = str(raw).strip()
    if not s or len(s) > 64:
        return None
    return s


def is_citizen_user(user) -> bool:
    return getattr(user, 'role', None) == 'Citizen'


def parse_coordinate_pair(latitude: Any, longitude: Any) -> Tuple[float, float]:
    """Parse lat/lng; raises ValueError on invalid input."""
    lat = float(latitude)
    lng = float(longitude)
    if not (-90 <= lat <= 90):
        raise ValueError('latitude out of range')
    if not (-180 <= lng <= 180):
        raise ValueError('longitude out of range')
    return lat, lng


def validate_multipart_presence(image_before, latitude: Any, longitude: Any) -> Optional[str]:
    """Return error message string or None if OK."""
    if not image_before:
        return 'Image is required'
    if latitude is None or longitude is None or latitude == '' or longitude == '':
        return 'GPS coordinates (latitude and longitude) are required'
    return None


def find_existing_by_temp_id(user, citizen_temp_id: Optional[str]):
    """Idempotent sync: return existing report for same citizen + temp id."""
    if not citizen_temp_id:
        return None
    from apps.reports.models import Report

    return Report.objects.filter(
        citizen_id=user,
        citizen_temp_id=citizen_temp_id,
    ).first()


def run_waste_detection(image_before):
    """
    Run ML on image file-like object; returns detector dict.

    Uses waste_detector.evaluate_waste_pass (strong 20% OR mixed 20% / 2+ types).
    Prefer verify_waste_image_file() for pass/fail + messages (admin & citizen).
    """
    from apps.reports.waste_detector import detect_waste

    return detect_waste(image_before)


def ml_result_is_rejected_waste(ml_result: dict) -> Tuple[bool, str]:
    """
    Returns (should_reject, reason_key) where reason_key is 'no_waste', 'unverified', or ''.
    """
    ai = ml_result.get('ai_result', 'Unverified')
    if ai == 'No Waste':
        return True, 'no_waste'
    if ai == 'Unverified':
        return True, 'unverified'
    return False, ''

def _get_citizen_badges_top3() -> Tuple[dict[int, str], dict[int, int]]:
    """
    Returns:
      - badge_by_citizen_id: {account_id: 'platinum'|'gold'|'silver'}
      - rank_by_citizen_id:  {account_id: 1|2|3}
    """
    from django.db.models import Count

    from apps.accounts.models import Account

    citizens = (
        Account.objects.filter(role='Citizen', is_active=True)
        .annotate(
            report_count=Count(
                'submitted_reports',
                filter=Q(submitted_reports__report_source='citizen'),
            ),
        )
        .filter(report_count__gt=0)
        .order_by('-report_count')
    )

    badge_map: dict[int, str] = {}
    rank_map: dict[int, int] = {}
    badge_by_rank = {1: 'platinum', 2: 'gold', 3: 'silver'}

    for rank, citizen in enumerate(list(citizens[:3]), start=1):
        badge = badge_by_rank.get(rank)
        if badge:
            badge_map[int(citizen.account_id)] = badge
            rank_map[int(citizen.account_id)] = rank

    return badge_map, rank_map


def _badge_score(badge: Optional[str]) -> int:
    if badge == 'platinum':
        return 3
    if badge == 'gold':
        return 2
    if badge == 'silver':
        return 1
    return 0


def _notify_citizens_badge_changes(
    *,
    old_badges: dict[int, str],
    new_badges: dict[int, str],
    new_report_id: int,
) -> None:
    """
    Create notifications for any citizen whose leaderboard badge changes.
    This supports both upgrades (e.g. silver -> gold) and downgrades
    (e.g. gold -> silver).
    """
    from apps.notifications.models import Notification, RecipientType

    affected_citizens = set(old_badges.keys()) | set(new_badges.keys())
    now = timezone.now()

    badge_title = {
        'platinum': 'Platinum Badge',
        'gold': 'Gold Badge',
        'silver': 'Silver Badge',
    }

    for account_id in affected_citizens:
        old_badge = old_badges.get(account_id)
        new_badge = new_badges.get(account_id)
        if old_badge == new_badge:
            continue

        old_score = _badge_score(old_badge)
        new_score = _badge_score(new_badge)

        # When moving up ranks => rank_up, otherwise => achievement
        backend_type = 'rank_up' if new_score > old_score else 'achievement'

        if new_badge is not None:
            title = badge_title.get(new_badge, 'Badge Update')
            if backend_type == 'rank_up':
                message = f'You have achieved the {new_badge} badge.'
            else:
                message = f'Your badge has changed from {old_badge} to {new_badge}.'
        else:
            title = 'Badge Update'
            message = f'Your badge has changed from {old_badge} to no badge.'

        Notification.objects.create(
            recipient_type=RecipientType.CITIZEN,
            recipient_id=account_id,
            message=json.dumps({
                'type': backend_type,  # must match Flutter mapping: rank_up / achievement
                'title': title,
                'message': message,
                'badge': new_badge,
                'old_badge': old_badge,
                'report_id': new_report_id,
                'updated_at': now.isoformat(),
            }),
            is_read=False,
        )


def create_report_from_ml(
    user,
    *,
    latitude: float,
    longitude: float,
    waste_type: str,
    image_before,
    ml_result: dict,
    citizen_temp_id: Optional[str],
    location_address: Optional[str] = None,
):
    """Persist Report after ML confirmed waste."""
    from apps.reports.models import Report

    from apps.reports.services.ai_categories import extract_ai_categories_from_ml

    detected_waste_type = ml_result.get('waste_type')
    ai_confidence = ml_result.get('ai_confidence', 0.0)
    final_waste_type = detected_waste_type if detected_waste_type else (waste_type or None)
    ai_categories = extract_ai_categories_from_ml(ml_result)

    addr = (location_address or '').strip()[:2000] or None

    image_before.seek(0)
    return Report.objects.create(
        citizen_id=user,
        report_source='citizen',
        citizen_temp_id=citizen_temp_id,
        is_synced=True,
        waste_type=final_waste_type,
        latitude=latitude,
        longitude=longitude,
        location_address=addr,
        image_before=image_before,
        status='Pending',
        ai_result='Waste',
        ai_confidence=ai_confidence,
        ai_categories=ai_categories,
    )


def create_report_from_ml_safe(
    user,
    *,
    latitude: float,
    longitude: float,
    waste_type: str,
    image_before,
    ml_result: dict,
    citizen_temp_id: Optional[str],
    location_address: Optional[str] = None,
) -> Tuple[Any, bool]:
    """
    Create report; on duplicate temp id (race), return existing row.
    Second value is True only if a new row was inserted (notify workers then).
    """
    from apps.reports.models import Report

    # Snapshot leaderboard badges BEFORE inserting this report.
    old_badges, _ = _get_citizen_badges_top3()

    try:
        with transaction.atomic():
            report = create_report_from_ml(
                user,
                latitude=latitude,
                longitude=longitude,
                waste_type=waste_type,
                image_before=image_before,
                ml_result=ml_result,
                citizen_temp_id=citizen_temp_id,
                location_address=location_address,
            )
            # Create badge-change notifications only when a new row is inserted.
            new_badges, _ = _get_citizen_badges_top3()
            _notify_citizens_badge_changes(
                old_badges=old_badges,
                new_badges=new_badges,
                new_report_id=int(report.report_id),
            )
            return report, True
    except IntegrityError:
        logger.info(
            'Duplicate citizen_temp_id for citizen, returning existing: %s',
            citizen_temp_id,
        )
        if citizen_temp_id:
            existing = Report.objects.filter(
                citizen_id=user,
                citizen_temp_id=citizen_temp_id,
            ).first()
            if existing:
                return existing, False
        raise


def notify_workers_for_report(report, user) -> None:
    """Push worker notifications when a new waste report is created."""
    if report.ai_result != 'Waste':
        return

    from apps.workers.models import Worker
    from apps.notifications.models import Notification, RecipientType
    from apps.admins.models import Admin

    active_workers = list(
        Worker.objects.filter(
            worker_id__is_active=True,
        ).select_related('worker_id')
    )

    expires_at_time = timezone.now() + timedelta(minutes=60)
    addr = (report.location_address or '').strip() or None
    notification_title = f'New Task Assignment - Report #{report.report_id}'

    for worker in active_workers:
        worker_name = (worker.worker_id.name or '').strip() or 'Worker'
        notification_message = json.dumps({
            'type': 'report_available',
            'report_id': report.report_id,
            'citizen_name': user.name,
            'worker_name': worker_name,
            'message': f'New report #{report.report_id} submitted by {user.name}',
            'expires_at': expires_at_time.isoformat(),
            'action_required': True,
            'location': report.location,
            'location_address': addr,
            'waste_type': report.waste_type,
            'latitude': str(report.latitude) if report.latitude is not None else None,
            'longitude': str(report.longitude) if report.longitude is not None else None,
        })
        Notification.objects.create(
            recipient_type=RecipientType.WORKER,
            recipient_id=worker.worker_id.account_id,
            message=notification_message,
            is_read=False,
            title=notification_title,
            status='pending',
            expires_at=expires_at_time,
            report_id=report.report_id,
        )

    # One admin-facing row per report (not one per worker).
    workers_notified = len(active_workers)
    admin_message = json.dumps({
        'type': 'citizen_report_pending',
        'report_id': report.report_id,
        'citizen_name': user.name,
        'waste_type': report.waste_type,
        'workers_notified_count': workers_notified,
        'message': (
            f'{user.name} submitted report #{report.report_id} ({report.waste_type}). '
            f'Waiting for a worker to accept.'
        ),
    })
    admin_title = f'New report pending — #{report.report_id}'
    for admin in Admin.objects.filter(is_active=True):
        Notification.objects.create(
            recipient_type=RecipientType.ADMIN,
            recipient_id=admin.admin_id,
            message=admin_message,
            is_read=False,
            title=admin_title,
            status='pending',
            expires_at=None,
            report_id=report.report_id,
        )


def build_submission_success_payload(
    report,
    serializer,
    *,
    message: str,
    final_waste_type: Any,
    ai_confidence: float,
) -> dict:
    """Uniform success body for POST /api/reports/submit/."""
    return {
        'success': True,
        'message': message,
        'data': serializer.data,
        'ai_result': 'Waste',
        'ai_confidence': float(ai_confidence),
        'waste_type': final_waste_type,
    }
