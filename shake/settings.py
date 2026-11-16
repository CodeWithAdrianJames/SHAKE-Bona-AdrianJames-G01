"""
Django settings for SHAKE (Structured Handling and Automated Knowledge Extraction).

Full Stack Django (Django Backend + Django Templates Frontend) configured strictly
for PostgreSQL / Supabase via environment variables.
"""

import os
from pathlib import Path

import dj_database_url
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
# Database Configuration — PostgreSQL / Supabase ONLY (No SQLite)
# ==============================================================================
# Supports either:
#   1. DATABASE_URL (e.g. Supabase connection pooler URI), or
#   2. Individual DB_NAME, DB_USER, DB_PASSWORD, DB_HOST, DB_PORT variables.

DATABASE_URL = os.environ.get('DATABASE_URL', '').strip()

if DATABASE_URL:
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
            'ENGINE': 'django.db.backends.postgresql',
            'NAME': os.environ.get('DB_NAME', 'postgres'),
            'USER': os.environ.get('DB_USER', 'postgres'),
            'PASSWORD': os.environ.get('DB_PASSWORD', ''),
            'HOST': os.environ.get('DB_HOST', 'localhost'),
            'PORT': os.environ.get('DB_PORT', '5432'),
            'OPTIONS': {
                'sslmode': os.environ.get('DB_SSLMODE', 'prefer'),
            },
        }
    }


# ==============================================================================
# Authentication & Password Validation
# ==============================================================================

AUTH_USER_MODEL = 'accounts.CustomUser'

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
