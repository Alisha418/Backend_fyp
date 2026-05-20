"""
Worker resolve verification when uploading image_after.

Validation A — GPS: worker within N meters of citizen report location.
Validation C — Image similarity: before/after photos look like the same scene (ResNet embeddings).
Validation B — AI waste: before had waste; after no waste OR at least 50% lower peak confidence.
"""
from __future__ import annotations

import io
import logging
import math
import time
from pathlib import Path
from threading import Lock
from typing import Any, Dict, Optional, Tuple

from django.conf import settings
from PIL import Image

logger = logging.getLogger(__name__)

# Short-lived pass after worker-verify-cleanup (avoid running AI twice on resolve upload).
_verify_cache_lock = Lock()
_verify_cache_until: Dict[tuple[int, int], float] = {}
VERIFY_CACHE_SECONDS = 600


def invalidate_report_verify_cache(report_id: int) -> None:
    """Clear per-report scene/detection cache (e.g. after logic updates)."""
    rid = int(report_id)
    with _scene_before_cache_lock:
        _scene_before_cache.pop(rid, None)
        _before_detection_cache.pop(rid, None)


def mark_cleanup_verified(report_id: int, worker_account_id: int) -> None:
    with _verify_cache_lock:
        _verify_cache_until[(int(report_id), int(worker_account_id))] = (
            time.time() + VERIFY_CACHE_SECONDS
        )


def is_cleanup_verified(report_id: int, worker_account_id: int) -> bool:
    key = (int(report_id), int(worker_account_id))
    with _verify_cache_lock:
        until = _verify_cache_until.get(key)
        if until is None:
            return False
        if time.time() > until:
            _verify_cache_until.pop(key, None)
            return False
        return True

# Lazy-loaded torchvision embedder (ResNet18)
_embed_model = None
_embed_transform = None

# Per-report before-scene embedding + YOLO boxes (retries / re-verify on same task).
_scene_before_cache_lock = Lock()
_scene_before_cache: Dict[int, Any] = {}
_before_detection_cache: Dict[int, Dict[str, Any]] = {}


def _max_distance_meters() -> float:
    return float(getattr(settings, 'WORKER_RESOLVE_MAX_DISTANCE_METERS', 30.0))


def _min_waste_reduction_ratio() -> float:
    """After peak must be <= before_peak * (1 - ratio). 0.5 = at least half gone."""
    return float(getattr(settings, 'WORKER_RESOLVE_MIN_WASTE_REDUCTION_RATIO', 0.50))


def _after_max_peak() -> float:
    """After-image peak at or below this always counts as clean (if before had waste)."""
    return float(getattr(settings, 'CLEANUP_AFTER_MAX_PEAK', 0.35))


def _before_min_peak() -> float:
    """Original report should have shown some waste signal."""
    return float(getattr(settings, 'WORKER_RESOLVE_BEFORE_MIN_PEAK', 0.20))


def _scene_similarity_min() -> float:
    """Min cosine similarity between before/after image embeddings (0–1)."""
    return float(getattr(settings, 'CLEANUP_SCENE_SIMILARITY_MIN', 0.38))


def _patch_similarity_min() -> float:
    """Min visual match of the YOLO waste-area crop (0–1). Catches unrelated photos."""
    return float(getattr(settings, 'CLEANUP_PATCH_SIMILARITY_MIN', 0.12))


def _patch_ssim_min() -> float:
    """Min SSIM on waste-area crop — same physical spot (structure still partly visible)."""
    return float(getattr(settings, 'CLEANUP_PATCH_SSIM_MIN', 0.09))


def _patch_ssim_max_no_change() -> float:
    """SSIM above this on waste crop => before/after too alike (no real cleanup)."""
    return float(getattr(settings, 'CLEANUP_PATCH_SSIM_MAX_NO_CHANGE', 0.60))


def _ssim_crop_size() -> int:
    return int(getattr(settings, 'CLEANUP_SSIM_SIZE', 256))


def _waste_region_padding() -> float:
    """Extra margin around YOLO boxes when cropping the waste area (0–1 scale)."""
    return float(getattr(settings, 'CLEANUP_WASTE_REGION_PADDING', 0.18))


def _open_pil_image(source: Any) -> Image.Image:
    from PIL import ImageOps

    if source is None:
        raise ValueError('Image source is required')
    if isinstance(source, Image.Image):
        pil = source.convert('RGB')
    elif hasattr(source, 'read'):
        source.seek(0)
        raw = source.read()
        source.seek(0)
        pil = Image.open(io.BytesIO(raw)).convert('RGB')
    elif isinstance(source, str):
        pil = Image.open(source).convert('RGB')
    elif isinstance(source, bytes):
        pil = Image.open(io.BytesIO(source)).convert('RGB')
    else:
        raise TypeError(f'Unsupported image source: {type(source)}')
    return ImageOps.exif_transpose(pil)


