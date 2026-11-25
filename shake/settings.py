"""
Django settings for SHAKE (Structured Handling and Automated Knowledge Extraction).

Full Stack Django (Django Backend + Django Templates Frontend) configured with
automatic SQLite fallback for local development and optional PostgreSQL via DATABASE_URL.
"""

import os
import sys
from pathlib import Path

try:
    import dj_database_url
except ImportError:  # pragma: no cover - optional when running SQLite-only
    dj_database_url = None
from django.contrib.messages import constants as message_constants
from dotenv import load_dotenv

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

# Load environment variables from a local, untracked .env file (see .env.example).
load_dotenv(BASE_DIR / '.env')


# ==============================================================================
# Core Security Settings
# ==============================================================================

SECRET_KEY = (
    os.environ.get('SECRET_KEY')
    or os.environ.get('DJANGO_SECRET_KEY')
    or 'django-insecure-shake-dev-fallback-key-replace-in-production'
)

DEBUG = os.environ.get('DEBUG', 'True').strip().lower() in ('1', 'true', 'yes', 'on')

ALLOWED_HOSTS = [
    host.strip()
    for host in os.environ.get('ALLOWED_HOSTS', '127.0.0.1,localhost').split(',')
    if host.strip()
]


# ==============================================================================
# Application Definition
# ==============================================================================

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    # SHAKE Apps
    'accounts',
    'dashboard',
    'contracts',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'shake.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'shake.wsgi.application'
ASGI_APPLICATION = 'shake.asgi.application'


# ==============================================================================
# Database Configuration — SQLite Default with Optional PostgreSQL (DATABASE_URL)
# ==============================================================================
# Supports:
#   1. PostgreSQL (Neon / Supabase / Local) when DATABASE_URL is non-empty, or
#   2. Local SQLite (BASE_DIR / 'db.sqlite3') when DATABASE_URL is unset or empty.

DATABASE_URL = os.environ.get('DATABASE_URL', '').strip()

if DATABASE_URL:
    if dj_database_url is None:
        raise ImportError(
            "dj-database-url is required when DATABASE_URL is configured. "
            "Install dependencies via `pip install -r requirements.txt`."
        )
    DATABASES = {
        'default': dj_database_url.parse(
            DATABASE_URL,
            conn_max_age=600,
            ssl_require=os.environ.get('DB_SSL_REQUIRE', 'True').strip().lower() in ('1', 'true', 'yes', 'on'),
        )
    }
else:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': BASE_DIR / 'db.sqlite3',
        }
    }


# ==============================================================================
# Authentication & Password Validation
# ==============================================================================

AUTH_USER_MODEL = 'accounts.CustomUser'

# BR-01: users sign in with their unique email address (case-insensitive).
# EmailBackend falls back to username lookups for the Django admin site.
AUTHENTICATION_BACKENDS = ['accounts.backends.EmailBackend']

LOGIN_URL = 'login'
LOGIN_REDIRECT_URL = 'dashboard'
LOGOUT_REDIRECT_URL = 'login'

AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]


# ==============================================================================
# Internationalization
# ==============================================================================

LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'Asia/Manila'
USE_I18N = True
USE_TZ = True


# ==============================================================================
# Static & Media Files
# ==============================================================================

STATIC_URL = 'static/'
STATICFILES_DIRS = [BASE_DIR / 'static'] if (BASE_DIR / 'static').exists() else []
STATIC_ROOT = BASE_DIR / 'staticfiles'

MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'


# ==============================================================================
# Email & Flash Messages (Bootstrap 5 Alert Mapping)
# ==============================================================================

EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'

MESSAGE_TAGS = {
    message_constants.DEBUG: 'secondary',
    message_constants.INFO: 'info',
    message_constants.SUCCESS: 'success',
    message_constants.WARNING: 'warning',
    message_constants.ERROR: 'danger',
}

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'


# ==============================================================================
# Local Loopback REST API (F-11)
# ==============================================================================
# /api/v1/* only answers clients whose REMOTE_ADDR is a loopback address, even
# when runserver is bound to 0.0.0.0. Proxy headers (X-Forwarded-For) are never
# trusted. "testserver" is accepted only in DEBUG or under `manage.py test` so
# Django's test client can exercise the API; it is never a real socket address.

RUNNING_TESTS = len(sys.argv) > 1 and sys.argv[1] == 'test'

SHAKE_API_LOOPBACK_ONLY = True
SHAKE_API_LOOPBACK_ADDRESSES = ['127.0.0.1', '::1']
if DEBUG or RUNNING_TESTS:
    SHAKE_API_LOOPBACK_ADDRESSES.append('testserver')
