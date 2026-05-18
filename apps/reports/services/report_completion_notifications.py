"""Notify the correct party when a worker updates an admin vs citizen report."""
from __future__ import annotations

import json
import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)


def is_admin_sourced_report(report) -> bool:
    if getattr(report, 'report_source', 'citizen') == 'admin':
        return True
    if getattr(report, 'created_by_admin_id', None):
        return True
    return False


def is_real_citizen_report(report) -> bool:
    if is_admin_sourced_report(report):
        return False
    cid = getattr(report, 'citizen_id_id', None)
    if not cid:
        return False
    # Legacy placeholder account used before admin-sourced migration.
    if int(cid) == 1:
        return False
    return True


def _worker_display_name(worker) -> str:
    if worker and getattr(worker, 'worker_id', None):
        return (worker.worker_id.name or '').strip() or 'Worker'
    return 'Worker'


def notify_work_started(report, worker) -> None:
    from apps.notifications.models import Notification, RecipientType

    worker_name = _worker_display_name(worker)
    waste_label = (report.waste_type or '').strip() or 'waste'

    if is_real_citizen_report(report):
        citizen = report.citizen_id
        citizen_name = (citizen.name or '').strip() or 'Citizen'
        Notification.objects.create(
            recipient_type=RecipientType.CITIZEN,
            recipient_id=citizen.account_id,
            title='Work Started',
            report_id=report.report_id,
            message=json.dumps({
                'type': 'work_started',
                'title': 'Work Started',
                'report_id': report.report_id,
                'citizen_name': citizen_name,
                'worker_name': worker_name,
                'waste_type': waste_label,
                'message': (
                    f'{citizen_name}, {worker_name} started work on your '
                    f'Report #{report.report_id} ({waste_label}).'
                ),
                'status': 'In Progress',
            }),
            is_read=False,
        )
        return

    if is_admin_sourced_report(report):
        admin = getattr(report, 'created_by_admin', None)
        if not admin:
            return
        admin_name = (admin.name or '').strip() or 'Admin'
        Notification.objects.create(
            recipient_type=RecipientType.ADMIN,
            recipient_id=admin.admin_id,
            title='Work Started',
            report_id=report.report_id,
            message=json.dumps({
                'type': 'work_started',
                'title': 'Work Started',
                'report_id': report.report_id,
                'admin_name': admin_name,
                'worker_name': worker_name,
                'waste_type': waste_label,
                'report_source': 'admin',
                'from_admin': True,
                'message': (
                    f'{worker_name} started work on your admin task '
                    f'#{report.report_id} ({waste_label}).'
                ),
                'status': 'In Progress',
            }),
            is_read=False,
        )


def notify_work_completed(report, worker) -> None:
    from apps.notifications.models import Notification, RecipientType

    worker_name = _worker_display_name(worker)
    waste_label = (report.waste_type or '').strip() or 'waste'

    if is_admin_sourced_report(report):
        admin = getattr(report, 'created_by_admin', None)
        if not admin:
            logger.warning(
                'Admin-sourced report %s has no created_by_admin; skip completion notify',
                report.report_id,
            )
            return
        admin_name = (admin.name or '').strip() or 'Admin'
        Notification.objects.create(
            recipient_type=RecipientType.ADMIN,
            recipient_id=admin.admin_id,
            title='Task Completed',
            report_id=report.report_id,
            message=json.dumps({
                'type': 'work_completed',
                'title': 'Task Completed',
                'report_id': report.report_id,
                'admin_name': admin_name,
                'worker_name': worker_name,
                'waste_type': waste_label,
                'report_source': 'admin',
                'from_admin': True,
                'message': (
                    f'Your admin task #{report.report_id} ({waste_label}) '
                    f'was completed by {worker_name}.'
                ),
                'status': 'Resolved',
            }),
            is_read=False,
        )
        return

    if is_real_citizen_report(report):
        citizen = report.citizen_id
        citizen_name = (citizen.name or '').strip() or 'Citizen'
        Notification.objects.create(
            recipient_type=RecipientType.CITIZEN,
            recipient_id=citizen.account_id,
            title='Work Completed',
            report_id=report.report_id,
            message=json.dumps({
                'type': 'work_completed',
                'title': 'Work Completed',
                'report_id': report.report_id,
                'citizen_name': citizen_name,
                'worker_name': worker_name,
                'waste_type': waste_label,
                'message': (
                    f'{citizen_name}, your Report #{report.report_id} ({waste_label}) '
                    f'was completed by {worker_name}.'
                ),
                'status': 'Resolved',
            }),
            is_read=False,
        )
