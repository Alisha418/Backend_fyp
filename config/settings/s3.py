"""
AWS S3 media storage (loaded when USE_S3=True in .env).
New uploads go to S3; files still on disk under MEDIA_ROOT keep working locally.
"""
import os

from .base import BASE_DIR

AWS_ACCESS_KEY_ID = os.getenv('AWS_ACCESS_KEY_ID')
AWS_SECRET_ACCESS_KEY = os.getenv('AWS_SECRET_ACCESS_KEY')
AWS_STORAGE_BUCKET_NAME = os.getenv('AWS_STORAGE_BUCKET_NAME', 'neatnow-reports')
AWS_S3_REGION_NAME = os.getenv('AWS_S3_REGION_NAME', 'us-east-1')

AWS_S3_CUSTOM_DOMAIN = (
    f'{AWS_STORAGE_BUCKET_NAME}.s3.{AWS_S3_REGION_NAME}.amazonaws.com'
)
AWS_S3_OBJECT_PARAMETERS = {
    'CacheControl': 'max-age=86400',
}
AWS_DEFAULT_ACL = None
AWS_QUERYSTRING_AUTH = False
AWS_S3_FILE_OVERWRITE = False

# Legacy uploads remain here; hybrid storage reads from this path when file exists
MEDIA_ROOT = BASE_DIR / 'media'
LOCAL_MEDIA_URL = '/media/'

# Used by S3 for new objects; local serving uses LOCAL_MEDIA_URL + MEDIA_ROOT
MEDIA_URL = f'https://{AWS_S3_CUSTOM_DOMAIN}/'

STORAGES = {
    'default': {
        'BACKEND': 'config.hybrid_storage.HybridMediaStorage',  # noqa: long path
        'OPTIONS': {
            'bucket_name': AWS_STORAGE_BUCKET_NAME,
            'region_name': AWS_S3_REGION_NAME,
            'access_key': AWS_ACCESS_KEY_ID,
            'secret_key': AWS_SECRET_ACCESS_KEY,
            'custom_domain': AWS_S3_CUSTOM_DOMAIN,
            'default_acl': AWS_DEFAULT_ACL,
            'querystring_auth': AWS_QUERYSTRING_AUTH,
            'file_overwrite': AWS_S3_FILE_OVERWRITE,
        },
    },
    'staticfiles': {
        'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage',
    },
}
