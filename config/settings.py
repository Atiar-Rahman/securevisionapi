from datetime import timedelta
import os
from decouple import AutoConfig
from pathlib import Path
from urllib.parse import urlparse, unquote

try:
    import cloudinary
except ImportError:  # pragma: no cover - optional until dependency is installed
    cloudinary = None

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent
config = AutoConfig(search_path=BASE_DIR)


def _to_bool(value, default=False):
    if isinstance(value, bool):
        return value
    if value is None:
        return default

    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off", "release", "prod", "production"}:
        return False
    return default


def _split_csv(value):
    if not value:
        return []
    return [item.strip() for item in str(value).split(",") if item.strip()]


def _postgres_config_from_url(database_url):
    parsed = urlparse(database_url)
    return {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": parsed.path.lstrip("/"),
        "USER": unquote(parsed.username or ""),
        "PASSWORD": unquote(parsed.password or ""),
        "HOST": parsed.hostname or "",
        "PORT": str(parsed.port or "5432"),
    }



SECRET_KEY = config('SECRET_KEY')
DEBUG = _to_bool(config('DEBUG', default=False))

default_allowed_hosts = [
    "127.0.0.1",
    "localhost",
    ".fly.dev",
    ".onrender.com",
]
configured_hosts = _split_csv(config("ALLOWED_HOSTS", default=""))
render_external_hostname = config("RENDER_EXTERNAL_HOSTNAME", default="").strip()
ALLOWED_HOSTS = list(
    dict.fromkeys(
        [
            *default_allowed_hosts,
            *configured_hosts,
            *([render_external_hostname] if render_external_hostname else []),
        ]
    )
)

# Use BigAutoField by default for all models
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
# Application definition

INSTALLED_APPS = [
    "whitenoise.runserver_nostatic",
    'daphne',
    'channels',
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'drf_yasg',
    'users',
    'rest_framework',
    'djoser',
    'rest_framework_simplejwt',
    'cameras',
    'api',
    'detection',
    'corsheaders',
    'alert',
    'contact',
    'reviews'
]

if DEBUG:
    INSTALLED_APPS.append("debug_toolbar")

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    "whitenoise.middleware.WhiteNoiseMiddleware",
    'django.contrib.sessions.middleware.SessionMiddleware',
    "corsheaders.middleware.CorsMiddleware",
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

if DEBUG:
    MIDDLEWARE.insert(0, "debug_toolbar.middleware.DebugToolbarMiddleware")

ROOT_URLCONF = 'config.urls'
AUTH_USER_MODEL = 'users.User'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'
ASGI_APPLICATION = 'config.asgi.application'

default_allowed_origins = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "https://secure-vision-ai-frontend.vercel.app",
    "https://securevisionaibackend.onrender.com",
]

configured_origins = _split_csv(config("CORS_ALLOWED_ORIGINS", default=""))
env_origins = [
    config("FRONTEND_URL", default="").strip(),
    config("BACKEND_URL", default="").strip(),
]
if render_external_hostname:
    env_origins.append(f"https://{render_external_hostname}")

CORS_ALLOWED_ORIGINS = list(
    dict.fromkeys(origin for origin in [*default_allowed_origins, *configured_origins, *env_origins] if origin)
)
CSRF_TRUSTED_ORIGINS = CORS_ALLOWED_ORIGINS.copy()
# Database
# https://docs.djangoproject.com/en/6.0/ref/settings/#databases

# DATABASES = {
#     'default': {
#         'ENGINE': 'django.db.backends.sqlite3',
#         'NAME': BASE_DIR / 'db.sqlite3',
#     }
# }

database_url = config("DATABASE_URL", default="").strip()

if database_url:
    default_database = _postgres_config_from_url(database_url)
else:
    default_database = {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': config('DB_NAME', default='w3_django_db'),
        'USER': config('DB_USER', default='admin'),
        'PASSWORD': config('DB_PASSWORD'),
        'HOST': config('DB_HOST', default='localhost'),
        'PORT': config('DB_PORT', default='5432'),
    }