def _detect_waste_pil(pil: Image.Image) -> Dict[str, Any]:
    from apps.reports.waste_detector import detect_waste

    buf = io.BytesIO()
    pil.save(buf, format='JPEG', quality=92)
    buf.seek(0)
    return detect_waste(buf)


def _before_detection_ml(report) -> Dict[str, Any]:
    """YOLO on citizen before-image with bbox cache (same report retries)."""
    from apps.reports.waste_detector import detect_waste

    rid = int(report.report_id)
    with _scene_before_cache_lock:
        cached = _before_detection_cache.get(rid)
    if cached is not None:
        return cached

    with report.image_before.open('rb') as before_fp:
        ml = detect_waste(before_fp)
    with _scene_before_cache_lock:
        _before_detection_cache[rid] = ml
    return ml


def _qualifying_waste_bboxes(ml_result: dict) -> list:
    """Normalized 0–1 boxes from YOLO (all detections with bbox, best conf per pass)."""
    from apps.reports.waste_detector import get_pass_thresholds

    thresholds = get_pass_thresholds()
    strong_min = float(thresholds['strong'])
    mixed_min = float(thresholds['mixed_per_class'])
    min_conf = min(strong_min, mixed_min, 0.12)

    boxes = []
    for det in ml_result.get('detections') or []:
        bbox = det.get('bbox')
        if not bbox:
            continue
        if float(det.get('confidence') or 0) >= min_conf:
            boxes.append(bbox)
    if boxes:
        return boxes

    for det in ml_result.get('valid_detections') or []:
        bbox = det.get('bbox')
        if bbox and float(det.get('confidence') or 0) >= min_conf:
            boxes.append(bbox)
    return boxes


def _patch_visual_similarity(
    before_pil: Image.Image,
    after_pil: Image.Image,
    bbox: Dict[str, float],
) -> float:
    """
    Compare the report waste rectangle on before vs after (structure + tone).
    Same site after cleanup stays >= ~0.32; unrelated photos are usually < 0.25.
    """
    import numpy as np
    from PIL import ImageFilter, ImageOps

    size = (176, 176)
    before_crop = ImageOps.autocontrast(
        _crop_pil_region(before_pil, bbox).convert('L').resize(
            size, Image.Resampling.LANCZOS,
        ),
    )
    after_crop = ImageOps.autocontrast(
        _crop_pil_region(after_pil, bbox).convert('L').resize(
            size, Image.Resampling.LANCZOS,
        ),
    )

    b = np.asarray(before_crop, dtype=np.float32) / 255.0
    a = np.asarray(after_crop, dtype=np.float32) / 255.0

    def _norm_corr(x, y):
        x = x - x.mean()
        y = y - y.mean()
        denom = float(np.linalg.norm(x) * np.linalg.norm(y))
        if denom < 1e-8:
            return 0.0
        return float(np.clip(np.dot(x.ravel(), y.ravel()) / denom, 0.0, 1.0))

    tone = _norm_corr(b, a)
    b_edge = np.asarray(before_crop.filter(ImageFilter.FIND_EDGES), dtype=np.float32) / 255.0
    a_edge = np.asarray(after_crop.filter(ImageFilter.FIND_EDGES), dtype=np.float32) / 255.0
    structure = _norm_corr(b_edge, a_edge)
    return float(0.45 * tone + 0.55 * structure)


def _waste_area_ssim(
    before_pil: Image.Image,
    after_pil: Image.Image,
    bbox: Dict[str, float],
) -> Optional[float]:
    """
    Structural similarity on the same YOLO waste rectangle (256×256 greyscale).
    Used only inside the report waste area — not full-frame scene match.
    """
    try:
        from skimage.metrics import structural_similarity as ssim_func
    except ImportError:
        logger.warning('scikit-image not installed; SSIM area check skipped')
        return None

    import numpy as np

    size = (_ssim_crop_size(), _ssim_crop_size())
    before_g = _crop_pil_region(before_pil, bbox).convert('L').resize(
        size, Image.Resampling.LANCZOS,
    )
    after_g = _crop_pil_region(after_pil, bbox).convert('L').resize(
        size, Image.Resampling.LANCZOS,
    )
    b = np.asarray(before_g, dtype=np.float64)
    a = np.asarray(after_g, dtype=np.float64)
    score = ssim_func(b, a, data_range=255.0)
    return float(max(0.0, min(1.0, score)))


