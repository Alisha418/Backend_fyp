from .base import *
from dotenv import load_dotenv, dotenv_values
import os
from pathlib import Path

# Always load .env from project root (manage.py folder). load_dotenv() without a path
# only reads cwd — agar runserver kisi aur directory se chala ho to ALLOWED_HOSTS miss ho jata hai.
load_dotenv(BASE_DIR / '.env')

# Firebase Admin (firebase-admin): service account JSON for ID token verify (e.g. /api/reset-password/).
# .env: GOOGLE_APPLICATION_CREDENTIALS=firebasekey.json (relative to this project root) or full path.
# If unset, looks for firebasekey.json then firbase_key.json next to manage.py.
_cred = os.getenv('GOOGLE_APPLICATION_CREDENTIALS', '').strip()
if _cred:
    _p = Path(_cred)
    if not _p.is_absolute():
        _p = BASE_DIR / _cred
    if _p.is_file():
        os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = str(_p.resolve())
elif not (os.getenv('FIREBASE_SERVICE_ACCOUNT_JSON') or '').strip():
    for _name in ('firebasekey.json', 'firbase_key.json'):
        _candidate = BASE_DIR / _name
        if _candidate.is_file():
            os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = str(_candidate.resolve())
            break

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = os.getenv('DEBUG', 'True') == 'True'

# ALLOWED_HOSTS: pehle .env file se (dotenv_values), phir os.environ.
# Windows par agar shell/system ne ALLOWED_HOSTS set kiya ho to load_dotenv() default usko
# overwrite NAHI karta — sirf os.getenv se purani list aati hai aur current LAN IP miss ho jata hai.
_default_allowed = 'localhost,127.0.0.1,10.0.2.2,192.168.100.24,192.168.100.25,192.168.1.3,192.168.1.4,192.168.1.5,192.168.1.6,192.168.1.7,10.5.56.136'
_file = dotenv_values(BASE_DIR / '.env')
_raw = (_file.get('ALLOWED_HOSTS') or os.getenv('ALLOWED_HOSTS') or _default_allowed)
if isinstance(_raw, str):
    _raw = _raw.strip()
if not _raw:
    _raw = _default_allowed
ALLOWED_HOSTS = list(
    dict.fromkeys(h.strip() for h in _raw.split(',') if h.strip())
)
# Extra safety: common LAN IPs (add yours if DisallowedHost on login)
for _lan_ip in ('192.168.100.24', '192.168.100.25', '192.168.1.3', '192.168.1.5', '192.168.1.4', '192.168.1.6', '10.5.56.136'):
    if _lan_ip not in ALLOWED_HOSTS:
        ALLOWED_HOSTS.append(_lan_ip)

# Database for development
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME':  os.getenv('DB_NAME', 'neat_now_db'),
        'USER': os. getenv('DB_USER', 'postgres'),
        'PASSWORD':  os.getenv('DB_PASSWORD', 'admin'),
        'HOST': os. getenv('DB_HOST', 'localhost'),
        'PORT': os.getenv('DB_PORT', '5432'),
    }
}

# Email backend for development
#EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'

# Media: USE_S3=False → all local; USE_S3=True → hybrid (legacy local + new S3)
USE_S3 = os.getenv('USE_S3', 'False').lower() in ('true', '1', 'yes')
if USE_S3:
    INSTALLED_APPS += ['storages']
    from .s3 import *  # noqa: F403, F401  # sets MEDIA_ROOT, LOCAL_MEDIA_URL, hybrid STORAGES
else:
    MEDIA_URL = '/media/'
    MEDIA_ROOT = BASE_DIR / 'media'
    LOCAL_MEDIA_URL = '/media/'
WEBSITE_URL = 'http://192.168.100.25:3000'
FRONTEND_URL = 'http://192.168.100.25:3000'

# For production, use: 
EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
EMAIL_HOST = 'smtp.gmail.com'
EMAIL_PORT = 587
EMAIL_USE_TLS = True
EMAIL_HOST_USER = 'afzalrehan779@gmail.com'
EMAIL_HOST_PASSWORD = 'iiqyvwwutxxjuhjg'  # Use Gmail App Password
DEFAULT_FROM_EMAIL = 'Admin System <afzalrehan779@gmail.com>'


# ==================== CORS CONFIGURATION (FIXED) ====================

# ✅ Allow Flutter Web (running on different port)
CORS_ALLOWED_ORIGINS = [
    'http://localhost:3000',
    'http://127.0.0.1:3000',
    'http://192.168.100.25:3000',  # admin panel (Vite) on laptop LAN
    'http://192.168.100.25:5173',
    'http://192.168.100.25:8000',
    'http://localhost:56901',  # Flutter web
    'http://127.0.0.1:56901',
    'http://10.0.2.2:8000',
]

# ✅ For development - allow all origins
CORS_ALLOW_ALL_ORIGINS = True

CORS_ALLOW_CREDENTIALS = True

# ✅ Add preflight caching
CORS_PREFLIGHT_MAX_AGE = 86400  # 24 hours

