"""
Hybrid media storage: new uploads → S3; legacy files on disk → served from local MEDIA_ROOT.

DB still stores relative paths (e.g. profiles/x.jpg, reports/before/y.jpg).
If that path exists under MEDIA_ROOT, read/url point to local /media/...
Otherwise use S3 (new uploads after migration).
"""
from pathlib import Path

from django.conf import settings
from storages.backends.s3 import S3Storage


class HybridMediaStorage(S3Storage):
    """Write to S3; prefer local disk when the same path exists there (pre-S3 uploads)."""

    def _local_file_path(self, name: str) -> Path:
        return Path(settings.MEDIA_ROOT) / name

    def _has_local_copy(self, name: str) -> bool:
        if not name:
            return False
        try:
            return self._local_file_path(name).is_file()
        except (TypeError, ValueError, OSError):
            return False

    def _local_media_url(self, name: str) -> str:
        base = getattr(settings, 'LOCAL_MEDIA_URL', '/media/')
        if not base.endswith('/'):
            base = f'{base}/'
        return f'{base}{name.lstrip("/")}'

    def url(self, name, parameters=None, expire=None, http_method=None):
        if self._has_local_copy(name):
            return self._local_media_url(name)
        return super().url(name, parameters=parameters, expire=expire, http_method=http_method)

    def exists(self, name):
        if self._has_local_copy(name):
            return True
        return super().exists(name)

    def open(self, name, mode='rb'):
        if 'r' in mode and self._has_local_copy(name):
            return open(self._local_file_path(name), mode)
        return super().open(name, mode)

    def size(self, name):
        if self._has_local_copy(name):
            return self._local_file_path(name).stat().st_size
        return super().size(name)

    def delete(self, name):
        # Remove from S3 when present; keep legacy local files untouched
        try:
            if super().exists(name):
                super().delete(name)
        except Exception:
            pass

    def save(self, name, content, max_length=None):
        # New content is stored on S3 only (not duplicated to local disk)
        return super().save(name, content, max_length=max_length)
