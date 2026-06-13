import os

from .base import *  # noqa: F401,F403


DEBUG = os.environ.get("DJANGO_DEBUG", "1").strip().lower() in {"1", "true", "yes", "on"}
ALLOWED_HOSTS = ["127.0.0.1", "localhost"]
CSRF_COOKIE_SECURE = os.environ.get("DJANGO_CSRF_COOKIE_SECURE", "0").strip().lower() in {"1", "true", "yes", "on"}
SESSION_COOKIE_SECURE = os.environ.get("DJANGO_SESSION_COOKIE_SECURE", "0").strip().lower() in {"1", "true", "yes", "on"}
