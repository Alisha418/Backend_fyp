"""
Django settings for core project. 
"""

from pathlib import Path
from datetime import timedelta
import os

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = 'django-insecure-4=73wcmynm56_m71fn#7-x4)npzz5lsvd%p8*ru34-!$!i+wrg'

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = True

# ✅ UPDATED: Allow connections from Flutter app
ALLOWED_HOSTS = [
    'localhost',
    '127.0.0.1',
    '10.0.2.2',  # Android emulator
    '*',  # Allow all for development (remove in production)
]

# URLs
WEBSITE_URL = 'http://localhost:3000'
FRONTEND_URL = 'http://localhost:3000'

# ==================== EMAIL CONFIGURATION ====================
EMAIL_BACKEND = 'django.core. mail.backends.smtp.EmailBackend'
EMAIL_HOST = 'smtp.gmail.com'
EMAIL_PORT = 587
EMAIL_USE_TLS = True
EMAIL_HOST_USER = 'afzalrehan779@gmail.com'
EMAIL_HOST_PASSWORD = 'iiqyvwwutxxjuhjg'  # Use Gmail App Password
DEFAULT_FROM_EMAIL = 'NeatNow System <afzalrehan779@gmail. com>'
SERVER_EMAIL = 'afzalrehan779@gmail.com'

# ==================== APPLICATION DEFINITION ====================

INSTALLED_APPS = [
    # Django apps
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib. sessions',
    'django.contrib.messages',
    'django. contrib.staticfiles',
    
    # Third party
    'rest_framework',
    'rest_framework_simplejwt',
    'corsheaders',  # ✅ Must be before django apps
    'django_filters',
    
    # Your apps - ORDER MATTERS!
    'apps. accounts',      # ✅ First (base user model)
    'apps.admins',        # ✅ Second (depends on accounts)
    'apps.workers',       # ✅ Third (depends on accounts)
    'apps.reports',       # ✅ Fourth (depends on accounts & workers)
    'apps.feedback',      # ✅ Fifth (depends on reports)
    'apps.tracking',      # ✅ Sixth (depends on reports)
    'apps.notifications', # ✅ Seventh
    'apps.analytics',     # ✅ LAST (depends on everything)
]

# ==================== MIDDLEWARE ====================

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'corsheaders.middleware.CorsMiddleware',  # ✅ MUST be at top, after SecurityMiddleware
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware. common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth. middleware.AuthenticationMiddleware',
    'django.contrib.messages. middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    # ❌ REMOVED: Duplicate SessionMiddleware and AuthenticationMiddleware
]

ROOT_URLCONF = 'core.urls'

# ==================== TEMPLATES ====================

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],  # ✅ Added templates directory
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django. contrib.messages.context_processors. messages',
                'django.template.context_processors.media',  # ✅ Added for media files
            ],
        },
    },
]

WSGI_APPLICATION = 'core.wsgi.application'

# ==================== DATABASE ====================

DATABASES = {
    'default': {
        'ENGINE': 'django.db. backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
    }
}

# ==================== PASSWORD VALIDATION ====================

AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django. contrib.auth.password_validation. MinimumLengthValidator',
        'OPTIONS': {
            'min_length': 8,  # ✅ Explicitly set minimum length
        }
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]

# ==================== CUSTOM USER MODEL ====================

AUTH_USER_MODEL = 'accounts.Account'  # ✅ Set custom user model

# ==================== REST FRAMEWORK ====================

REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'rest_framework_simplejwt.authentication.JWTAuthentication',  # ✅ Primary auth
        'rest_framework. authentication.SessionAuthentication',  # For admin panel
    ],
    'DEFAULT_PERMISSION_CLASSES':   [
        'rest_framework.permissions.AllowAny',  # ✅ Allow public registration/login
    ],
    'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.PageNumberPagination',
    'PAGE_SIZE': 20,
    'DEFAULT_FILTER_BACKENDS': [
        'django_filters.rest_framework.DjangoFilterBackend',
        'rest_framework.filters.SearchFilter',
        'rest_framework.filters.OrderingFilter',
    ],
    'DEFAULT_RENDERER_CLASSES': [
        'rest_framework.renderers.JSONRenderer',
        'rest_framework.renderers.BrowsableAPIRenderer',  # For DRF web interface
    ],
    'DEFAULT_PARSER_CLASSES': [
        'rest_framework.parsers.JSONParser',
        'rest_framework.parsers.MultiPartParser',  # ✅ For file uploads
        'rest_framework.parsers. FormParser',
    ],
    'EXCEPTION_HANDLER': 'rest_framework.views.exception_handler',
    'NON_FIELD_ERRORS_KEY': 'error',
    'DATETIME_FORMAT': '%Y-%m-%d %H:%M:%S',
}

