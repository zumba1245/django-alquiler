import os
from pathlib import Path


# Build paths inside the project like this: BASE_DIR / "subdir".
BASE_DIR = Path(__file__).resolve().parent.parent.parent


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


# SECURITY WARNING: keep the secret key used in production secret.
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "django-insecure-dev-key-change-me")

DEBUG = _env_bool("DJANGO_DEBUG", default=False)
ALLOWED_HOSTS = []
CSRF_COOKIE_SECURE = _env_bool("DJANGO_CSRF_COOKIE_SECURE", default=False)
SESSION_COOKIE_SECURE = _env_bool("DJANGO_SESSION_COOKIE_SECURE", default=False)


INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "tienda",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "tienda.middleware.SessionSecurityMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "alquiler_site.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "tienda.context_processors.breadcrumbs",
            ],
        },
    },
]

WSGI_APPLICATION = "alquiler_site.wsgi.application"
ASGI_APPLICATION = "alquiler_site.asgi.application"


DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}


AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
]


LANGUAGE_CODE = "es-es"
TIME_ZONE = "Europe/Madrid"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"

# Regla de negocio configurable para validación de formulario de película.
PELICULA_PRECIO_MINIMO = 0
RATE_LIMIT_FORM_MAX_ATTEMPTS = int(os.environ.get("DJANGO_RATE_LIMIT_FORM_MAX_ATTEMPTS", "20"))
RATE_LIMIT_FORM_WINDOW_SECONDS = int(os.environ.get("DJANGO_RATE_LIMIT_FORM_WINDOW_SECONDS", "60"))
FORCE_INITIAL_PASSWORD_CHANGE = _env_bool("DJANGO_FORCE_INITIAL_PASSWORD_CHANGE", default=True)
SESSION_IDLE_TIMEOUT_SECONDS = int(os.environ.get("DJANGO_SESSION_IDLE_TIMEOUT_SECONDS", "1800"))

LOG_DIR = Path(os.environ.get("DJANGO_LOG_DIR", BASE_DIR / "logs")).expanduser()
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE_MAX_BYTES = int(os.environ.get("DJANGO_LOG_FILE_MAX_BYTES", str(1024 * 1024)))
LOG_FILE_BACKUP_COUNT = int(os.environ.get("DJANGO_LOG_FILE_BACKUP_COUNT", "5"))

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "%(levelname)s %(asctime)s %(name)s %(message)s",
        },
    },
    "handlers": {
        "error_file": {
            "class": "logging.handlers.RotatingFileHandler",
            "level": "ERROR",
            "filename": str(LOG_DIR / "errors.log"),
            "maxBytes": LOG_FILE_MAX_BYTES,
            "backupCount": LOG_FILE_BACKUP_COUNT,
            "formatter": "verbose",
            "encoding": "utf-8",
        },
    },
    "root": {
        "handlers": ["error_file"],
        "level": "ERROR",
    },
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
