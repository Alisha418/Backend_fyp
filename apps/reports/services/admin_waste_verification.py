"""
Admin task creation — YOLO waste verification (best.pt) before saving reports.
"""
from __future__ import annotations

import io
import logging
import os
from typing import Any, Dict, Optional, Tuple

from django.conf import settings
from django.core.files.uploadedfile import InMemoryUploadedFile

from apps.reports.services.citizen_submission import (
    ml_result_is_rejected_waste,
    run_waste_detection,
)

logger = logging.getLogger(__name__)

# In-memory cache: (report_id, image mtime) -> verification payload
_report_verify_cache: Dict[tuple, Dict[str, Any]] = {}


def _group_detections_by_class(detections: list) -> list[dict]:
    """One entry per waste category (class), with best confidence and region count."""
    grouped: dict[str, dict] = {}
    for d in detections or []:
        cls = (d.get('class') or 'Unknown').strip()
        conf = float(d.get('confidence') or 0.0)
        if cls not in grouped:
            grouped[cls] = {
                'class': cls,
                'confidence': conf,
                'region_count': 1,
            }
        else:
            grouped[cls]['region_count'] += 1
            grouped[cls]['confidence'] = max(grouped[cls]['confidence'], conf)
    return sorted(grouped.values(), key=lambda x: float(x['confidence']), reverse=True)


def buffer_uploaded_image(image_file):
    """
    Read multipart upload into memory once so YOLO + ImageField save see the same bytes.
    Fixes empty/corrupt reads when the stream was already consumed.
    """
    if image_file is None:
        return None
    if not hasattr(image_file, 'read'):
        return image_file
    image_file.seek(0)
    raw = image_file.read()
    image_file.seek(0)
    if not raw:
        return image_file
    buf = io.BytesIO(raw)
    name = getattr(image_file, 'name', None) or 'image.jpg'
    content_type = getattr(image_file, 'content_type', None) or 'image/jpeg'
    return InMemoryUploadedFile(
        buf,
        getattr(image_file, 'field_name', None),
        name,
        content_type,
        len(raw),
        getattr(image_file, 'charset', None),
    )


def rejection_kind_for_ml(reason: str, ml_result: dict) -> str:
    """Citizen UI hint: no_waste | low_confidence | unverified."""
    if reason == 'unverified':
        return 'unverified'
    if reason != 'no_waste':
        return 'no_waste'
    peak = float(ml_result.get('peak_confidence') or ml_result.get('ai_confidence') or 0.0)
    if ml_result.get('below_threshold') and peak > 0:
        return 'low_confidence'
    return 'no_waste'


def _user_message_for_rejection(reason: str, ml_result: dict) -> str:
    if reason == 'no_waste':
        conf = float(ml_result.get('ai_confidence') or ml_result.get('peak_confidence') or 0.0)
        min_req = float(ml_result.get('min_confidence_required') or 0.20)
        min_pct = int(round(min_req * 100))
        peak_pct = int(round(conf * 100))

        if ml_result.get('below_threshold') and conf > 0:
            return (
                f'Possible waste was found, but confidence is too low ({peak_pct}%). '
                f'At least {min_pct}% is required. Please move closer and take a clearer photo '
                f'with the waste fully in frame.'
            )
        if conf > 0:
            return (
                f'Waste was not verified ({peak_pct}% confidence). '
                f'Please retake the photo with clearer lighting and the waste centered in view.'
            )
        return (
            'No waste was detected in this image. '
            'Please make sure litter or waste is clearly visible, then try again.'
        )
    if reason == 'unverified':
        err = ml_result.get('error') or 'Model could not verify the image'
        return f'AI verification is unavailable: {err}. Task was not saved.'
    return 'AI verification failed. Task was not saved.'