# ==================== JWT SETTINGS ====================

SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(minutes=30),  # ✅ Reduced from 1 hour
    'REFRESH_TOKEN_LIFETIME': timedelta(days=7),
    'ROTATE_REFRESH_TOKENS': True,
    'BLACKLIST_AFTER_ROTATION': False,
    'UPDATE_LAST_LOGIN': True,
    
    'ALGORITHM': 'HS256',
    'SIGNING_KEY': SECRET_KEY,
    'VERIFYING_KEY':  None,
    'AUDIENCE':  None,
    'ISSUER': None,
    
    'AUTH_HEADER_TYPES':  ('Bearer',),
    'AUTH_HEADER_NAME': 'HTTP_AUTHORIZATION',
    'USER_ID_FIELD': 'account_id',  # ✅ Changed from admin_id to account_id
    'USER_ID_CLAIM': 'user_id',
    
    'AUTH_TOKEN_CLASSES': ('rest_framework_simplejwt.tokens.AccessToken',),
    'TOKEN_TYPE_CLAIM':   'token_type',
    
    'JTI_CLAIM': 'jti',
    
    'TOKEN_USER_CLASS': 'rest_framework_simplejwt. models.TokenUser',
    
    # ✅ Custom claims
    'TOKEN_OBTAIN_SERIALIZER': 'rest_framework_simplejwt. serializers.TokenObtainPairSerializer',
    'TOKEN_REFRESH_SERIALIZER': 'rest_framework_simplejwt.serializers.TokenRefreshSerializer',
}

# ==================== CORS CONFIGURATION ====================

# ✅ CRITICAL: Allow Flutter app to connect
CORS_ALLOWED_ORIGINS = [
    'http://localhost:3000',
    'http://127.0.0.1:3000',
    'http://10.0.2.2:8000',  # Android emulator
]

# For development - allow all origins
CORS_ALLOW_ALL_ORIGINS = True  # ✅ Set to False in production

CORS_ALLOW_CREDENTIALS = True

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
]

# ==================== MEDIA FILES (User Uploads) ====================

MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

# Create media directories if they don't exist
MEDIA_DIRS = [
    MEDIA_ROOT / 'profiles',
    MEDIA_ROOT / 'reports',
    MEDIA_ROOT / 'temp',
]

for dir_path in MEDIA_DIRS:
    dir_path.mkdir(parents=True, exist_ok=True)

# File upload settings
FILE_UPLOAD_MAX_MEMORY_SIZE = 10485760  # 10MB
DATA_UPLOAD_MAX_MEMORY_SIZE = 10485760  # 10MB

# Allowed file extensions
ALLOWED_IMAGE_EXTENSIONS = ['.jpg', '.jpeg', '.png', '.gif', '.webp']
MAX_IMAGE_SIZE = 5 * 1024 * 1024  # 5MB

# ==================== ML MODEL CONFIGURATION ====================

# Waste detection — Ultralytics YOLO needs best.pt (not legacy PyTorch folder only)
# Place weights at model_ml/best.pt or set path to your .pt file
WASTE_MODEL_PATH = BASE_DIR / 'model_ml' / 'best.pt'
SCENE_EMBEDDER_WEIGHTS_PATH = os.getenv(
    'SCENE_EMBEDDER_WEIGHTS_PATH',
    str(BASE_DIR / 'model_ml' / 'resnet18-f37072fd.pth'),
)
# Inference tuning (CPU: 640 fastest; raise via .env if GPU available)
WASTE_YOLO_IMAGE_SIZE = int(os.getenv('WASTE_YOLO_IMAGE_SIZE', '640'))
WASTE_YOLO_PREDICT_CONF = float(os.getenv('WASTE_YOLO_PREDICT_CONF', '0.12'))
WASTE_MAX_SOURCE_SIDE = int(os.getenv('WASTE_MAX_SOURCE_SIDE', '1280'))
WASTE_MODEL_WARMUP = os.getenv('WASTE_MODEL_WARMUP', 'True').lower() in ('true', '1', 'yes')
WASTE_VERIFY_CACHE = os.getenv('WASTE_VERIFY_CACHE', 'True').lower() in ('true', '1', 'yes')
# Pass: single type >= 40% OR mixed (>=2 model classes each >= 35%, >=2 boxes)
WASTE_MIN_CONFIDENCE = float(os.getenv('WASTE_MIN_CONFIDENCE', '0.20'))
WASTE_MIXED_MIN_CONFIDENCE = float(os.getenv('WASTE_MIXED_MIN_CONFIDENCE', '0.20'))
WASTE_MIXED_MIN_CATEGORIES = int(os.getenv('WASTE_MIXED_MIN_CATEGORIES', '2'))
WASTE_MIXED_MIN_DETECTIONS = int(os.getenv('WASTE_MIXED_MIN_DETECTIONS', '2'))