def _area_same_place_ok(
    patch_sim: float,
    ssim_val: Optional[float],
    patch_min: float,
    ssim_min: float,
) -> bool:
    """
    Same waste area if patch OR SSIM passes (integer % to match UI), or blend is enough.
    After cleanup SSIM often 0.25–0.85; unrelated crops are usually lower on both.
    """
    patch_pct = int(round(float(patch_sim) * 100))
    patch_need = int(round(float(patch_min) * 100))

    if patch_pct >= patch_need:
        return True

    if ssim_val is None:
        return False

    ssim_pct = int(round(float(ssim_val) * 100))
    ssim_need = int(round(float(ssim_min) * 100))
    if ssim_pct >= ssim_need:
        return True

    blend = 0.35 * float(patch_sim) + 0.65 * float(ssim_val)
    blend_min = 0.35 * float(patch_min) + 0.65 * float(ssim_min)
    return int(round(blend * 100)) >= int(round(blend_min * 100))


def _area_metrics_payload(
    patch_sim: Optional[float],
    ssim_val: Optional[float],
    patch_min: float,
    ssim_min: float,
    ssim_max_no_change: float,
) -> Dict[str, Any]:
    patch_pct = int(round(patch_sim * 100)) if patch_sim is not None else None
    ssim_pct = int(round(ssim_val * 100)) if ssim_val is not None else None
    blend = None
    blend_pct = None
    if patch_sim is not None and ssim_val is not None:
        blend = 0.35 * patch_sim + 0.65 * ssim_val
        blend_pct = int(round(blend * 100))
    return {
        'waste_region_similarity': round(patch_sim, 4) if patch_sim is not None else None,
        'waste_region_similarity_percent': patch_pct,
        'waste_patch_min_required': patch_min,
        'waste_area_ssim': round(ssim_val, 4) if ssim_val is not None else None,
        'waste_area_ssim_percent': ssim_pct,
        'waste_area_ssim_min_required': ssim_min,
        'waste_area_ssim_max_no_change': ssim_max_no_change,
        'waste_area_combined_percent': blend_pct,
    }


def _union_bbox_normalized(boxes: list, padding: Optional[float] = None) -> Optional[Dict[str, float]]:
    if not boxes:
        return None
    pad = _waste_region_padding() if padding is None else padding
    x1 = min(float(b['x1']) for b in boxes)
    y1 = min(float(b['y1']) for b in boxes)
    x2 = max(float(b['x2']) for b in boxes)
    y2 = max(float(b['y2']) for b in boxes)
    w = max(x2 - x1, 1e-6)
    h = max(y2 - y1, 1e-6)
    x1 = max(0.0, x1 - pad * w)
    y1 = max(0.0, y1 - pad * h)
    x2 = min(1.0, x2 + pad * w)
    y2 = min(1.0, y2 + pad * h)
    if x2 - x1 < 0.05 or y2 - y1 < 0.05:
        return None
    return {'x1': x1, 'y1': y1, 'x2': x2, 'y2': y2}


def _crop_pil_region(pil: Image.Image, bbox: Dict[str, float]) -> Image.Image:
    w, h = pil.size
    left = max(0, min(w - 1, int(bbox['x1'] * w)))
    top = max(0, min(h - 1, int(bbox['y1'] * h)))
    right = max(left + 1, min(w, int(bbox['x2'] * w)))
    bottom = max(top + 1, min(h, int(bbox['y2'] * h)))
    if right - left < 48 or bottom - top < 48:
        return pil
    return pil.crop((left, top, right, bottom))


def _regional_waste_ml(before_pil: Image.Image, after_pil: Image.Image, union_bbox: Dict[str, float]):
    """Run YOLO on the same waste-area crop for before and after."""
    before_crop = _crop_pil_region(before_pil, union_bbox)
    after_crop = _crop_pil_region(after_pil, union_bbox)
    return _detect_waste_pil(before_crop), _detect_waste_pil(after_crop)


def scene_embedder_weights_path() -> Path:
    """Local ResNet18 checkpoint (no runtime download when file exists)."""
    configured = getattr(settings, 'SCENE_EMBEDDER_WEIGHTS_PATH', None)
    if configured:
        path = Path(configured)
        if not path.is_absolute():
            path = Path(settings.BASE_DIR) / path
        return path
    return Path(settings.BASE_DIR) / 'model_ml' / 'resnet18-f37072fd.pth'


def _load_resnet18_state(weights_path: Path):
    import torch

    try:
        return torch.load(weights_path, map_location='cpu', weights_only=True)
    except TypeError:
        return torch.load(weights_path, map_location='cpu')