def format_ai_verification_block(ml_result: dict, *, passed: bool) -> Dict[str, Any]:
    """Structured payload for admin UI dialogs."""
    detections = ml_result.get('detections') or []
    valid = ml_result.get('valid_detections') or []
    min_req = float(ml_result.get('min_confidence_required') or 0.20)
    mixed_req = float(ml_result.get('mixed_min_confidence_required') or 0.20)
    conf = float(ml_result.get('ai_confidence') or 0.0)
    peak = float(ml_result.get('peak_confidence') or conf)
    model_classes = set(ml_result.get('model_class_names') or [])
    if model_classes:
        detections = [d for d in detections if (d.get('class') or '').strip() in model_classes]
    categories = _group_detections_by_class(detections)
    pass_mode = ml_result.get('pass_mode')
    return {
        'passed': passed,
        'ai_result': ml_result.get('ai_result', 'Unverified'),
        'ai_confidence': conf,
        'peak_confidence': peak,
        'min_confidence_required': min_req,
        'min_confidence_percent': int(round(min_req * 100)),
        'mixed_min_confidence_required': mixed_req,
        'mixed_min_confidence_percent': int(round(mixed_req * 100)),
        'pass_mode': pass_mode,
        'pass_reason': ml_result.get('pass_reason') or '',
        'is_mixed_waste': bool(ml_result.get('is_mixed_waste')),
        'model_class_names': list(ml_result.get('model_class_names') or []),
        'waste_type': ml_result.get('waste_type'),
        'detection_count': len(detections),
        'valid_detection_count': len(valid),
        'below_threshold': bool(ml_result.get('below_threshold')),
        'waste_categories': [
            {
                'class': c['class'],
                'confidence': round(float(c['confidence']), 3),
                'region_count': int(c['region_count']),
                'meets_strong': float(c['confidence']) >= min_req,
                'meets_mixed': float(c['confidence']) >= mixed_req,
            }
            for c in categories
        ],
        'top_detections': [
            {
                'class': c['class'],
                'confidence': round(float(c['confidence']), 3),
            }
            for c in categories
        ],
        'detection_boxes': [
            {
                'class': d.get('class'),
                'confidence': round(float(d.get('confidence', 0)), 3),
                'bbox': d.get('bbox'),
                'meets_threshold': float(d.get('confidence', 0)) >= min_req
                or float(d.get('confidence', 0)) >= mixed_req,
                'meets_strong': float(d.get('confidence', 0)) >= min_req,
                'meets_mixed': float(d.get('confidence', 0)) >= mixed_req,
            }
            for d in sorted(
                detections,
                key=lambda x: float(x.get('confidence', 0)),
                reverse=True,
            )
            if d.get('bbox')
        ],
        'image_width': ml_result.get('image_width'),
        'image_height': ml_result.get('image_height'),
    }


def _package_ml_verification(
    ml_result: dict,
    *,
    cached: bool = False,
) -> Dict[str, Any]:
    rejected, reason = ml_result_is_rejected_waste(ml_result)
    passed = not rejected
    block = format_ai_verification_block(ml_result, passed=passed)

    if passed:
        wt = ml_result.get('waste_type') or 'waste'
        conf = float(ml_result.get('ai_confidence') or 0.0)
        reason = ml_result.get('pass_reason') or ''
        if ml_result.get('pass_mode') == 'mixed':
            msg = f'Mixed waste detected: {wt} (avg {conf:.0%} across qualifying types).'
        else:
            msg = f'Waste detected: {wt} ({conf:.0%} confidence).'
        if reason:
            msg = f'{msg} {reason}'
        return {
            'passed': True,
            'ml_result': ml_result,
            'ai_verification': block,
            'message': msg.strip(),
            'cached': cached,
        }

    return {
        'passed': False,
        'ml_result': ml_result,
        'ai_verification': block,
        'message': _user_message_for_rejection(reason, ml_result),
        'reason': reason or 'rejected',
        'cached': cached,
    }


