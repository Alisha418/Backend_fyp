import logging

from django.apps import AppConfig

logger = logging.getLogger(__name__)


class ReportsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.reports'

    def ready(self):
        from django.conf import settings

        if not getattr(settings, 'WASTE_MODEL_WARMUP', False):
            return
        try:
            from apps.reports.waste_detector import load_model, warmup_model

            load_model()
            warmup_model()
        except Exception as exc:
            logger.warning('Waste model warmup skipped: %s', exc)

        try:
            from apps.reports.services.similarity_cleanup import (
                _get_scene_embedder,
                scene_embedder_weights_path,
            )

            weights_path = scene_embedder_weights_path()
            if weights_path.is_file() and weights_path.stat().st_size >= 40_000_000:
                _get_scene_embedder()
                logger.info('Scene similarity model (ResNet18) ready')
            elif weights_path.is_file():
                logger.warning(
                    'Scene weights file is incomplete (%s bytes) — delete it and run: '
                    'python manage.py fetch_scene_weights --force',
                    weights_path.stat().st_size,
                )
            else:
                logger.warning(
                    'Scene weights not in model_ml/ — run: python manage.py fetch_scene_weights',
                )
        except Exception as exc:
            logger.warning('Scene embedder warmup skipped: %s', exc)