CORS_ALLOW_METHODS = [
    'DELETE',
    'GET',
    'OPTIONS',
    'PATCH',
    'POST',
    'PUT',
]

CORS_ALLOW_HEADERS = [
    'accept',
    'accept-encoding',
    'authorization',
    'content-type',
    'dnt',
    'origin',
    'user-agent',
    'x-csrftoken',
    'x-requested-with',
    'x-session-id',  # ✅ Add custom headers
]

# ✅ Expose custom headers
CORS_EXPOSE_HEADERS = [
    'content-type',
    'x-session-id',
]

# ==================== CSRF SETTINGS (FIXED) ====================

CSRF_TRUSTED_ORIGINS = [
    'http://localhost:3000',
    'http://127.0.0.1:3000',
    'http://192.168.100.25:3000',
    'http://192.168.100.25:5173',
    'http://192.168.1.6:3000',
    'http://10.5.56.136:3000',
    'http://localhost:56901',
    'http://127.0.0.1:56901',
    'http://10.0.2.2:8000',
]
from datetime import timedelta
APPEND_SLASH = True  # Default behavior
# Your existing SIMPLE_JWT configuration
SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(minutes=60),
    'REFRESH_TOKEN_LIFETIME': timedelta(days=1),
    'ROTATE_REFRESH_TOKENS': False,
    'BLACKLIST_AFTER_ROTATION': True,
    'UPDATE_LAST_LOGIN': False,

    'ALGORITHM': 'HS256',
    'SIGNING_KEY': SECRET_KEY,
    'VERIFYING_KEY': None,
    'AUDIENCE': None,
    'ISSUER': None,

    'AUTH_HEADER_TYPES': ('Bearer',),
    'AUTH_HEADER_NAME': 'HTTP_AUTHORIZATION',
    'USER_ID_FIELD': 'account_id',  # ← Add this line
    'USER_ID_CLAIM': 'user_id',     # ← Add this line
    
    'AUTH_TOKEN_CLASSES': ('rest_framework_simplejwt.tokens.AccessToken',),
    'TOKEN_TYPE_CLAIM': 'token_type',
}

# ✅ Disable CSRF for API endpoints in development
CSRF_COOKIE_HTTPONLY = False
CSRF_USE_SESSIONS = False

# Preload YOLO + ResNet18 on server start (avoids slow first worker verify).
WASTE_MODEL_WARMUP = os.getenv('WASTE_MODEL_WARMUP', 'True').lower() in ('true', '1', 'yes')

# Waste YOLO pass thresholds (citizen submit + admin create-task)
WASTE_MIN_CONFIDENCE = float(os.getenv('WASTE_MIN_CONFIDENCE', '0.20'))
WASTE_MIXED_MIN_CONFIDENCE = float(os.getenv('WASTE_MIXED_MIN_CONFIDENCE', '0.20'))

# Worker resolve: GPS + image similarity + before/after waste (similarity_cleanup.py)
WORKER_RESOLVE_MAX_DISTANCE_METERS = float(
    os.getenv('WORKER_RESOLVE_MAX_DISTANCE_METERS', '30'),
)
CLEANUP_SCENE_SIMILARITY_MIN = float(os.getenv('CLEANUP_SCENE_SIMILARITY_MIN', '0.38'))
CLEANUP_PATCH_SIMILARITY_MIN = float(os.getenv('CLEANUP_PATCH_SIMILARITY_MIN', '0.12'))
# SSIM on YOLO waste-area crop (256×256 grey): min = same spot, max = no visible cleanup
CLEANUP_PATCH_SSIM_MIN = float(os.getenv('CLEANUP_PATCH_SSIM_MIN', '0.12'))
CLEANUP_PATCH_SSIM_MAX_NO_CHANGE = float(os.getenv('CLEANUP_PATCH_SSIM_MAX_NO_CHANGE', '0.60'))
CLEANUP_SSIM_SIZE = int(os.getenv('CLEANUP_SSIM_SIZE', '256'))
CLEANUP_WASTE_REGION_PADDING = float(os.getenv('CLEANUP_WASTE_REGION_PADDING', '0.22'))
# Local ResNet18 for worker before/after scene match (see: python manage.py fetch_scene_weights)
SCENE_EMBEDDER_WEIGHTS_PATH = os.getenv(
    'SCENE_EMBEDDER_WEIGHTS_PATH',
    str(BASE_DIR / 'model_ml' / 'resnet18-f37072fd.pth'),
)
WORKER_RESOLVE_MIN_WASTE_REDUCTION_RATIO = float(
    os.getenv('WORKER_RESOLVE_MIN_WASTE_REDUCTION_RATIO', '0.50'),
)
WORKER_RESOLVE_BEFORE_MIN_PEAK = float(os.getenv('WORKER_RESOLVE_BEFORE_MIN_PEAK', '0.20'))
CLEANUP_AFTER_MAX_PEAK = float(os.getenv('CLEANUP_AFTER_MAX_PEAK', '0.35'))