"""
Waste Detection Service using YOLOv8
Handles ML model loading and inference for waste detection
"""
import os
import logging
import time
import tempfile
from pathlib import Path
from typing import Any, Dict, Optional, Tuple, Union
from PIL import Image
import io

logger = logging.getLogger(__name__)

# Strong pass: any single detection >= 20% (citizen + admin)
WASTE_MIN_CONFIDENCE = 0.20
# Mixed pass: >=2 model classes each >= 20% (class max), >=2 total boxes
WASTE_MIXED_MIN_CONFIDENCE = 0.20
WASTE_MIXED_MIN_CATEGORIES = 2
WASTE_MIXED_MIN_DETECTIONS = 2


def get_pass_thresholds() -> Dict[str, Any]:
    from django.conf import settings

    return {
        'strong': float(getattr(settings, 'WASTE_MIN_CONFIDENCE', WASTE_MIN_CONFIDENCE)),
        'mixed_per_class': float(
            getattr(settings, 'WASTE_MIXED_MIN_CONFIDENCE', WASTE_MIXED_MIN_CONFIDENCE),
        ),
        'mixed_min_categories': int(
            getattr(settings, 'WASTE_MIXED_MIN_CATEGORIES', WASTE_MIXED_MIN_CATEGORIES),
        ),
        'mixed_min_boxes': int(
            getattr(settings, 'WASTE_MIXED_MIN_DETECTIONS', WASTE_MIXED_MIN_DETECTIONS),
        ),
    }


def _group_max_by_class(detections: list) -> Dict[str, Dict[str, Any]]:
    grouped: Dict[str, Dict[str, Any]] = {}
    for det in detections:
        cls = det['class']
        conf = float(det['confidence'])
        if cls not in grouped:
            grouped[cls] = {'max_conf': conf, 'count': 1}
        else:
            grouped[cls]['count'] += 1
            grouped[cls]['max_conf'] = max(grouped[cls]['max_conf'], conf)
    return grouped


def evaluate_waste_pass(detections: list) -> Dict[str, Any]:
    """
    Pass if:
      - any box >= strong threshold (20%), OR
      - >=2 waste categories with class-max >= mixed threshold (20%) and >=2 total boxes.
    """
    thresholds = get_pass_thresholds()
    strong_min = thresholds['strong']
    mixed_min = thresholds['mixed_per_class']
    min_cats = thresholds['mixed_min_categories']
    min_boxes = thresholds['mixed_min_boxes']

    peak_confidence = max((float(d['confidence']) for d in detections), default=0.0)
    grouped = _group_max_by_class(detections)

    best_strong = None
    best_strong_conf = 0.0
    for det in detections:
        conf = float(det['confidence'])
        if conf >= strong_min and conf > best_strong_conf:
            best_strong_conf = conf
            best_strong = det['class']

    if best_strong:
        valid = [d for d in detections if float(d['confidence']) >= strong_min]
        return {
            'passed': True,
            'pass_mode': 'strong',
            'pass_reason': (
                f'Single waste type detected at {best_strong_conf:.0%} '
                f'(required {strong_min:.0%}+).'
            ),
            'waste_type': best_strong,
            'ai_confidence': round(best_strong_conf, 2),
            'peak_confidence': round(peak_confidence, 2),
            'valid_detections': valid,
            'mixed_qualifying_categories': [],
            'is_mixed_waste': False,
            'min_confidence_required': strong_min,
            'mixed_min_confidence_required': mixed_min,
            'below_threshold': False,
        }

    qualifying = [
        {
            'class': cls,
            'confidence': info['max_conf'],
            'region_count': info['count'],
        }
        for cls, info in grouped.items()
        if info['max_conf'] >= mixed_min
    ]
    qualifying.sort(key=lambda x: float(x['confidence']), reverse=True)

    if len(qualifying) >= min_cats and len(detections) >= min_boxes:
        avg_conf = sum(float(q['confidence']) for q in qualifying) / len(qualifying)
        top_names = ', '.join(q['class'] for q in qualifying[:3])
        waste_type = f'Mixed ({top_names})' if len(qualifying) > 1 else qualifying[0]['class']
        valid = [d for d in detections if float(d['confidence']) >= mixed_min]
        return {
            'passed': True,
            'pass_mode': 'mixed',
            'pass_reason': (
                f'Multiple waste types detected ({len(qualifying)} categories at '
                f'{mixed_min:.0%}+, {len(detections)} regions in photo).'
            ),
            'waste_type': waste_type,
            'ai_confidence': round(avg_conf, 2),
            'peak_confidence': round(peak_confidence, 2),
            'valid_detections': valid,
            'mixed_qualifying_categories': qualifying,
            'is_mixed_waste': len(qualifying) > 1,
            'min_confidence_required': strong_min,
            'mixed_min_confidence_required': mixed_min,
            'below_threshold': False,
        }

    return {
        'passed': False,
        'pass_mode': None,
        'pass_reason': '',
        'waste_type': None,
        'ai_confidence': round(peak_confidence, 2),
        'peak_confidence': round(peak_confidence, 2),
        'valid_detections': [],
        'mixed_qualifying_categories': qualifying,
        'is_mixed_waste': False,
        'min_confidence_required': strong_min,
        'mixed_min_confidence_required': mixed_min,
        'below_threshold': len(detections) > 0 and peak_confidence > 0,
    }


