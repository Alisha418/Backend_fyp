"""Build browser-loadable URLs for uploaded files (legacy local or S3)."""
from pathlib import Path

from django.conf import settings


def _local_media_url_for_name(name: str) -> str | None:
    """Return /media/... path if file exists on local disk."""
    if not name:
        return None
    media_root = getattr(settings, 'MEDIA_ROOT', None)
    if not media_root:
        return None
    try:
        if not (Path(media_root) / name).is_file():
            return None
    except (TypeError, ValueError, OSError):
        return None
    base = getattr(settings, 'LOCAL_MEDIA_URL', '/media/')
    if not base.endswith('/'):
        base = f'{base}/'
    return f'{base}{name.lstrip("/")}'


def build_media_file_url(file_field, request=None):
    """
    Return a full URL for an ImageField/FileField, or None if empty.
    Legacy files on MEDIA_ROOT use local /media/; new files use storage (S3).
    """
    if not file_field:
        return None

    name = getattr(file_field, 'name', None)
    if name:
        local_url = _local_media_url_for_name(name)
        if local_url:
            if request is not None:
                return request.build_absolute_uri(local_url)
            return local_url

    try:
        url = file_field.url
    except (ValueError, AttributeError):
        return None
    if not url:
        return None
    if url.startswith(('http://', 'https://')):
        return url
    if not url.startswith('/'):
        url = f'/{url}'
    if not url.startswith('/media/') and url.startswith('/profiles/'):
        url = f'/media{url}'
    if request is not None:
        return request.build_absolute_uri(url)
    return url