def verify_waste_image_file(image_file) -> Dict[str, Any]:
    """
    Shared YOLO verification for admin create-task, citizen capture, and citizen submit.

  Pass rules (see waste_detector.evaluate_waste_pass):
      - Strong: any detection >= 20%
      - Mixed: >=2 categories each >= 20% (class max) and >=2 boxes total

    Returns dict with keys: passed, ml_result, ai_verification, message.
    Does not persist anything.
    """
    if image_file is None:
        return {
            'passed': False,
            'ml_result': {'ai_result': 'Unverified', 'ai_confidence': 0.0},
            'message': 'Image is required for AI verification',
            'reason': 'missing_image',
        }

    buffered = buffer_uploaded_image(image_file)
    ml_result = run_waste_detection(buffered)

    if hasattr(buffered, 'seek'):
        buffered.seek(0)

    return _package_ml_verification(ml_result)


# Backwards-compatible aliases (admin + citizen use the same logic).
verify_admin_task_image = verify_waste_image_file
verify_citizen_waste_image = verify_waste_image_file


def verify_report_image(report) -> Dict[str, Any]:
    """
    Run YOLO on an existing report's image_before (no re-upload from browser).
    Uses server-local file path when available — much faster for Report Details.
    """
    if not report.image_before:
        return {
            'passed': False,
            'ml_result': {'ai_result': 'Unverified', 'ai_confidence': 0.0},
            'message': 'Report has no before image',
            'reason': 'missing_image',
        }

    cache_key = None
    local_path = None

    try:
        candidate = report.image_before.path
        if os.path.isfile(candidate):
            local_path = candidate
            cache_key = (report.report_id, os.path.getmtime(candidate))
    except (ValueError, NotImplementedError, AttributeError):
        local_path = None

    use_cache = getattr(settings, 'WASTE_VERIFY_CACHE', True)
    if use_cache and cache_key and cache_key in _report_verify_cache:
        logger.info('AI verify cache hit for report %s', report.report_id)
        return _report_verify_cache[cache_key]

    if local_path:
        ml_result = run_waste_detection(local_path)
    else:
        with report.image_before.open('rb') as image_file:
            ml_result = run_waste_detection(image_file)

    result = _package_ml_verification(ml_result)

    if use_cache and cache_key:
        if len(_report_verify_cache) > 128:
            _report_verify_cache.clear()
        _report_verify_cache[cache_key] = result

    return result


def apply_ml_to_mutable_request_data(request, ml_result: dict) -> None:
    """Inject ML fields into multipart POST before serializer validation."""
    detected_waste_type = ml_result.get('waste_type')
    ai_confidence = ml_result.get('ai_confidence', 0.0)
    request.data._mutable = True
    request.data['ai_result'] = 'Waste'
    if detected_waste_type:
        request.data['waste_type'] = detected_waste_type
    request.data['ai_confidence'] = ai_confidence
    request.data._mutable = False


def build_rejection_response(
    verification: Dict[str, Any],
    *,
    http_status: int = 400,
) -> Tuple[Dict[str, Any], int]:
    """DRF Response body + status for failed AI checks."""
    ml_result = verification.get('ml_result') or {}
    reason = verification.get('reason') or 'no_waste'
    body = {
        'success': False,
        'rejected': True,
        'message': verification.get('message') or 'AI verification failed',
        'ai_result': ml_result.get('ai_result', 'Unverified'),
        'ai_confidence': float(ml_result.get('ai_confidence') or 0.0),
        'waste_type': ml_result.get('waste_type'),
        'ai_verification': verification.get('ai_verification'),
        'reason': reason,
        'below_threshold': bool(ml_result.get('below_threshold')),
        'rejection_kind': rejection_kind_for_ml(reason, ml_result),
    }
    return body, http_status


def build_create_success_response(report, serializer, ml_result: dict) -> Dict[str, Any]:
    conf = float(ml_result.get('ai_confidence') or 0.0)
    wt = ml_result.get('waste_type') or report.waste_type
    return {
        'success': True,
        'message': 'Report created successfully. AI verification passed.',
        'data': serializer.data,
        'ai_result': 'Waste',
        'ai_confidence': conf,
        'waste_type': wt,
        'ai_verification': format_ai_verification_block(ml_result, passed=True),
    }