default_database['CONN_MAX_AGE'] = config('DB_CONN_MAX_AGE', default=60, cast=int)

DATABASES = {
    'default': default_database
}

if _to_bool(config("DB_SSL_REQUIRED", default=not DEBUG), default=not DEBUG):
    DATABASES["default"]["OPTIONS"] = {"sslmode": "require"}


# Password validation
# https://docs.djangoproject.com/en/6.0/ref/settings/#auth-password-validators

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


# Internationalization
# https://docs.djangoproject.com/en/6.0/topics/i18n/

LANGUAGE_CODE = 'en-us'

TIME_ZONE = 'UTC'

USE_I18N = True

USE_TZ = True


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/6.0/howto/static-files/

STATIC_URL = 'static/'

STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_STORAGE = "whitenoise.storage.CompressedStaticFilesStorage"

MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"
INTERNAL_IPS = [
    '127.0.0.1'
]

# Channels configuration
CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels.layers.InMemoryChannelLayer"
    }
}


REST_FRAMEWORK = {
    'COERCE_DECIMAL_TO_STRING':False,
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated"
    ],
    'DEFAULT_AUTHENTICATION_CLASSES': (
        'rest_framework_simplejwt.authentication.JWTAuthentication',
    )
}

SIMPLE_JWT = {
   'AUTH_HEADER_TYPES': ('JWT',),
   "ACCESS_TOKEN_LIFETIME": timedelta(days=10),
}


DJOSER = {
    # 'PASSWORD_RESET_CONFIRM_URL': '#/password/reset/confirm/{uid}/{token}',
    # 'USERNAME_RESET_CONFIRM_URL': '#/username/reset/confirm/{uid}/{token}',
    # 'ACTIVATION_URL': '#/activate/{uid}/{token}',
    # 'SEND_ACTIVATION_EMAIL': True,
    'SERIALIZERS': {
        'user_create':'users.serializers.UserCreateSerializer',
        'current_user':'users.serializers.UserSerializer',
    },
}


SWAGGER_SETTINGS = {
   'SECURITY_DEFINITIONS': {
      'Bearer': {
            'type': 'apiKey',
            'name': 'Authorization',
            'in': 'header',
            'description':'Enter your jwt token format `JWT <your token>`'
      }
   }
}


EMAIL_BACKEND = config(
    "EMAIL_BACKEND",
    default="django.core.mail.backends.smtp.EmailBackend",
)
EMAIL_HOST = config("EMAIL_HOST", default="")
EMAIL_PORT = config("EMAIL_PORT", default=587, cast=int)
EMAIL_USE_TLS = _to_bool(config("EMAIL_USE_TLS", default=True), default=True)
EMAIL_HOST_USER = config("EMAIL_HOST_USER", default="").strip()
EMAIL_HOST_PASSWORD = config("EMAIL_HOST_PASSWORD", default="").replace(" ", "").strip()
DEFAULT_FROM_EMAIL = config(
    "DEFAULT_FROM_EMAIL",
    default=EMAIL_HOST_USER or "no-reply@securevision.local",
).strip()
SUSPICIOUS_EMAIL_ENABLED = _to_bool(config("SUSPICIOUS_EMAIL_ENABLED", default=True), default=True)


if cloudinary and config("CLOUDINARY_CLOUD_NAME", default=""):
    cloudinary.config(
        cloud_name=config("CLOUDINARY_CLOUD_NAME"),
        api_key=config("CLOUDINARY_API_KEY"),
        api_secret=config("CLOUDINARY_API_SECRET"),
        secure=True,
    )

SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
USE_X_FORWARDED_HOST = True

if not DEBUG:
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_BROWSER_XSS_FILTER = True
    SECURE_CONTENT_TYPE_NOSNIFF = True
    SECURE_REFERRER_POLICY = "same-origin"