def get_yolo_config() -> Dict[str, Any]:
    from django.conf import settings

    return {
        'imgsz': int(getattr(settings, 'WASTE_YOLO_IMAGE_SIZE', 640)),
        'conf': float(getattr(settings, 'WASTE_YOLO_PREDICT_CONF', 0.15)),
        'max_side': int(getattr(settings, 'WASTE_MAX_SOURCE_SIDE', 960)),
    }


def get_inference_device() -> str:
    try:
        import torch

        if torch.cuda.is_available():
            return '0'
    except ImportError:
        pass
    return 'cpu'


def _resize_pil_image(img: Image.Image, max_side: int) -> Image.Image:
    w, h = img.size
    longest = max(w, h)
    if longest <= max_side:
        return img
    scale = max_side / longest
    return img.resize(
        (int(w * scale), int(h * scale)),
        Image.Resampling.LANCZOS,
    )


def _resolve_predict_source(
    image_file: Any,
    max_side: int,
) -> Union[str, Image.Image]:
    """PIL in-memory for uploads; local path used as-is (no re-upload)."""
    if isinstance(image_file, (str, Path)):
        path = Path(image_file)
        if path.is_file():
            with Image.open(path) as img:
                return _resize_pil_image(img.convert('RGB'), max_side)
        return str(image_file)

    if hasattr(image_file, 'read'):
        image_file.seek(0)
        raw = image_file.read()
        image_file.seek(0)
        # Re-decode phone JPEGs (fixes corrupt/scaled gallery exports on Android).
        with Image.open(io.BytesIO(raw)) as img:
            rgb = img.convert('RGB')
            buf = io.BytesIO()
            rgb.save(buf, format='JPEG', quality=92, optimize=True)
            buf.seek(0)
            with Image.open(buf) as clean:
                return _resize_pil_image(clean.convert('RGB'), max_side)

    return image_file


def run_yolo_predict(model, source: Any):
    cfg = get_yolo_config()
    device = get_inference_device()
    kwargs: Dict[str, Any] = {
        'source': source,
        'imgsz': cfg['imgsz'],
        'conf': cfg['conf'],
        'verbose': False,
        'device': device,
        'save': False,
        'augment': False,
        'max_det': 40,
        'iou': 0.5,
    }
    if device != 'cpu':
        kwargs['half'] = True
    return model.predict(**kwargs)


def get_model_class_names(model) -> list[str]:
    """Human-readable class labels defined in best.pt (for UI filtering)."""
    names = getattr(model, 'names', None) or {}
    if isinstance(names, dict):
        return [str(names[k]).strip() for k in sorted(names.keys()) if names[k]]
    return [str(n).strip() for n in names if n]


