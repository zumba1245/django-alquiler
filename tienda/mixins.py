from __future__ import annotations

import time

from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpResponse
from django.urls import reverse_lazy
from django.utils.http import url_has_allowed_host_and_scheme


class PrivateViewMixin(LoginRequiredMixin):
    """
    Mixin base para proteger vistas privadas.
    Redirige al login del admin si el usuario no está autenticado.
    """

    login_url = reverse_lazy("admin:login")
    redirect_field_name = "next"


class WriteLoginRequiredMixin(LoginRequiredMixin):
    """
    Exige autenticación solo para métodos de escritura.
    Permite que GET/HEAD/OPTIONS sigan siendo públicos cuando se necesite.
    """

    login_url = reverse_lazy("admin:login")
    redirect_field_name = "next"
    protected_methods = {"POST", "PUT", "PATCH", "DELETE"}

    def dispatch(self, request, *args, **kwargs):
        if request.method in self.protected_methods and not request.user.is_authenticated:
            return self.handle_no_permission()
        # Evitamos la validación global de LoginRequiredMixin para GET.
        return super(LoginRequiredMixin, self).dispatch(request, *args, **kwargs)


class SupervisorRequiredMixin(LoginRequiredMixin):
    """
    Permite acceso solo a superusuario o miembros del grupo 'supervisor'.
    """

    login_url = reverse_lazy("admin:login")
    redirect_field_name = "next"

    def user_is_supervisor(self, user):
        return user.is_superuser or user.groups.filter(name="supervisor").exists()

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        if not self.user_is_supervisor(request.user):
            raise PermissionDenied("Solo supervisor puede acceder a esta operación.")
        return super(LoginRequiredMixin, self).dispatch(request, *args, **kwargs)


class RateLimitedFormMixin:
    """
    Protección básica de tasa por sesión para métodos de escritura.
    """

    rate_limit_methods = {"POST"}
    rate_limit_max_attempts = 20
    rate_limit_window_seconds = 60
    rate_limit_session_key = "_form_rate_limits"

    def get_rate_limit_scope(self, request):
        return self.__class__.__name__

    def get_rate_limit_identity(self, request):
        if request.user.is_authenticated:
            return f"user:{request.user.pk}"
        return f"ip:{request.META.get('REMOTE_ADDR', 'unknown')}"

    def get_rate_limit_max_attempts(self):
        return int(getattr(settings, "RATE_LIMIT_FORM_MAX_ATTEMPTS", self.rate_limit_max_attempts))

    def get_rate_limit_window_seconds(self):
        return int(getattr(settings, "RATE_LIMIT_FORM_WINDOW_SECONDS", self.rate_limit_window_seconds))

    def _is_rate_limited(self, request):
        session_bucket = request.session.get(self.rate_limit_session_key, {})
        scope = f"{self.get_rate_limit_scope(request)}:{self.get_rate_limit_identity(request)}"
        timestamps = session_bucket.get(scope, [])
        now = int(time.time())
        cutoff = now - self.get_rate_limit_window_seconds()
        timestamps = [ts for ts in timestamps if ts >= cutoff]

        if len(timestamps) >= self.get_rate_limit_max_attempts():
            session_bucket[scope] = timestamps
            request.session[self.rate_limit_session_key] = session_bucket
            request.session.modified = True
            return True

        timestamps.append(now)
        session_bucket[scope] = timestamps
        request.session[self.rate_limit_session_key] = session_bucket
        request.session.modified = True
        return False

    def dispatch(self, request, *args, **kwargs):
        if request.method in self.rate_limit_methods and self._is_rate_limited(request):
            return HttpResponse(
                "Demasiados intentos. Espera un momento e inténtalo de nuevo.",
                status=429,
            )
        return super().dispatch(request, *args, **kwargs)


class PaginatedOrderedListMixin:
    """
    Mixin reutilizable para paginación + ordenamiento por query params.

    Query params:
    - per_page: tamaño de página (1..100)
    - order: campo de ordenamiento (prefijo '-' para descendente)
    """

    paginate_by = 20
    paginate_by_param = "per_page"
    ordering_param = "order"
    ordering_fields: tuple[str, ...] = ()
    default_ordering = None
    per_page_options: tuple[int, ...] = (10, 20, 50, 100)
    max_ordering_levels = 3

    def get_paginate_by(self, queryset):
        raw_value = self.request.GET.get(self.paginate_by_param)
        if raw_value and raw_value.isdigit():
            value = int(raw_value)
            return max(1, min(value, 100))
        return super().get_paginate_by(queryset)

    def get_requested_ordering(self):
        raw_values = self.request.GET.getlist(self.ordering_param)
        cleaned_values = []

        for raw_value in raw_values:
            if raw_value is None:
                continue
            for candidate in str(raw_value).split(","):
                candidate = candidate.strip()
                if not candidate:
                    continue
                field = candidate.lstrip("-")
                if field in self.ordering_fields and candidate not in cleaned_values:
                    cleaned_values.append(candidate)
                if len(cleaned_values) >= self.max_ordering_levels:
                    return cleaned_values
        return cleaned_values

    def get_ordering(self):
        requested_ordering = self.get_requested_ordering()
        if requested_ordering:
            if len(requested_ordering) == 1:
                return requested_ordering[0]
            return requested_ordering

        if self.default_ordering is not None:
            return self.default_ordering
        return super().get_ordering()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        current_order_list = self.get_requested_ordering()
        context["current_order"] = (
            current_order_list[0]
            if len(current_order_list) == 1
            else ",".join(current_order_list)
        )
        context["current_order_list"] = current_order_list
        context["ordering_slots"] = (
            current_order_list + [""] * self.max_ordering_levels
        )[: self.max_ordering_levels]
        context["current_per_page"] = self.request.GET.get(self.paginate_by_param, self.paginate_by)
        context["per_page_options"] = self.per_page_options
        context["ordering_fields"] = self.ordering_fields
        return context


class NextUrlRedirectMixin:
    """
    Permite volver al listado filtrado usando query param/post param `next`.
    """

    next_field_name = "next"

    def get_next_url(self):
        candidate = (
            self.request.POST.get(self.next_field_name)
            or self.request.GET.get(self.next_field_name)
        )
        if candidate and url_has_allowed_host_and_scheme(
            url=candidate,
            allowed_hosts={self.request.get_host()},
            require_https=self.request.is_secure(),
        ):
            return candidate
        return None

    def get_success_url(self):
        next_url = self.get_next_url()
        if next_url:
            return next_url
        return super().get_success_url()
