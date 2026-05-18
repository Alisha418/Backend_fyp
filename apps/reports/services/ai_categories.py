"""Persist and resolve per-class AI waste categories for API clients."""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from apps.reports.services.admin_waste_verification import _group_detections_by_class

_MIXED_RE = re.compile(r'^Mixed\s*\((.+)\)\s*$', re.IGNORECASE)


def extract_ai_categories_from_ml(ml_result: dict) -> List[Dict[str, Any]]:
    """Build storable category rows from YOLO ml_result (same grouping as admin UI)."""
    mixed = ml_result.get('mixed_qualifying_categories') or []
    if mixed:
        return [
            {
                'class': (q.get('class') or 'Unknown').strip(),
                'confidence': round(float(q.get('confidence') or 0), 3),
                'region_count': int(q.get('region_count') or 1),
            }
            for q in mixed
        ]

    detections = ml_result.get('valid_detections') or ml_result.get('detections') or []
    grouped = _group_detections_by_class(detections)
    if grouped:
        return [
            {
                'class': g['class'],
                'confidence': round(float(g['confidence']), 3),
                'region_count': int(g['region_count']),
            }
            for g in grouped
        ]

    waste_type = (ml_result.get('waste_type') or '').strip()
    conf = float(ml_result.get('ai_confidence') or 0)
    if not waste_type:
        return []
    return _categories_from_waste_type_label(waste_type, conf)


def _categories_from_waste_type_label(waste_type: str, confidence: float) -> List[Dict[str, Any]]:
    wt = (waste_type or '').strip()
    if not wt:
        return []
    m = _MIXED_RE.match(wt)
    if m:
        names = [n.strip() for n in m.group(1).split(',') if n.strip()]
        if not names:
            return []
        return [
            {'class': name, 'confidence': round(confidence, 3), 'region_count': 1}
            for name in names
        ]
    return [{'class': wt, 'confidence': round(confidence, 3), 'region_count': 1}]


def resolve_report_ai_categories(report) -> List[Dict[str, Any]]:
    """Categories for serializers: stored JSON first, else legacy waste_type parse."""
    stored = getattr(report, 'ai_categories', None)
    if stored:
        return list(stored)
    conf = float(report.ai_confidence or 0)
    return _categories_from_waste_type_label(report.waste_type or '', conf)