def warmup_model() -> None:
    """Load + fuse weights at startup so first user request is faster."""
    import numpy as np

    model = load_model()
    cfg = get_yolo_config()
    blank = np.zeros((cfg['imgsz'], cfg['imgsz'], 3), dtype=np.uint8)
    run_yolo_predict(model, blank)
    logger.info(
        'Waste YOLO warmup finished (device=%s, imgsz=%s)',
        get_inference_device(),
        cfg['imgsz'],
    )

# Global model instance (lazy loading)
_model_instance = None


def _collect_pt_candidates() -> list[Path]:
    """Ordered search paths for Ultralytics YOLO .pt weights."""
    from django.conf import settings

    candidates: list[Path] = []
    configured = getattr(settings, 'WASTE_MODEL_PATH', None)
    if configured:
        p = Path(configured)
        if p.is_file() and p.suffix.lower() == '.pt':
            candidates.append(p)
        elif p.is_dir():
            candidates.extend([
                p / 'best.pt',
                p / 'weights' / 'best.pt',
                p / 'weights' / 'last.pt',
            ])
        elif p.suffix.lower() == '.pt':
            candidates.append(p)

    base_dir = Path(settings.BASE_DIR)
    model_ml_dir = base_dir / 'model_ml'
    candidates.extend([
        model_ml_dir / 'best_weights.pt',
        model_ml_dir / 'best.pt',
        model_ml_dir / 'best' / 'best.pt',
        model_ml_dir / 'weights' / 'best.pt',
        model_ml_dir / 'runs' / 'train' / 'weights' / 'best.pt',
    ])
    return candidates


def _is_valid_weights_file(path: Path) -> bool:
    """True when path is a single Ultralytics-style .pt weights file (~50MB)."""
    try:
        return path.is_file() and path.stat().st_size > 100_000
    except OSError:
        return False


def _misplaced_pytorch_folder_hint() -> Optional[str]:
    """Detect model_ml/best.pt folder (data.pkl) — common copy mistake."""
    from django.conf import settings

    model_ml = Path(settings.BASE_DIR) / 'model_ml'

    # Valid weights already present (e.g. model_ml/best/best.pt next to data.pkl export).
    for candidate in (
        model_ml / 'best_weights.pt',
        model_ml / 'best.pt',
        model_ml / 'best' / 'best.pt',
        model_ml / 'weights' / 'best.pt',
        model_ml / 'runs' / 'train' / 'weights' / 'best.pt',
    ):
        if _is_valid_weights_file(candidate):
            return None

    wrong = model_ml / 'best.pt'
    if wrong.is_dir() and (wrong / 'data.pkl').exists():
        return (
            f'{wrong} is a folder (PyTorch export), not a YOLO weights file. '
            'Copy the real trained file from training output '
            '(runs/train/weights/best.pt, ~50MB) to model_ml/best_weights.pt '
            'or rename the folder and place the single .pt file at model_ml/best.pt'
        )
    legacy = model_ml / 'best'
    if legacy.is_dir() and (legacy / 'data.pkl').exists():
        return (
            f'Found legacy folder {legacy} only. Export or copy Ultralytics '
            'best.pt (single file) into model_ml/best.pt'
        )
    return None


def get_model_path() -> Path:
    """
    Resolve trained YOLOv8 weights (best.pt).
    Ultralytics requires a single .pt file — not a folder named best.pt.
    """
    for path in _collect_pt_candidates():
        if _is_valid_weights_file(path):
            return path

    from django.conf import settings

    base_dir = Path(settings.BASE_DIR)
    model_ml_dir = base_dir / 'model_ml'
    # Alternate filename if user keeps folder named best.pt
    alt = model_ml_dir / 'best_weights.pt'
    if alt.is_file() and alt.exists():
        return alt

    misplaced = _misplaced_pytorch_folder_hint()
    if misplaced:
        logger.error(misplaced)

    hint = model_ml_dir / 'best.pt'
    return hint


