"""Consistent copy when the admin panel notifies a worker."""
from __future__ import annotations

import json
from typing import Any, Tuple


def admin_display_name(request_user: Any) -> str:
    if request_user is not None and getattr(request_user, 'name', None):
        name = str(request_user.name).strip()
        if name:
            return name
    return 'NeatNow Admin'


def build_admin_task_assignment_notification(
    *,
    admin_name: str,
    report: Any,
    worker_display_name: str,
) -> Tuple[str, str]:
    """
    Returns (title, message_json) for worker inbox + push.
    """
    report_id = report.report_id
    waste = (getattr(report, 'waste_type', None) or 'waste').strip()
    location_address = (getattr(report, 'location_address', None) or '').strip()
    citizen_name = (
        report.citizen_id.name
        if getattr(report, 'citizen_id', None) is not None
        else 'Admin task'
    )

    title = f'From Admin — Task assigned (Report #{report_id})'
    body = (
        f'{admin_name} assigned Report #{report_id} to you from the admin panel. '
        f'Open Tasks to view location and details.'
    )

    payload = {
        'type': 'task_assignment',
        'from_admin': True,
        'source': 'admin_panel',
        'admin_name': admin_name,
        'report_id': report_id,
        'citizen_name': citizen_name,
        'worker_name': worker_display_name,
        'message': body,
        'body': body,
        'title': title,
        'action_required': True,
        'waste_type': waste,
        'location': getattr(report, 'location', None),
        'location_address': location_address or None,
        'reported_by': 'Assigned by Admin',
    }
    return title, json.dumps(payload)


def build_admin_manual_notification(
    *,
    admin_name: str,
    body: str,
    extra: dict | None = None,
) -> Tuple[str, str]:
    """Admin → worker message via POST /api/workers/{id}/notify/."""
    title = f'From Admin — {admin_name}'
    text = body.strip()
    payload = {
        'type': 'admin_message',
        'from_admin': True,
        'source': 'admin_panel',
        'admin_name': admin_name,
        'message': text,
        'body': text,
        'title': title,
        'reported_by': 'Message from Admin',
        **(extra or {}),
    }
    return title, json.dumps(payload)