# ==================== STATIC FILES ====================

STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'

STATICFILES_DIRS = [
    BASE_DIR / 'static',
]

# Create static directory if it doesn't exist
(BASE_DIR / 'static').mkdir(exist_ok=True)

# ==================== INTERNATIONALIZATION ====================

LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'Asia/Karachi'  # ✅ Set to Pakistan timezone (adjust as needed)
USE_I18N = True
USE_TZ = True

# ==================== LOGGING ====================

LOGGING = {
    'version':  1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose':  {
            'format': '{levelname} {asctime} {module} {message}',
            'style': '{',
        },
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'verbose',
        },
        'file': {
            'class': 'logging.FileHandler',
            'filename': BASE_DIR / 'logs' / 'debug.log',
            'formatter':  'verbose',
        },
    },
    'root': {
        'handlers': ['console', 'file'],
        'level': 'INFO',
    },
    'loggers': {
        'django': {
            'handlers': ['console', 'file'],
            'level': 'INFO',
            'propagate':  False,
        },
        # Dev server lines like: [date] "POST /api/... HTTP/1.1" 200 ...
        # Explicit so request logs always show on the runserver terminal.
        'django.server': {
            'handlers': ['console', 'file'],
            'level': 'INFO',
            'propagate': False,
        },
        'apps': {
            'handlers': ['console', 'file'],
            'level': 'DEBUG',
            'propagate': False,
        },
    },
}

# Create logs directory
(BASE_DIR / 'logs').mkdir(exist_ok=True)

# ==================== SECURITY SETTINGS ====================

# CSRF Settings
CSRF_TRUSTED_ORIGINS = [
    'http://localhost:3000',
    'http://127.0.0.1:3000',
    'http://10.0.2.2:8000',
]

# Session Settings
SESSION_COOKIE_AGE = 1209600  # 2 weeks
SESSION_COOKIE_SECURE = False  # Set True in production with HTTPS
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = 'Lax'

# CSRF Cookie
CSRF_COOKIE_SECURE = False  # Set True in production
CSRF_COOKIE_HTTPONLY = False  # Allow JavaScript to read for API calls
CSRF_COOKIE_SAMESITE = 'Lax'

# Security headers (disable in development)
SECURE_BROWSER_XSS_FILTER = False
SECURE_CONTENT_TYPE_NOSNIFF = False
X_FRAME_OPTIONS = 'SAMEORIGIN'

# ==================== CUSTOM SETTINGS ====================

# Default primary key field type
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# Account settings
ACCOUNT_SESSION_REMEMBER = True
ACCOUNT_LOCKOUT_ATTEMPTS = 5
ACCOUNT_LOCKOUT_DURATION = 900  # 15 minutes in seconds

# Notification settings
NOTIFICATION_RETENTION_DAYS = 30
SEND_EMAIL_NOTIFICATIONS = True
SEND_SMS_NOTIFICATIONS = False  # Enable when SMS gateway is configured

# Report settings
REPORT_IMAGE_MAX_SIZE = 5 * 1024 * 1024  # 5MB
REPORT_AUTO_ASSIGN_RADIUS = 5000  # 5km in meters

# Worker tracking settings
WORKER_LOCATION_UPDATE_INTERVAL = 30  # seconds
WORKER_TRACKING_RETENTION_DAYS = 90

# Analytics settings
ANALYTICS_CACHE_TIMEOUT = 300  # 5 minutes

# ==================== DEVELOPMENT HELPERS ====================

if DEBUG:
    # Show SQL queries in console
    # LOGGING['loggers']['django.db.backends'] = {
    #     'handlers': ['console'],
    #     'level': 'DEBUG',
    #     'propagate': False,
    # }
    
    # Install django-extensions for better debugging
    try:
        import django_extensions
        INSTALLED_APPS.append('django_extensions')
    except ImportError:
        pass