def load_model():
    """
    Load YOLOv8 model (lazy loading - only loads once)
    """
    global _model_instance
    
    if _model_instance is not None:
        return _model_instance
    
    try:
        from ultralytics import YOLO
        
        model_path = get_model_path()
        
        logger.info(f"📦 Loading waste detection model from: {model_path}")
        
        if not _is_valid_weights_file(model_path):
            misplaced = _misplaced_pytorch_folder_hint()
            if misplaced:
                raise FileNotFoundError(misplaced)

        if not model_path.exists():
            raise FileNotFoundError(f"Model file not found at: {model_path}")

        if model_path.is_dir():
            raise FileNotFoundError(
                f'{model_path} is a directory. YOLO needs one weights file '
                f'(e.g. model_ml/best_weights.pt), not a folder named best.pt.'
            )

        if model_path.is_file() and model_path.stat().st_size < 100_000:
            raise FileNotFoundError(
                f'{model_path} is too small ({model_path.stat().st_size} bytes). '
                'Expected Ultralytics best.pt (~50MB).'
            )
        
        # Load model
        _model_instance = YOLO(str(model_path))
        
        # Verify model loaded correctly
        if _model_instance is None:
            raise RuntimeError("Model failed to load - YOLO returned None")
        
        # Set to evaluation mode
        if hasattr(_model_instance, 'model'):
            _model_instance.model.eval()

        try:
            _model_instance.fuse()
            logger.info('Model layers fused for faster inference')
        except Exception as fuse_exc:
            logger.debug('Model fuse skipped: %s', fuse_exc)
        
        # Log model info
        if hasattr(_model_instance, 'names'):
            class_count = len(_model_instance.names)
            logger.info(f"✅ Model loaded successfully with {class_count} classes")
            logger.info(f"📋 Classes: {list(_model_instance.names.values())}")
        else:
            logger.info("✅ Model loaded successfully")
        
        return _model_instance
        
    except ImportError:
        logger.error("Ultralytics YOLO not installed. Please install: pip install ultralytics")
        raise ImportError("Ultralytics YOLO library is required. Install with: pip install ultralytics")
    except FileNotFoundError as e:
        logger.error(f"Model file not found: {model_path} — {e}")
        raise FileNotFoundError(str(e)) from e
    except Exception as e:
        logger.error(f"Failed to load waste detection model from {model_path}: {str(e)}")
        raise RuntimeError(
            f"Failed to load waste detection model: {str(e)}\n"
            f"Model path: {model_path}\n"
            f"Please ensure the model file is a valid YOLOv8 .pt file."
        )


