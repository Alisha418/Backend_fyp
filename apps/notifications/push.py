"""
FCM push delivery for in-app notification rows (worker & citizen).
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, Optional

from django.utils import timezone

logger = logging.getLogger(__name__)


def _ensure_firebase_initialized() -> bool:
    try:
        import firebase_admin
        from firebase_admin import credentials as firebase_credentials
    except ModuleNotFoundError:
        logger.warning('firebase-admin not installed; push skipped')
        return False

    if firebase_admin._apps:
        return True

    service_account_json = (os.getenv('FIREBASE_SERVICE_ACCOUNT_JSON') or '').strip()
    try:
        if service_account_json:
            cred = firebase_credentials.Certificate(json.loads(service_account_json))
            firebase_admin.initialize_app(cred)
        else:
            firebase_admin.initialize_app()
        return True
    except Exception as exc:
        logger.warning('Firebase Admin init failed (push skipped): %s', exc)
        return False


def _parse_message_data(notification) -> dict:
    try:
        if notification.message:
            return json.loads(notification.message)
    except (json.JSONDecodeError, TypeError, AttributeError):
        pass
    return {}


def _notification_title_body(notification) -> tuple[str, str]:
    message_data = _parse_message_data(notification)
    title = (getattr(notification, 'title', None) or '').strip()
    if not title:
        title = (
            message_data.get('title')
            or message_data.get('message')
            or 'Notification'
        )
    body = (
        message_data.get('body')
        or message_data.get('message')
        or title
    )
    if isinstance(body, dict):
        body = title
    body = str(body).strip() or str(title)
    return str(title), body


def _android_channel_for_type(notification_type: str) -> str:
    t = (notification_type or '').lower()
    if t in ('urgent', 'urgent_task'):
        return 'urgent_notifications'
    if t in (
        'task_assignment',
        'report_available',
        'report_assigned',
        'proximity_task',
        'work_started',
        'work_completed',
        'feedback',
        'admin_message',
    ):
        return 'task_notifications'
    return 'general_notifications'


def send_push_for_notification(notification) -> bool:
    """
    Send FCM to the account matching notification.recipient_id.
    Returns True if a message was sent successfully.
    """
    from apps.accounts.models import Account
    from .models import RecipientType

    recipient_type = getattr(notification, 'recipient_type', None)
    recipient_id = getattr(notification, 'recipient_id', None)
    if not recipient_id:
        return False

    if recipient_type not in (RecipientType.WORKER, RecipientType.CITIZEN):
        return False

    try:
        account = Account.objects.get(account_id=recipient_id)
    except Account.DoesNotExist:
        logger.warning('FCM: account %s not found', recipient_id)
        return False

    token = (account.fcm_token or '').strip()
    if not token:
        return False

    if not _ensure_firebase_initialized():
        return False

    try:
        from firebase_admin import messaging
    except ModuleNotFoundError:
        return False

    message_data = _parse_message_data(notification)
    title, body = _notification_title_body(notification)
    ntype = str(message_data.get('type') or 'general')

    data: Dict[str, str] = {
        'notification_id': str(getattr(notification, 'notification_id', '')),
        'recipient_type': str(recipient_type),
        'type': ntype,
        'title': title,
        'body': body,
    }
    if notification.report_id:
        data['report_id'] = str(notification.report_id)
    for key in ('report_id', 'task_id', 'status', 'from_admin', 'source'):
        if key in message_data and message_data[key] is not None:
            data[key] = str(message_data[key])

    channel_id = _android_channel_for_type(ntype)

    try:
        message = messaging.Message(
            notification=messaging.Notification(title=title, body=body),
            data=data,
            token=token,
            android=messaging.AndroidConfig(
                priority='high',
                notification=messaging.AndroidNotification(
                    channel_id=channel_id,
                    priority='high',
                ),
            ),
        )
        response = messaging.send(message)
        logger.info(
            'FCM push sent notification_id=%s account=%s response=%s',
            getattr(notification, 'notification_id', '?'),
            recipient_id,
            response,
        )
        return True
    except Exception as exc:
        err = str(exc).lower()
        if 'not-found' in err or 'registration-token-not-registered' in err:
            Account.objects.filter(account_id=account.account_id).update(
                fcm_token=None,
                fcm_token_updated_at=timezone.now(),
            )
            logger.info('Cleared invalid FCM token for account %s', account.account_id)
        else:
            logger.warning('FCM push failed for account %s: %s', account.account_id, exc)
        return False


def send_push_to_account(
    account_id: int,
    title: str,
    body: str,
    data: Optional[Dict[str, Any]] = None,
) -> bool:
    """Send a push directly to an account (e.g. admin manual notify)."""
    from apps.accounts.models import Account

    try:
        account = Account.objects.get(account_id=account_id)
    except Account.DoesNotExist:
        return False

    token = (account.fcm_token or '').strip()
    if not token or not _ensure_firebase_initialized():
        return False

    try:
        from firebase_admin import messaging
    except ModuleNotFoundError:
        return False

    payload = {str(k): str(v) for k, v in (data or {}).items()}
    payload.setdefault('title', title)
    payload.setdefault('body', body)
    ntype = payload.get('type', 'general')
    channel_id = _android_channel_for_type(ntype)

    try:
        messaging.send(
            messaging.Message(
                notification=messaging.Notification(title=title, body=body),
                data=payload,
                token=token,
                android=messaging.AndroidConfig(
                    priority='high',
                    notification=messaging.AndroidNotification(
                        channel_id=channel_id,
                        priority='high',
                    ),
                ),
            )
        )
        return True
    except Exception as exc:
        logger.warning('FCM direct push failed account %s: %s', account_id, exc)
        return False