def _get_scene_embedder():
    global _embed_model, _embed_transform
    if _embed_model is not None:
        return _embed_model, _embed_transform

    import torch
    from torchvision import models, transforms

    weights_path = scene_embedder_weights_path()
    model = models.resnet18(weights=None)

    if not weights_path.is_file():
        raise FileNotFoundError(
            f'Scene embedder weights not found at {weights_path}. '
            'Run once: python manage.py fetch_scene_weights',
        )

    logger.info('Loading scene embedder from %s', weights_path)
    state = _load_resnet18_state(weights_path)
    model.load_state_dict(state)

    model.fc = torch.nn.Identity()
    model.eval()

    transform = transforms.Compose([
        transforms.Resize((224, 224)),
        transforms.ToTensor(),
        transforms.Normalize(
            mean=[0.485, 0.456, 0.406],
            std=[0.229, 0.224, 0.225],
        ),
    ])

    _embed_model = model
    _embed_transform = transform
    return _embed_model, _embed_transform


def scene_embedding(source: Any):
    """Unit-normalized feature vector for cosine similarity."""
    import numpy as np
    import torch

    pil = _open_pil_image(source)
    model, transform = _get_scene_embedder()
    tensor = transform(pil).unsqueeze(0)

    with torch.no_grad():
        vec = model(tensor).cpu().numpy().reshape(-1).astype('float32')

    norm = float(np.linalg.norm(vec))
    if norm < 1e-8:
        return vec
    return vec / norm


def cosine_similarity(a, b) -> float:
    import numpy as np

    a = np.asarray(a, dtype='float32').reshape(-1)
    b = np.asarray(b, dtype='float32').reshape(-1)
    denom = float(np.linalg.norm(a) * np.linalg.norm(b))
    if denom < 1e-8:
        return 0.0
    return float(np.clip(np.dot(a, b) / denom, -1.0, 1.0))