def detect_waste(image_file) -> Dict[str, any]:
    """
    Detect waste in uploaded image using YOLOv8 model
    
    Saves uploaded file temporarily for inference, then deletes it.
    
    Args:
        image_file: Django uploaded file or file path
        
    Returns:
        Dictionary with:
        - ai_result: 'Waste' or 'No Waste'
        - waste_type: Detected waste type (if waste found)
        - ai_confidence: Confidence score (0.0 to 1.0)
        - detections: List of all detections
    """
    temp_file_path = None
    t0 = time.perf_counter()

    try:
        model = load_model()
        model_class_names = get_model_class_names(model)
        cfg = get_yolo_config()
        source = _resolve_predict_source(image_file, cfg['max_side'])
        results = run_yolo_predict(model, source)
        logger.info(
            'YOLO predict done in %.2fs (imgsz=%s, device=%s)',
            time.perf_counter() - t0,
            cfg['imgsz'],
            get_inference_device(),
        )

        thresholds = get_pass_thresholds()
        detections = []
        image_width = None
        image_height = None

        if results and len(results) > 0:
            result = results[0]
            if getattr(result, 'orig_shape', None):
                image_height, image_width = int(result.orig_shape[0]), int(result.orig_shape[1])

            class_names = model.names if hasattr(model, 'names') else {}

            if result.boxes is not None and len(result.boxes) > 0:
                for box in result.boxes:
                    cls_id = int(box.cls[0].item())
                    confidence = float(box.conf[0].item())
                    if cls_id not in class_names:
                        continue
                    class_name = str(class_names[cls_id]).strip()
                    if not class_name or class_name.startswith('Class_'):
                        continue

                    bbox_norm = None
                    if image_width and image_height:
                        xyxy = box.xyxy[0].tolist()
                        bbox_norm = {
                            'x1': round(xyxy[0] / image_width, 4),
                            'y1': round(xyxy[1] / image_height, 4),
                            'x2': round(xyxy[2] / image_width, 4),
                            'y2': round(xyxy[3] / image_height, 4),
                        }

                    det_entry = {
                        'class': class_name,
                        'confidence': confidence,
                        'class_id': cls_id,
                    }
                    if bbox_norm:
                        det_entry['bbox'] = bbox_norm
                    detections.append(det_entry)
                    logger.debug('Detection: %s %.2f', class_name, confidence)

        if detections:
            logger.info(
                'Detection summary: total=%s strong>=%.0f%% mixed>=%.0f%% (need %s cats, %s boxes)',
                len(detections),
                thresholds['strong'] * 100,
                thresholds['mixed_per_class'] * 100,
                thresholds['mixed_min_categories'],
                thresholds['mixed_min_boxes'],
            )

        verdict = evaluate_waste_pass(detections)
        base = {
            'detections': detections,
            'model_class_names': model_class_names,
            'image_width': image_width,
            'image_height': image_height,
            'min_confidence_required': verdict['min_confidence_required'],
            'mixed_min_confidence_required': verdict['mixed_min_confidence_required'],
            'peak_confidence': verdict['peak_confidence'],
            'pass_mode': verdict.get('pass_mode'),
            'pass_reason': verdict.get('pass_reason', ''),
            'is_mixed_waste': verdict.get('is_mixed_waste', False),
            'mixed_qualifying_categories': verdict.get('mixed_qualifying_categories', []),
        }

        if verdict['passed']:
            logger.info(
                'Waste pass (%s): %s conf=%.2f',
                verdict['pass_mode'],
                verdict['waste_type'],
                verdict['ai_confidence'],
            )
            return {
                **base,
                'ai_result': 'Waste',
                'waste_type': verdict['waste_type'],
                'ai_confidence': verdict['ai_confidence'],
                'valid_detections': verdict['valid_detections'],
                'below_threshold': False,
            }

        if detections:
            logger.warning(
                'No waste pass: peak=%.0f%% (strong %.0f%% or %s types at %.0f%%+)',
                verdict['peak_confidence'] * 100,
                thresholds['strong'] * 100,
                thresholds['mixed_min_categories'],
                thresholds['mixed_per_class'] * 100,
            )
        else:
            logger.info('No detections found in image')

        return {
            **base,
            'ai_result': 'No Waste',
            'waste_type': None,
            'ai_confidence': verdict['ai_confidence'],
            'valid_detections': [],
            'below_threshold': verdict.get('below_threshold', False),
        }
            
    except Exception as e:
        logger.error(f"Error during waste detection: {str(e)}", exc_info=True)
        
        # Return safe default on error
        return {
            'ai_result': 'Unverified',
            'waste_type': None,
            'ai_confidence': 0.0,
            'detections': [],
            'error': str(e)
        }
    
    finally:
        # Always delete temporary file after inference
        if temp_file_path and os.path.exists(temp_file_path):
            try:
                os.unlink(temp_file_path)
                logger.debug(f"Deleted temporary file: {temp_file_path}")
            except Exception as e:
                logger.warning(f"Failed to delete temporary file {temp_file_path}: {str(e)}")


def reset_model():
    """
    Reset model instance (useful for testing or reloading)
    """
    global _model_instance
    _model_instance = None

