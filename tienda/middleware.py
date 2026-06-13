from __future__ import annotations

import time

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import logout
from django.shortcuts import redirect
from django.urls import NoReverseMatch, reverse

from .models import UserSecurityProfile


class SessionSecurityMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated:
            force_redirect = self._force_password_change_redirect(request)
            if force_redirect is not None:
                return force_redirect

            timeout_redirect = self._idle_timeout_redirect(request)
            if timeout_redirect is not None:
                return timeout_redirect

        return self.get_response(request)

    def _force_password_change_redirect(self, request):
        if not getattr(settings, "FORCE_INITIAL_PASSWORD_CHANGE", True):
            return None

        profile, _ = UserSecurityProfile.objects.get_or_create(
            user=request.user,
            defaults={"must_change_password": not request.user.is_superuser},
        )
        if not profile.must_change_password:
            return None

        try:
            change_url = reverse("tienda:initial_password_change")
            logout_url = reverse("admin:logout")
        except NoReverseMatch:
            return None

        if request.path in {change_url, logout_url}:
            return None
        if request.path.startswith("/admin/login/"):
            return None

        return redirect(change_url)

    def _idle_timeout_redirect(self, request):
        timeout_seconds = int(getattr(settings, "SESSION_IDLE_TIMEOUT_SECONDS", 1800))
        if timeout_seconds <= 0:
            return None

        now = int(time.time())
        last_activity = request.session.get("last_activity_ts")
        if last_activity is not None and (now - int(last_activity)) > timeout_seconds:
            logout(request)
            messages.warning(request, "Tu sesión se cerró por inactividad.")
            return redirect("admin:login")

        request.session["last_activity_ts"] = now
        request.session.modified = True
        return None