def haversine_meters(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius = 6371000.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = (
        math.sin(dphi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    )
    return 2 * radius * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _peak_confidence(ml_result: dict) -> float:
    if not ml_result:
        return 0.0
    peak = ml_result.get('peak_confidence')
    if peak is not None:
        return float(peak)
    return float(ml_result.get('ai_confidence') or 0.0)


def _before_ml_from_report(report) -> Optional[Dict[str, Any]]:
    """
    Reuse citizen-submit AI fields so worker verify skips a second YOLO on image_before.
    Falls back to live inference when stored data is missing or unreliable.
    """
    from apps.reports.services.ai_categories import resolve_report_ai_categories

    ai = (report.ai_result or '').strip()
    if ai not in ('Waste', 'No Waste'):
        return None

    conf = float(report.ai_confidence or 0)
    categories = resolve_report_ai_categories(report)
    peak = conf
    for row in categories:
        peak = max(peak, float(row.get('confidence') or 0))

    min_peak = _before_min_peak()
    if ai == 'Waste' and peak < min_peak and not categories:
        return None

    return {
        'ai_result': ai,
        'waste_type': report.waste_type,
        'ai_confidence': round(conf, 2),
        'peak_confidence': round(peak, 4),
        'valid_detections': [],
        'mixed_qualifying_categories': categories,
        'from_report_cache': True,
    }


def _before_scene_embedding(report):
    """Cache before-image ResNet embedding for this report (same worker retries)."""
    rid = int(report.report_id)
    with _scene_before_cache_lock:
        cached = _scene_before_cache.get(rid)
    if cached is not None:
        return cached

    with report.image_before.open('rb') as before_fp:
        emb = scene_embedding(before_fp)
    with _scene_before_cache_lock:
        _scene_before_cache[rid] = emb
    return emb


def _cleanliness_score(before_peak: float, after_peak: float) -> int:
    """0–100: percent reduction in waste signal (50+ means at least half gone)."""
    if before_peak <= 0.05:
        if after_peak <= _after_max_peak():
            return 100
        return int(max(0, min(100, round((1.0 - after_peak) * 100))))
    ratio = 1.0 - (after_peak / before_peak)
    return int(max(0, min(100, round(ratio * 100))))


def _validate_gps(
    report,
    resolution_latitude: Optional[float],
    resolution_longitude: Optional[float],
) -> Tuple[bool, Dict[str, Any]]:
    max_m = _max_distance_meters()

    if resolution_latitude is None or resolution_longitude is None:
        return False, {
            'rejection_kind': 'gps_required',
            'message': (
                'GPS location is required when resolving. '
                'Enable location and capture your position at the cleanup site.'
            ),
        }

    try:
        worker_lat = float(resolution_latitude)
        worker_lng = float(resolution_longitude)
    except (TypeError, ValueError):
        return False, {
            'rejection_kind': 'gps_required',
            'message': 'Invalid GPS coordinates for resolution.',
        }

    if not (-90 <= worker_lat <= 90 and -180 <= worker_lng <= 180):
        return False, {
            'rejection_kind': 'gps_required',
            'message': 'GPS coordinates are out of range.',
        }

    if abs(worker_lat) < 1e-6 and abs(worker_lng) < 1e-6:
        return False, {
            'rejection_kind': 'gps_required',
            'message': 'Valid GPS fix required (location shows 0,0).',
        }

    report_lat = getattr(report, 'latitude', None)
    report_lng = getattr(report, 'longitude', None)
    if report_lat is None or report_lng is None:
        return False, {
            'rejection_kind': 'missing_location',
            'message': 'This report has no GPS location on file. Cannot verify you are on site.',
        }

    try:
        site_lat = float(report_lat)
        site_lng = float(report_lng)
    except (TypeError, ValueError):
        return False, {
            'rejection_kind': 'missing_location',
            'message': 'Report location data is invalid.',
        }

    distance_m = haversine_meters(site_lat, site_lng, worker_lat, worker_lng)
    if distance_m > max_m:
        return False, {
            'rejection_kind': 'too_far',
            'message': (
                f'You are {distance_m:.0f}m from the reported site '
                f'(maximum allowed {max_m:.0f}m). Move closer to the waste location and try again.'
            ),
            'gps_distance_meters': round(distance_m, 1),
            'gps_max_distance_meters': max_m,
            'report_latitude': site_lat,
            'report_longitude': site_lng,
            'worker_latitude': worker_lat,
            'worker_longitude': worker_lng,
        }

    return True, {
        'gps_distance_meters': round(distance_m, 1),
        'gps_max_distance_meters': max_m,
        'report_latitude': site_lat,
        'report_longitude': site_lng,
        'worker_latitude': worker_lat,
        'worker_longitude': worker_lng,
    }


def _validate_scene_similarity(
    report,
    image_after_file,
    *,
    before_detect: Optional[Dict[str, Any]] = None,
    before_pil: Optional[Image.Image] = None,
    after_pil: Optional[Image.Image] = None,
    union: Optional[Dict[str, float]] = None,
) -> Tuple[bool, Dict[str, Any]]:
    """
    Same-place check: full-frame ResNet + waste-area patch + SSIM on YOLO crop.
    SSIM runs only inside the report waste rectangle (not whole image).
    """
    scene_min = _scene_similarity_min()
    patch_min = _patch_similarity_min()
    ssim_min = _patch_ssim_min()
    ssim_max_no_change = _patch_ssim_max_no_change()

    try:
        before_emb = _before_scene_embedding(report)
        after_emb = scene_embedding(image_after_file)
        full_sim = cosine_similarity(before_emb, after_emb)
        full_pct = int(round(full_sim * 100))
        min_pct = int(round(scene_min * 100))

        patch_sim = None
        ssim_val = None
        area_payload: Dict[str, Any] = {}

        if union is not None:
            if before_pil is None:
                with report.image_before.open('rb') as before_fp:
                    before_pil = _open_pil_image(before_fp)
            if after_pil is None:
                after_pil = _open_pil_image(image_after_file)
            patch_sim = _patch_visual_similarity(before_pil, after_pil, union)
            ssim_val = _waste_area_ssim(before_pil, after_pil, union)
            area_payload = _area_metrics_payload(
                patch_sim, ssim_val, patch_min, ssim_min, ssim_max_no_change,
            )

        patch_pct = area_payload.get('waste_region_similarity_percent')
        ssim_pct = area_payload.get('waste_area_ssim_percent')

        logger.info(
            'Scene verify report %s: full=%.0f%% patch=%s ssim=%s union=%s',
            report.report_id,
            full_sim * 100,
            f'{patch_pct}%' if patch_pct is not None else 'n/a',
            f'{ssim_pct}%' if ssim_pct is not None else 'n/a',
            union is not None,
        )

        if union is not None and patch_sim is not None:
            if ssim_val is not None and ssim_val >= ssim_max_no_change:
                return False, {
                    'rejection_kind': 'no_change',
                    'message': (
                        f'After photo looks almost identical to the before image inside the '
                        f'report waste area (SSIM {ssim_pct}%, max allowed '
                        f'{int(round(ssim_max_no_change * 100))}% for cleanup proof). '
                        f'Clean the area and take a new after photo.'
                    ),
                    'scene_similarity': round(full_sim, 4),
                    'scene_min_required': scene_min,
                    'scene_similarity_percent': full_pct,
                    **area_payload,
                }

            if not _area_same_place_ok(patch_sim, ssim_val, patch_min, ssim_min):
                ssim_need = int(round(ssim_min * 100))
                patch_need = int(round(patch_min * 100))
                detail = (
                    'After photo is not the same waste area as the report '
                    f'(inside report area: match {patch_pct}%'
                )
                if ssim_pct is not None:
                    detail += f', SSIM {ssim_pct}%'
                detail += (
                    f'; need about {patch_need}%+ match or {ssim_need}%+ SSIM). '
                    'Photograph the same spot after cleaning.'
                )
                return False, {
                    'rejection_kind': 'wrong_location',
                    'message': detail,
                    'scene_similarity': round(full_sim, 4),
                    'scene_min_required': scene_min,
                    'scene_similarity_percent': full_pct,
                    **area_payload,
                }

        if full_sim < scene_min:
            area_ok = (
                union is not None
                and patch_sim is not None
                and _area_same_place_ok(patch_sim, ssim_val, patch_min, ssim_min)
            )
            if not area_ok:
                detail = (
                    f'After photo does not look like the same place as the original report '
                    f'(scene {full_pct}%, need {min_pct}%+). '
                )
                if patch_pct is not None:
                    detail += f'Area match {patch_pct}%. '
                if ssim_pct is not None:
                    detail += f'SSIM {ssim_pct}%. '
                detail += 'Photograph the same site after cleanup.'
                return False, {
                    'rejection_kind': 'wrong_location',
                    'message': detail,
                    'scene_similarity': round(full_sim, 4),
                    'scene_min_required': scene_min,
                    'scene_similarity_percent': full_pct,
                    **area_payload,
                }

        msg = f'Same scene confirmed (full {full_pct}%'
        if patch_pct is not None:
            msg += f', area {patch_pct}%'
        if ssim_pct is not None:
            msg += f', SSIM {ssim_pct}%'
        msg += ').'
        return True, {
            'scene_similarity': round(full_sim, 4),
            'scene_min_required': scene_min,
            'scene_similarity_percent': full_pct,
            'message': msg,
            **area_payload,
        }

    except ImportError as exc:
        logger.error('Scene similarity unavailable: %s', exc)
        return False, {
            'rejection_kind': 'unverified',
            'message': 'Image similarity check is unavailable.',
        }
    except Exception as exc:
        logger.error('Scene similarity failed: %s', exc, exc_info=True)
        return False, {
            'rejection_kind': 'unverified',
            'message': f'Image similarity check failed: {exc}',
        }


def _validate_waste_cleanup(
    before_ml: dict,
    after_full_ml: dict,
    *,
    before_detect: Optional[dict] = None,
    regional_before_ml: Optional[dict] = None,
    regional_after_ml: Optional[dict] = None,
) -> Tuple[bool, Dict[str, Any]]:
    """
    Compare waste signal before vs after on the report waste area (YOLO crop when possible).
    """
    used_region = regional_after_ml is not None
    before_peak = _peak_confidence(regional_before_ml or before_detect or before_ml)
    if before_peak < _before_min_peak():
        before_peak = max(before_peak, _peak_confidence(before_ml))

    after_eval = regional_after_ml if used_region else after_full_ml
    after_peak = _peak_confidence(after_eval)
    after_full_peak = _peak_confidence(after_full_ml)

    before_ai = (before_ml.get('ai_result') or '').strip()
    after_ai = (after_eval.get('ai_result') or '').strip()
    min_reduction = _min_waste_reduction_ratio()
    min_clean_pct = int(round(min_reduction * 100))
    score = _cleanliness_score(before_peak, after_peak)
    after_max_allowed = before_peak * (1.0 - min_reduction) if before_peak > 0.05 else _after_max_peak()

    # Before: citizen report should have had waste
    stored_before_ok = before_ai == 'Waste' or before_peak >= _before_min_peak()
    if not stored_before_ok:
        return False, {
            'rejection_kind': 'no_before_waste',
            'message': (
                'Original report image does not show enough waste to verify cleanup. '
                'Contact admin if this task is incorrect.'
            ),
            'before_peak_confidence': round(before_peak, 4),
            'after_peak_confidence': round(after_peak, 4),
            'cleanliness_score': score,
            'cleanliness_min_required': min_clean_pct,
        }

    # After: no waste OR at least half reduction in peak confidence
    region_note = ' (waste area only)' if used_region else ''

    if used_region and after_full_peak >= _before_min_peak() and after_peak <= _after_max_peak():
        return False, {
            'rejection_kind': 'not_clean',
            'message': (
                f'Waste still visible elsewhere in the photo ({after_full_peak:.0%}). '
                f'Frame the same cleaned area as the report.'
            ),
            'before_peak_confidence': round(before_peak, 4),
            'after_peak_confidence': round(after_peak, 4),
            'after_full_peak_confidence': round(after_full_peak, 4),
            'cleanliness_score': score,
            'cleanliness_min_required': min_clean_pct,
            'waste_region_check': True,
        }

    if after_ai == 'No Waste':
        return True, {
            'message': f'After image shows no waste in the report area{region_note}.',
            'before_peak_confidence': round(before_peak, 4),
            'after_peak_confidence': round(after_peak, 4),
            'after_full_peak_confidence': round(after_full_peak, 4),
            'cleanliness_score': max(score, min_clean_pct),
            'cleanliness_min_required': min_clean_pct,
            'before_waste_type': (regional_before_ml or before_ml).get('waste_type'),
            'after_waste_type': after_eval.get('waste_type'),
            'after_ai_result': after_ai,
            'waste_region_check': used_region,
        }

    if before_peak > 0.05 and after_peak <= after_max_allowed:
        return True, {
            'message': (
                f'Cleanup verified{region_note}: waste reduced from {before_peak:.0%} '
                f'to {after_peak:.0%} ({score}% reduction, need at least {min_clean_pct}%).'
            ),
            'before_peak_confidence': round(before_peak, 4),
            'after_peak_confidence': round(after_peak, 4),
            'cleanliness_score': score,
            'cleanliness_min_required': min_clean_pct,
            'before_waste_type': (regional_before_ml or before_ml).get('waste_type'),
            'after_waste_type': after_eval.get('waste_type'),
            'after_ai_result': after_ai,
            'waste_region_check': used_region,
        }

    if after_peak >= before_peak:
        msg = (
            f'After photo still shows similar or more waste in the report area{region_note} '
            f'({after_peak:.0%} vs before {before_peak:.0%}). '
            f'Clean the area and retake the photo.'
        )
    else:
        msg = (
            f'Not enough cleanup in the report area{region_note} yet '
            f'({score}% reduction, need at least {min_clean_pct}%). '
            f'Before {before_peak:.0%}, after {after_peak:.0%}.'
        )

    return False, {
        'rejection_kind': 'not_clean',
        'message': msg,
        'before_peak_confidence': round(before_peak, 4),
        'after_peak_confidence': round(after_peak, 4),
        'cleanliness_score': score,
        'cleanliness_min_required': min_clean_pct,
        'before_waste_type': (regional_before_ml or before_ml).get('waste_type'),
        'after_waste_type': after_eval.get('waste_type'),
        'after_ai_result': after_ai,
        'waste_region_check': used_region,
    }


def verify_worker_cleanup(
    report,
    image_after_file,
    *,
    resolution_latitude: Optional[float] = None,
    resolution_longitude: Optional[float] = None,
) -> Dict[str, Any]:
    """
    Full worker resolve verification: GPS + image similarity + YOLO before/after.

    Does not mutate the report.
    """
    from apps.reports.services.admin_waste_verification import buffer_uploaded_image
    from apps.reports.waste_detector import detect_waste

    if not report.image_before:
        return {
            'passed': False,
            'message': 'This report has no before image. Cannot verify cleanup.',
            'rejection_kind': 'missing_before',
        }

    gps_ok, gps_payload = _validate_gps(
        report, resolution_latitude, resolution_longitude,
    )
    if not gps_ok:
        return {'passed': False, **gps_payload}

    buffered_after = buffer_uploaded_image(image_after_file)

    try:
        before_detect = _before_detection_ml(report)
        before_ml = _before_ml_from_report(report) or before_detect

        with report.image_before.open('rb') as before_fp:
            before_pil = _open_pil_image(before_fp)
        if hasattr(buffered_after, 'seek'):
            buffered_after.seek(0)
        after_pil = _open_pil_image(buffered_after)

        union = _union_bbox_normalized(_qualifying_waste_bboxes(before_detect))

        scene_ok, scene_payload = _validate_scene_similarity(
            report,
            buffered_after,
            before_detect=before_detect,
            before_pil=before_pil,
            after_pil=after_pil,
            union=union,
        )
        if not scene_ok:
            return {'passed': False, **gps_payload, **scene_payload}

        if hasattr(buffered_after, 'seek'):
            buffered_after.seek(0)
        after_full_ml = detect_waste(buffered_after)

        regional_before_ml = None
        regional_after_ml = None
        if union is not None:
            regional_before_ml, regional_after_ml = _regional_waste_ml(
                before_pil,
                after_pil,
                union,
            )
            logger.info(
                'Cleanup verify report %s: YOLO on waste-area crop (%.0f%% x %.0f%% frame)',
                report.report_id,
                (union['x2'] - union['x1']) * 100,
                (union['y2'] - union['y1']) * 100,
            )
        else:
            logger.warning(
                'Cleanup verify report %s: no waste boxes on before image — full-frame YOLO only',
                report.report_id,
            )

        if (before_ml.get('ai_result') or '') == 'Unverified':
            return {
                'passed': False,
                'message': 'Could not analyze the original report image.',
                'rejection_kind': 'unverified',
                **gps_payload,
            }
        after_check = regional_after_ml or after_full_ml
        if (after_check.get('ai_result') or '') == 'Unverified':
            return {
                'passed': False,
                'message': 'Could not analyze your after photo. Please try again.',
                'rejection_kind': 'unverified',
                **gps_payload,
            }

        clean_ok, clean_payload = _validate_waste_cleanup(
            before_ml,
            after_full_ml,
            before_detect=before_detect,
            regional_before_ml=regional_before_ml,
            regional_after_ml=regional_after_ml,
        )
        if not clean_ok:
            return {'passed': False, **gps_payload, **scene_payload, **clean_payload}

        return {
            'passed': True,
            'rejection_kind': '',
            'message': (
                f'Verified: within {gps_payload["gps_distance_meters"]}m of report site. '
                f'{scene_payload.get("message", "")} '
                f'{clean_payload.get("message", "")}'
            ).strip(),
            **gps_payload,
            **scene_payload,
            **clean_payload,
        }

    except ImportError as exc:
        logger.error('Cleanup verification import error: %s', exc)
        return {
            'passed': False,
            'message': 'AI verification service is unavailable.',
            'rejection_kind': 'unverified',
        }
    except Exception as exc:
        logger.error('Cleanup verification failed: %s', exc, exc_info=True)
        return {
            'passed': False,
            'message': f'AI verification failed: {exc}',
            'rejection_kind': 'unverified',
        }


def build_cleanup_rejection_response(
    verification: Dict[str, Any],
) -> Tuple[Dict[str, Any], int]:
    from rest_framework import status as drf_status

    kind = verification.get('rejection_kind') or 'rejected'
    code = (
        drf_status.HTTP_503_SERVICE_UNAVAILABLE
        if kind == 'unverified'
        else drf_status.HTTP_400_BAD_REQUEST
    )
    body = {
        'success': False,
        'rejected': True,
        'message': verification.get('message') or 'Cleanup verification failed',
        'rejection_kind': kind,
        'gps_distance_meters': verification.get('gps_distance_meters'),
        'gps_max_distance_meters': verification.get('gps_max_distance_meters'),
        'scene_similarity': verification.get('scene_similarity'),
        'scene_similarity_percent': verification.get('scene_similarity_percent'),
        'scene_min_required': verification.get('scene_min_required'),
        'waste_region_similarity_percent': verification.get('waste_region_similarity_percent'),
        'waste_patch_min_required': verification.get('waste_patch_min_required'),
        'waste_area_ssim_percent': verification.get('waste_area_ssim_percent'),
        'waste_area_ssim_min_required': verification.get('waste_area_ssim_min_required'),
        'waste_area_combined_percent': verification.get('waste_area_combined_percent'),
        'cleanliness_score': verification.get('cleanliness_score'),
        'cleanliness_min_required': verification.get('cleanliness_min_required'),
        'before_peak_confidence': verification.get('before_peak_confidence'),
        'after_peak_confidence': verification.get('after_peak_confidence'),
        'before_waste_type': verification.get('before_waste_type'),
        'after_waste_type': verification.get('after_waste_type'),
        'verification': verification,
    }
    return body, code


def build_cleanup_success_response(verification: Dict[str, Any]) -> Dict[str, Any]:
    return {
        'success': True,
        'rejected': False,
        'message': verification.get('message') or 'Cleanup verified',
        'gps_distance_meters': verification.get('gps_distance_meters'),
        'gps_max_distance_meters': verification.get('gps_max_distance_meters'),
        'scene_similarity_percent': verification.get('scene_similarity_percent'),
        'scene_min_required': verification.get('scene_min_required'),
        'waste_region_similarity_percent': verification.get('waste_region_similarity_percent'),
        'waste_patch_min_required': verification.get('waste_patch_min_required'),
        'waste_area_ssim_percent': verification.get('waste_area_ssim_percent'),
        'waste_area_ssim_min_required': verification.get('waste_area_ssim_min_required'),
        'waste_area_combined_percent': verification.get('waste_area_combined_percent'),
        'cleanliness_score': verification.get('cleanliness_score'),
        'cleanliness_min_required': verification.get('cleanliness_min_required'),
        'before_peak_confidence': verification.get('before_peak_confidence'),
        'after_peak_confidence': verification.get('after_peak_confidence'),
        'verification': verification,
    }
