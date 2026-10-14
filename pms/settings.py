"""
Django settings for PROPERTY MANAGEMENT SYSTEM.
"""
import os
from pathlib import Path

from pms.database import get_secure_database_config

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = 'django-insecure-pms-dev-key-change-in-production-xyz123abc'

DEBUG = True

ALLOWED_HOSTS = ['*']

CSRF_TRUSTED_ORIGINS = [
    'http://localhost:8000',
    'http://127.0.0.1:8000',
    'https://*.replit.dev',
    'https://*.sisko.replit.dev',
    'https://*.replit.app',
]

USE_X_FORWARDED_HOST = True
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    # Local apps
    'accounts',
    'equipment',
    'borrowing',
    'maintenance',
    'reports',
    'core',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'accounts.middleware.RoleAccessMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'pms.urls'

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
                'core.context_processors.site_settings_processor',
                'core.context_processors.notifications_processor',
            ],
        },
    },
]

WSGI_APPLICATION = 'pms.wsgi.application'

_database_url = os.environ.get('DATABASE_URL')
if _database_url:
    DATABASES = get_secure_database_config(db_url=_database_url)
else:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.mysql',
            'NAME': 'test_02',
            'USER': 'root',
            'PASSWORD': 'root',
            'HOST': '127.0.0.1',
            'PORT': '3307',
            'OPTIONS': {
                'connect_timeout': 20,
                'init_command': "SET sql_mode='STRICT_TRANS_TABLES', time_zone='+08:00'",
                'charset': 'utf8mb4',
            },
        }
    }

AUTH_USER_MODEL = 'accounts.User'

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'Asia/Manila'
USE_I18N = True
USE_TZ = True

STATIC_URL = '/static/'
STATICFILES_DIRS = [BASE_DIR / 'static']
STATIC_ROOT = BASE_DIR / 'staticfiles'
STATICFILES_STORAGE = 'whitenoise.storage.CompressedManifestStaticFilesStorage'

MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

LOGIN_URL = '/accounts/login/'
LOGIN_REDIRECT_URL = '/'
LOGOUT_REDIRECT_URL = '/accounts/login/'

# Email (SMTP)
EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
EMAIL_HOST = os.environ.get('MAIL_SERVER', 'smtp.gmail.com')
EMAIL_PORT = int(os.environ.get('MAIL_PORT', '587'))
EMAIL_USE_TLS = os.environ.get('MAIL_USE_TLS', 'True').lower() == 'true'
EMAIL_HOST_USER = os.environ.get('MAIL_USERNAME', 'habervincent21@gmail.com')
EMAIL_HOST_PASSWORD = os.environ.get('MAIL_PASSWORD', 'rudl msmx qphm kuln')
DEFAULT_FROM_EMAIL = os.environ.get(
    'MAIL_DEFAULT_SENDER',
    'MUNICIPALITY OF SUDIPEN <habervincent21@gmail.com>',
)

# Daily report recipients
ADMIN_EMAIL = os.environ.get('ADMIN_EMAIL', 'habervincent21@gmail.com')
DAILY_REPORT_EMAIL = os.environ.get('DAILY_REPORT_EMAIL', ADMIN_EMAIL)

CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
    }
}

# LGU name for COA forms (Province/City/Municipality)
LGU_NAME = 'SUDIPEN'
LGU_PROVINCE = os.environ.get('LGU_PROVINCE', 'LA UNION')
LGU_MUNICIPALITY = os.environ.get('LGU_MUNICIPALITY', 'SUDIPEN')
# LGU / school code used in property numbers — editable in Admin → Site settings (fallback)
LGU_CODE = os.environ.get('LGU_CODE', '1042')
